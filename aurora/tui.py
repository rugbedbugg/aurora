"""A curses front end for Aurora that uses only the terminal's default colours."""

import contextlib
import curses
import io
import sys
from collections import OrderedDict

from aurora import burst, cli, device, image

POLLING = [125, 250, 500, 1000]
KNOWN_DPI = sorted(image.DPI_LABEL)
FUNCTION_NAMES = list(cli.FUNCTIONS)
EFFECTS = cli.EFFECTS
PROFILE_NAMES = ["Office", "Game I", "Game II", "Media"]
TABS = ["Buttons (Office)", "Performance", "Backlight", "Profiles"]
FOOTER = "Left/Right change  Up/Down select  Tab tab  a apply  ? keys  q quit"
KEYS = [
    "Left/Right or h/l   change the selected value",
    "Up/Down or k/j      select a row",
    "Tab / Shift-Tab     next / previous tab",
    "[ and ]             change by 1 (double click speed)",
    "r g b / R G B       raise / lower a colour channel",
    "u                   undo the selected row",
    "x                   undo every pending change",
    "a                   apply the pending changes",
    "Ctrl-R              reload from the mouse",
    "!                   accept the device state as the last known good",
    "q                   quit",
]
UNVERIFIED = "range unverified, only small values were seen"


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


class Row:
    def __init__(self, key, label, show, step=None, rgb=None, hint=""):
        self.key, self.label, self.show, self.step, self.rgb, self.hint = key, label, show, step, rgb, hint


def polling_step(img, d, fine):
    cur = image.get_polling(img)
    new = POLLING[clamp((POLLING.index(cur) if cur in POLLING else 0) + d, 0, len(POLLING) - 1)]
    return lambda im: image.set_polling(im, new)


def dpi_step(n):
    def step(img, d, fine):
        cur = image.get_dpi_index(img, n)
        if cur in KNOWN_DPI:
            new = KNOWN_DPI[clamp(KNOWN_DPI.index(cur) + d, 0, len(KNOWN_DPI) - 1)]
        else:
            above = [k for k in KNOWN_DPI if cur is not None and k > cur]
            below = [k for k in KNOWN_DPI if cur is not None and k < cur]
            new = above[0] if d > 0 and above else below[-1] if d < 0 and below else KNOWN_DPI[0]
        return lambda im: image.set_dpi_stage(im, n, new)

    return step


def dpi_show(n):
    def show(img):
        i = image.get_dpi_index(img, n)
        label = image.DPI_LABEL.get(i)
        return f"{label} DPI" if label else f"index {i} (value unknown)"

    return show


def toggle_step(addr, bit, setter):
    def step(img, d, fine):
        on = not img[addr] >> bit & 1
        return lambda im: setter(im, on)

    return step


def number_step(get, setter, lo, hi, coarse=1):
    def step(img, d, fine):
        cur = get(img)
        if cur is None:
            return None
        new = clamp(cur + d * (1 if fine else coarse), lo, hi)
        return lambda im: setter(im, new)

    return step


def effect_step(img, d, fine):
    cur = image.get_led_effect(img)
    new = clamp((cur if cur is not None else -1) + d, 0, len(EFFECTS) - 1)
    return lambda im: image.set_led_effect(im, new)


def effect_show(img):
    e = image.get_led_effect(img)
    return EFFECTS[e] if e is not None and e < len(EFFECTS) else f"unknown ({img[0x1C]:02x})"


def button_step(n):
    def step(img, d, fine):
        name = cli.FUNCTION_NAME.get(image.get_button(img, n)[0])
        i = FUNCTION_NAMES.index(name) if name in FUNCTION_NAMES else 0
        new = cli.FUNCTIONS[FUNCTION_NAMES[clamp(i + d, 0, len(FUNCTION_NAMES) - 1)]]
        return lambda im: image.set_button(im, n, new)

    return step


def button_show(n):
    return lambda img: cli.FUNCTION_NAME.get(image.get_button(img, n)[0], "unknown")


def build_rows():
    rgb_hint = "r/g/b raise, R/G/B lower, 0 to 15"
    buttons = [
        Row(
            f"button.{n}",
            f"Button {n}",
            button_show(n),
            button_step(n),
            hint="at least one button must stay Left Click",
        )
        for n in range(1, 9)
    ]
    perf = [
        Row("polling", "Polling rate", lambda i: f"{image.get_polling(i)} Hz", polling_step),
        Row(
            "fire-time",
            "Double click speed",
            lambda i: f"{i[0x1A] | i[0x1B] << 8} ms",
            number_step(lambda i: i[0x1A] | i[0x1B] << 8, image.set_fire_time, 0, 300, 10),
            hint="arrows change by 10, [ and ] by 1, up to 300 ms",
        ),
        Row(
            "dpi-active",
            "Active DPI stage",
            lambda i: str(i[0x18] - 0x18 + 1),
            number_step(
                lambda i: i[0x18] - 0x18 + 1, lambda im, v: image.set_active_dpi_stage(im, v - 1), 1, 6
            ),
            hint="the active stage must be enabled",
        ),
    ]
    for n in range(6):
        perf.append(
            Row(
                f"dpi.{n + 1}",
                f"DPI stage {n + 1}",
                dpi_show(n),
                dpi_step(n),
                hint="only values read from the vendor app are offered",
            )
        )
        perf.append(
            Row(
                f"dpi-enable.{n + 1}",
                f"  stage {n + 1} enabled",
                lambda i, n=n: "on" if i[0x19] >> n & 1 else "off",
                toggle_step(0x19, n, lambda im, on, n=n: image.set_dpi_enabled(im, n, on)),
                hint="at least one stage must stay enabled",
            )
        )
        perf.append(
            Row(
                f"dpi-colour.{n + 1}",
                f"  stage {n + 1} colour",
                None,
                None,
                rgb=(
                    lambda i, n=n: image.get_dpi_colour(i, n),
                    lambda im, c, n=n: image.set_dpi_colour(im, n, *c),
                ),
                hint=rgb_hint + " (the app shows stage pairs swapped)",
            )
        )
    light = [
        Row("effect", "Effect", effect_show, effect_step),
        Row(
            "brightness",
            "Brightness",
            lambda i: f"{i[0x3F] >> 4}",
            number_step(lambda i: i[0x3F] >> 4, image.set_brightness, 0, 15),
            hint=UNVERIFIED,
        ),
        Row(
            "cycle-time",
            "Cycle time",
            lambda i: "n/a" if image.get_led_cycle_time(i) is None else str(image.get_led_cycle_time(i)),
            number_step(image.get_led_cycle_time, image.set_led_cycle_time, 0, 15),
            hint=UNVERIFIED,
        ),
        Row(
            "symmetry",
            "Symmetry",
            lambda i: "on" if i[0x3A] >> 6 & 1 else "off",
            toggle_step(0x3A, 6, image.set_led_symmetry),
        ),
    ]
    for s in range(7):
        light.append(
            Row(
                f"led-colour.{s}",
                f"LED colour {s}",
                None,
                None,
                rgb=(
                    lambda i, s=s: image.get_led_colour(i, s),
                    lambda im, c, s=s: image.set_led_colour(im, s, *c),
                ),
                hint=rgb_hint,
            )
        )
    profiles = [
        Row(
            "profile",
            "Active profile",
            lambda i: PROFILE_NAMES[i[0x01] >> 5 & 3],
            number_step(lambda i: i[0x01] >> 5 & 3, image.set_profile, 0, 3),
            hint="the Buttons tab shows the Office table only",
        )
    ]
    return dict(zip(TABS, [buttons, perf, light, profiles], strict=True))


def read_device():
    dev = device.Device()
    try:
        return burst.read_image(dev)
    finally:
        dev.close()


class Screen:
    def __init__(self, scr, base, offline, structure, drift):
        self.scr, self.base, self.offline = scr, base, offline
        self.structure, self.drift = structure, drift
        self.rows = build_rows()
        self.tab, self.sel, self.top = 0, 0, 0
        self.pending = OrderedDict()
        self.work = dict(base)
        self.msg = ""
        self.colours = False
        self.pairs = {}
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        try:
            curses.use_default_colors()
            if curses.has_colors():
                names = [
                    curses.COLOR_RED,
                    curses.COLOR_GREEN,
                    curses.COLOR_YELLOW,
                    curses.COLOR_BLUE,
                    curses.COLOR_MAGENTA,
                    curses.COLOR_CYAN,
                    curses.COLOR_WHITE,
                ]
                for i, color in enumerate(names, 1):
                    curses.init_pair(i, -1, color)
                    self.pairs[color] = i
                self.colours = True
        except curses.error:
            self.colours = False

    def current_rows(self):
        return self.rows[TABS[self.tab]]

    def recompute(self):
        self.work = dict(self.base)
        for patch in self.pending.values():
            patch(self.work)

    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and x < w:
            try:
                self.scr.addstr(y, x, text[: max(0, w - x - 1)], attr)
            except curses.error:
                pass

    def swatch(self, rgb):
        on = tuple(1 if c >= 8 else 0 for c in rgb)
        names = {
            (1, 0, 0): ("red", curses.COLOR_RED),
            (0, 1, 0): ("green", curses.COLOR_GREEN),
            (1, 1, 0): ("yellow", curses.COLOR_YELLOW),
            (0, 0, 1): ("blue", curses.COLOR_BLUE),
            (1, 0, 1): ("magenta", curses.COLOR_MAGENTA),
            (0, 1, 1): ("cyan", curses.COLOR_CYAN),
            (1, 1, 1): ("white", curses.COLOR_WHITE),
        }
        name, color = names.get(on, ("off", None))
        if self.colours and color is not None:
            return "    ", curses.color_pair(self.pairs[color])
        return name, curses.A_BOLD

    def draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        if h < 12 or w < 50:
            self.put(0, 0, "terminal too small, need 50x12")
            self.scr.refresh()
            return
        title = (
            "Aurora: EvoFox Blaze"
            + ("  [offline]" if self.offline else "")
            + ("  [read only]" if self.structure else "")
        )
        self.put(0, 1, title, curses.A_BOLD)
        x = 1
        for i, name in enumerate(TABS):
            self.put(1, x, f" {name} ", curses.A_REVERSE if i == self.tab else 0)
            x += len(name) + 3
        rows = self.current_rows()
        room = max(1, h - 8)
        self.top = clamp(self.top, max(0, self.sel - room + 1), self.sel)
        for line, row in enumerate(rows[self.top : self.top + room]):
            idx = self.top + line
            dirty = row.key in self.pending
            attr = curses.A_REVERSE if idx == self.sel else 0
            self.put(
                3 + line,
                1,
                f"{'*' if dirty else ' '} {row.label:<24}",
                attr | (curses.A_BOLD if dirty else 0),
            )
            if row.rgb:
                rgb = row.rgb[0](self.work)
                self.put(3 + line, 28, f"{rgb[0]:>2} {rgb[1]:>2} {rgb[2]:>2}  ", attr)
                text, sattr = self.swatch(rgb)
                self.put(3 + line, 38, text, sattr)
            else:
                self.put(3 + line, 28, row.show(self.work), attr)
        if self.tab == 0 and self.work[0x01] >> 5 & 3:
            self.put(
                h - 6, 1, "The active profile is not Office. These buttons are not in use.", curses.A_BOLD
            )
        if self.structure:
            banner = "the device read looks wrong, writes are disabled: " + "; ".join(self.structure)
        elif self.drift:
            banner = "the device differs from the last verified state, press ! to accept it"
        else:
            banner = ""
        self.put(h - 5, 1, banner, curses.A_BOLD)
        self.put(h - 4, 1, rows[self.sel].hint if rows else "", curses.A_DIM)
        count = len(self.pending)
        self.put(
            h - 3,
            1,
            f"{count} pending change{'s' if count != 1 else ''}",
            curses.A_BOLD if count else curses.A_DIM,
        )
        self.put(h - 2, 1, self.msg)
        self.put(h - 1, 1, FOOTER, curses.A_DIM)
        self.scr.refresh()

    def say(self, text):
        self.msg = text
        self.draw()

    def wait_key(self):
        return self.scr.getch()

    def ask(self, question):
        self.say(question + " (y/n)")
        while True:
            key = self.wait_key()
            if key in (ord("y"), ord("Y")):
                return True
            if key in (ord("n"), ord("N"), 27):
                return False

    def overlay(self):
        self.scr.erase()
        self.put(0, 1, "Keys", curses.A_BOLD)
        for i, line in enumerate(KEYS):
            self.put(2 + i, 1, line)
        self.put(3 + len(KEYS), 1, "Press any key to go back.", curses.A_DIM)
        self.scr.refresh()
        self.wait_key()

    def value_of(self, row, img):
        return row.rgb[0](img) if row.rgb else row.show(img)

    def change(self, key, patch):
        row = self.current_rows()[self.sel]
        before = self.value_of(row, self.base)
        previous = self.pending.get(key)
        self.pending[key] = patch
        try:
            self.recompute()
            image.check_invariants(self.work)
        except (ValueError, image.Unmapped) as exc:
            if previous is None:
                del self.pending[key]
            else:
                self.pending[key] = previous
            self.recompute()
            self.msg = f"refused: {exc}"
            return
        if self.value_of(row, self.work) == before:
            del self.pending[key]
            self.recompute()
        self.msg = ""

    def step(self, d, fine=False):
        row = self.current_rows()[self.sel]
        if row.step is None:
            return
        patch = row.step(self.work, d, fine)
        if patch is not None:
            self.change(row.key, patch)

    def channel(self, index, d):
        row = self.current_rows()[self.sel]
        if not row.rgb:
            return
        rgb = list(row.rgb[0](self.work))
        rgb[index] = (rgb[index] + d) % 16
        rgb = tuple(rgb)
        self.change(row.key, lambda im: row.rgb[1](im, rgb))

    def reload(self):
        self.say("Reading the mouse, about 7 seconds...")
        try:
            img = image.load_sample() if self.offline else read_device()
        except Exception as exc:
            self.msg = f"read failed: {exc}"
            return False
        self.base = img
        self.pending.clear()
        self.recompute()
        self.msg = "reloaded"
        return True

    def apply(self):
        if not self.pending:
            self.msg = "nothing to apply"
            return
        if self.structure:
            self.msg = "the device read looks wrong, writes are disabled"
            return
        if not self.ask(f"Apply {len(self.pending)} change(s) to the mouse?"):
            self.msg = "cancelled"
            return
        if self.offline:
            self.base = dict(self.work)
            self.pending.clear()
            self.msg = "offline: nothing was written"
            return
        self.say("Writing and verifying, about 25 seconds. Do not unplug the mouse...")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                ok = burst.apply(list(self.pending.values()), False)
            except Exception as exc:
                ok = False
                print(exc)
        self.scr.clear()
        tail = buf.getvalue().strip().splitlines()
        if ok and self.reload():
            self.drift = []
            self.msg = "applied and verified by read-back"
        elif ok:
            self.msg = "applied, but the reload failed: " + self.msg
        else:
            self.msg = "apply failed: " + (tail[-1] if tail else "unknown error")

    def accept(self):
        if self.offline:
            self.msg = "offline mode has no device"
            return
        if self.pending:
            self.msg = "undo or apply the pending changes first"
            return
        if not self.ask("Accept the current device state as the last known good?"):
            return
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = burst.rebaseline()
        self.scr.clear()
        if ok:
            self.drift = []
        out = buf.getvalue().strip().splitlines()
        self.msg = out[-1] if out else "done"

    def run(self):
        while True:
            self.draw()
            key = self.wait_key()
            rows = self.current_rows()
            if key in (ord("q"), ord("Q")):
                if not self.pending or self.ask("Discard the pending changes and quit?"):
                    return
            elif key in (curses.KEY_DOWN, ord("j")):
                self.sel = min(len(rows) - 1, self.sel + 1)
            elif key in (curses.KEY_UP, ord("k")):
                self.sel = max(0, self.sel - 1)
            elif key == 9:
                self.tab, self.sel, self.top = (self.tab + 1) % len(TABS), 0, 0
            elif key == curses.KEY_BTAB:
                self.tab, self.sel, self.top = (self.tab - 1) % len(TABS), 0, 0
            elif key in (curses.KEY_RIGHT, ord("l")):
                self.step(1)
            elif key in (curses.KEY_LEFT, ord("h")):
                self.step(-1)
            elif key == ord("]"):
                self.step(1, True)
            elif key == ord("["):
                self.step(-1, True)
            elif key in (ord("r"), ord("g"), ord("b")):
                self.channel("rgb".index(chr(key)), 1)
            elif key in (ord("R"), ord("G"), ord("B")):
                self.channel("RGB".index(chr(key)), -1)
            elif key == ord("u"):
                self.pending.pop(rows[self.sel].key, None)
                self.recompute()
            elif key == ord("x"):
                self.pending.clear()
                self.recompute()
            elif key == ord("a"):
                self.apply()
            elif key == 18:
                self.reload()
            elif key == ord("!"):
                self.accept()
            elif key == ord("?"):
                self.overlay()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    offline = "--offline" in argv
    structure, drift = [], []
    if offline:
        base = image.load_sample()
    else:
        print("Reading the mouse, about 7 seconds...", flush=True)
        try:
            base = read_device()
        except device.DeviceError as exc:
            print("error:", exc, file=sys.stderr)
            return 3
        structure = burst.validate_read(base, None)
        last_good = burst.load_last_good()
        drift = [p for p in burst.validate_read(base, last_good) if p not in structure]
    curses.wrapper(lambda scr: Screen(scr, base, offline, structure, drift).run())
    return 0


if __name__ == "__main__":
    sys.exit(main())

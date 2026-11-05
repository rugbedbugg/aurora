"""A curses front end for Aurora that follows the layout of the vendor app.

The screen is an 80x24 canvas. Every control has a fixed place on it, and the arrow keys
move the focus to the nearest control in that direction.
"""

import contextlib
import curses
import io
import sys
from collections import OrderedDict, namedtuple

from aurora import burst, cli, device, image

CANVAS_W, CANVAS_H = 80, 24
POLLING = [125, 250, 500, 1000]
KNOWN_DPI = sorted(image.DPI_LABEL)
PROFILE_NAMES = ["Office", "Game I", "Game II", "Media"]
TABS = ["Button", "Macro", "Performance", "Backlight"]
FUNCTION_LABELS = {
    "none": "No Function",
    "left": "Left Click",
    "middle": "Middle Click",
    "right": "Right Click",
    "backward": "Backward",
    "forward": "Forward",
    "dpi-loop": "DPI Loop",
    "show-desktop": "Show Desktop",
    "double-click": "Double Click",
    "rapid-fire": "Rapid Fire",
    "led-loop": "LED Loop",
    "dpi-up": "DPI +",
    "dpi-down": "DPI -",
    "fn": "Fn function",
    "profile-office": "Office",
    "profile-game-1": "Game I",
    "profile-game-2": "Game II",
}
EFFECT_LABELS = [
    "DPI Breathing Effect",
    "Cycle Breathing Effect",
    "Light On",
    "Flowing Water Effect",
    "Mono Water Effect",
    "Comet Streak",
    "Neon",
    "Ambilight",
    "Flicker",
    "Star Trek",
    "Ripple",
    "Enraptured",
    "Button Response",
    "LED Off",
]
UNVERIFIED = "range unverified, only small values were seen"
FOOTER = "Arrows move  Enter change  +/- adjust  Tab tab  a apply  ? keys  q quit"
KEYS = [
    "Arrows or h j k l   move to the nearest control",
    "Enter or Space      open a list, toggle, select or press",
    "+ or = / -          adjust a slider by its step",
    "] / [               adjust a slider by 1",
    "r g b / R G B       raise / lower a colour channel on a swatch",
    "s                   make the selected DPI stage the active one",
    "Tab / Shift-Tab     next / previous tab",
    "u                   undo the selected control",
    "x                   undo every pending change (same as Cancel)",
    "a                   apply the pending changes",
    "Ctrl-R              reload from the mouse",
    "!                   accept the device state as the last known good",
    "q                   quit",
]
ART = [
    r"      .--------.      ",
    r"    .' 1  |  2  '.    ",
    r"   /      |3|      \  ",
    r"  | 8     |_|       | ",
    r"  |     6     7     | ",
    r" 4|                 | ",
    r" 5|                 | ",
    r"  \                 / ",
    r"   '.             .'  ",
    r"     '-._______.-'    ",
]

Edit = namedtuple("Edit", "key value patch")


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


class Widget:
    """One control or label at a fixed place on the canvas."""

    def __init__(self, kind, key, y, x, w, **kw):
        self.kind, self.key, self.y, self.x, self.w = kind, key, y, x, w
        self.text = kw.get("text", "")
        self.value = kw.get("value")
        self.options = kw.get("options")
        self.toggle = kw.get("toggle")
        self.choose = kw.get("choose")
        self.selected = kw.get("selected")
        self.bar = kw.get("bar")
        self.adjust = kw.get("adjust")
        self.rgb = kw.get("rgb")
        self.action = kw.get("action")
        self.index = kw.get("index")
        self.stage = kw.get("stage")
        self.hint = kw.get("hint", "")
        self.enabled = kw.get("enabled", True)
        self.dim = kw.get("dim", False)
        self.bold = kw.get("bold", False)

    @property
    def focusable(self):
        return self.enabled and self.kind != "label"


class Model:
    """The settings being edited. It holds the device image and the pending edits, and no curses."""

    def __init__(self, base, offline=False, structure=None, drift=None):
        self.base = base
        self.work = dict(base)
        self.pending = OrderedDict()
        self.offline = offline
        self.structure = structure or []
        self.drift = drift or []
        self.dpi_sel = 0
        self.msg = ""

    def recompute(self):
        self.work = dict(self.base)
        for patch in self.pending.values():
            patch(self.work)

    def change(self, edit):
        """Apply an edit to the working image. Return False and set a message if it is refused."""
        before = edit.value(self.base)
        previous = self.pending.get(edit.key)
        self.pending[edit.key] = edit.patch
        try:
            self.recompute()
            image.check_invariants(self.work)
        except (ValueError, image.Unmapped) as exc:
            if previous is None:
                del self.pending[edit.key]
            else:
                self.pending[edit.key] = previous
            self.recompute()
            self.msg = f"refused: {exc}"
            return False
        if edit.value(self.work) == before:
            del self.pending[edit.key]
            self.recompute()
        self.msg = ""
        return True

    def undo(self, key):
        self.pending.pop(key, None)
        self.recompute()

    def undo_all(self):
        self.pending.clear()
        self.recompute()

    def reset(self, base):
        self.base = base
        self.pending.clear()
        self.recompute()


def nearest(widgets, cur, direction):
    """Return the focusable widget closest to cur in a direction, or None."""
    cx, cy = cur.x + cur.w / 2, cur.y
    best, best_score = None, None
    for w in widgets:
        if w is cur or not w.focusable:
            continue
        dx, dy = w.x + w.w / 2 - cx, w.y - cy
        if direction == "up" and dy < 0:
            score = -dy * 4 + abs(dx)
        elif direction == "down" and dy > 0:
            score = dy * 4 + abs(dx)
        elif direction == "left" and dx < 0 and abs(dy) <= 1:
            score = -dx + abs(dy) * 8
        elif direction == "right" and dx > 0 and abs(dy) <= 1:
            score = dx + abs(dy) * 8
        else:
            continue
        if best_score is None or score < best_score:
            best, best_score = w, score
    return best


def dpi_label(n):
    def label(img):
        i = image.get_dpi_index(img, n)
        value = image.DPI_LABEL.get(i)
        return str(value) if value else f"i{i}"

    return label


def dpi_step(n):
    """Return a function that steps stage n along the DPI values read from the vendor app."""

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


def button_label(n):
    return lambda img: FUNCTION_LABELS.get(cli.FUNCTION_NAME.get(image.get_button(img, n)[0]), "unknown")


def effect_label(img):
    e = image.get_led_effect(img)
    return EFFECT_LABELS[e] if e is not None and e < len(EFFECT_LABELS) else f"unknown ({img[0x1C]:02x})"


def fire_time(img):
    return img[0x1A] | img[0x1B] << 8


def profile_of(img):
    return img[0x01] >> 5 & 3


def tab_widgets():
    spec = [("Button", 2), ("Macro", 13), ("Performance", 49), ("Backlight", 65)]
    return [
        Widget("tab", f"tab.{name}", 1, x, len(name) + 4, text=name, index=i, hint="Enter opens the tab")
        for i, (name, x) in enumerate(spec)
    ]


def footer_widgets():
    widgets = []
    x = 2
    for i, name in enumerate(PROFILE_NAMES):
        w = len(name) + 4
        widgets.append(
            Widget(
                "choice",
                "profile",
                19,
                x,
                w,
                text=name,
                selected=lambda img, i=i: profile_of(img) == i,
                choose=lambda img, i=i: Edit("profile", profile_of, lambda im: image.set_profile(im, i)),
                hint="the Button tab edits the Office table only",
            )
        )
        x += w + 2
    widgets.append(
        Widget("action", "apply", 19, 57, 9, text="Apply", action="apply", hint="write the pending changes")
    )
    widgets.append(
        Widget("action", "cancel", 19, 67, 10, text="Cancel", action="cancel", hint="undo every change")
    )
    for text, x, w in (("Import", 2, 10), ("Export", 13, 10), ("Reset", 24, 9)):
        widgets.append(Widget("action", text.lower(), 20, x, w, text=text, enabled=False))
    return widgets


def button_widgets():
    widgets = []
    for n in range(1, 9):
        left = n <= 4
        y = 5 + 3 * ((n - 1) % 4)
        number_x, box_x = (3, 5) if left else (55, 57)
        widgets.append(Widget("label", None, y, number_x, 1, text=str(n), bold=True))

        def options(img, n=n):
            key, value = f"button.{n}", button_label(n)
            return [
                (FUNCTION_LABELS[name], Edit(key, value, lambda im, f=function: image.set_button(im, n, f)))
                for name, function in cli.FUNCTIONS.items()
            ]

        widgets.append(
            Widget(
                "pick",
                f"button.{n}",
                y,
                box_x,
                20,
                value=button_label(n),
                options=options,
                index=n,
                hint="at least one button must stay Left Click",
            )
        )
    widgets.append(Widget("action", "music", 16, 3, 18, text="Music-lighting", enabled=False))
    return widgets


def performance_widgets(model):
    widgets = [
        Widget("label", None, 4, 3, 17, text="Mouse Sensitivity", dim=True),
        Widget("label", None, 5, 3, 36, text="[-----------o------]  set by the OS", dim=True),
        Widget("label", None, 7, 3, 12, text="Scroll Speed", dim=True),
        Widget("label", None, 8, 3, 36, text="[-----------o------]  set by the OS", dim=True),
        Widget("label", None, 10, 3, 18, text="Double Click Speed"),
        Widget(
            "slider",
            "fire-time",
            11,
            3,
            34,
            value=lambda img: str(fire_time(img)),
            bar=lambda img: (fire_time(img), 0, 300, f"{fire_time(img)} / 300ms"),
            adjust=lambda img, d, fine: Edit(
                "fire-time",
                lambda im: str(fire_time(im)),
                (lambda ms: lambda im: image.set_fire_time(im, ms))(
                    clamp(fire_time(img) + d * (1 if fine else 10), 0, 300)
                ),
            ),
            hint="+/- by 10, [ and ] by 1, up to 300 ms",
        ),
        Widget("label", None, 4, 41, 17, text="Polling Rate (Hz)"),
    ]
    x = 41
    for hz in POLLING:
        w = len(str(hz)) + 4
        widgets.append(
            Widget(
                "choice",
                "polling",
                5,
                x,
                w,
                text=str(hz),
                selected=lambda img, hz=hz: image.get_polling(img) == hz,
                choose=lambda img, hz=hz: Edit(
                    "polling", lambda im: str(image.get_polling(im)), lambda im: image.set_polling(im, hz)
                ),
            )
        )
        x += w + 2
    widgets.append(Widget("label", None, 7, 41, 11, text="DPI Control"))
    for n in range(6):
        x = 41 + 6 * n
        key = f"dpi.{n + 1}"
        widgets.append(
            Widget(
                "toggle",
                f"dpi-enable.{n + 1}",
                8,
                x,
                3,
                value=lambda img, n=n: "on" if img[0x19] >> n & 1 else "off",
                toggle=lambda img, n=n: Edit(
                    f"dpi-enable.{n + 1}",
                    lambda im: "on" if im[0x19] >> n & 1 else "off",
                    (lambda on: lambda im: image.set_dpi_enabled(im, n, on))(not img[0x19] >> n & 1),
                ),
                selected=lambda img, n=n: bool(img[0x19] >> n & 1),
                stage=n,
                hint="at least one stage must stay enabled",
            )
        )

        def options(img, n=n, key=key):
            return [
                (f"{label} DPI", Edit(key, dpi_label(n), lambda im, i=index: image.set_dpi_stage(im, n, i)))
                for index, label in sorted(image.DPI_LABEL.items())
            ]

        widgets.append(
            Widget(
                "pick",
                key,
                9,
                x,
                5,
                value=dpi_label(n),
                options=options,
                stage=n,
                hint="Enter lists the DPI values",
            )
        )
        widgets.append(
            Widget(
                "swatch",
                f"dpi-colour.{n + 1}",
                10,
                x,
                4,
                rgb=(
                    lambda img, n=n: image.get_dpi_colour(img, n),
                    lambda im, c, n=n: image.set_dpi_colour(im, n, *c),
                ),
                stage=n,
                hint="r/g/b raise, R/G/B lower. The vendor app shows stage pairs swapped",
            )
        )

    def dpi_bar(img):
        n = model.dpi_sel
        i = image.get_dpi_index(img, n)
        pos = KNOWN_DPI.index(i) if i in KNOWN_DPI else 0
        return pos, 0, len(KNOWN_DPI) - 1, f"stage {n + 1}: {dpi_label(n)(img)}"

    def dpi_adjust(img, d, fine):
        n = model.dpi_sel
        return Edit(f"dpi.{n + 1}", dpi_label(n), dpi_step(n)(img, d, fine))

    widgets.append(
        Widget(
            "slider",
            "dpi-slider",
            13,
            41,
            36,
            value=lambda img: dpi_label(model.dpi_sel)(img),
            bar=dpi_bar,
            adjust=dpi_adjust,
            hint="+/- changes the selected stage, s makes it the active stage",
        )
    )
    return widgets


def backlight_widgets():
    widgets = [
        Widget("label", None, 4, 38, 6, text="Effect"),
        Widget(
            "pick",
            "effect",
            5,
            38,
            30,
            value=effect_label,
            options=lambda img: [
                (name, Edit("effect", effect_label, lambda im, i=i: image.set_led_effect(im, i)))
                for i, name in enumerate(EFFECT_LABELS)
            ],
            hint="Enter lists the effects",
        ),
        Widget("label", None, 6, 38, 13, text="Cycle colours"),
    ]
    for n in range(7):
        x = 38 + 5 * n
        widgets.append(
            Widget(
                "swatch",
                f"led-colour.{n}",
                7,
                x,
                4,
                rgb=(
                    lambda img, n=n: image.get_led_colour(img, n),
                    lambda im, c, n=n: image.set_led_colour(im, n, *c),
                ),
                hint="r/g/b raise, R/G/B lower, 0 to 15",
            )
        )
        widgets.append(
            Widget(
                "toggle",
                f"cycle-colour.{n}",
                8,
                x,
                3,
                value=lambda img, n=n: "on" if image.get_cycle_colour_enabled(img, n) else "off",
                toggle=lambda img, n=n: Edit(
                    f"cycle-colour.{n}",
                    lambda im: "on" if image.get_cycle_colour_enabled(im, n) else "off",
                    (lambda on: lambda im: image.set_cycle_colour_enabled(im, n, on))(
                        not image.get_cycle_colour_enabled(img, n)
                    ),
                ),
                selected=lambda img, n=n: image.get_cycle_colour_enabled(img, n),
                hint="the bit to colour order is assumed, check it on the mouse",
            )
        )
    widgets += [
        Widget("label", None, 10, 38, 10, text="Brightness"),
        Widget(
            "slider",
            "brightness",
            10,
            50,
            26,
            value=lambda img: str(img[0x3F] >> 4),
            bar=lambda img: (img[0x3F] >> 4, 0, 15, str(img[0x3F] >> 4)),
            adjust=lambda img, d, fine: Edit(
                "brightness",
                lambda im: str(im[0x3F] >> 4),
                (lambda v: lambda im: image.set_brightness(im, v))(clamp((img[0x3F] >> 4) + d, 0, 15)),
            ),
            hint=UNVERIFIED,
        ),
        Widget("label", None, 11, 38, 5, text="Speed"),
        Widget(
            "slider",
            "cycle-time",
            11,
            50,
            26,
            value=lambda img: str(image.get_led_cycle_time(img)),
            bar=lambda img: (
                image.get_led_cycle_time(img) or 0,
                0,
                15,
                str(image.get_led_cycle_time(img) or "n/a"),
            ),
            adjust=lambda img, d, fine: (
                None
                if image.get_led_cycle_time(img) is None
                else Edit(
                    "cycle-time",
                    lambda im: str(image.get_led_cycle_time(im)),
                    (lambda v: lambda im: image.set_led_cycle_time(im, v))(
                        clamp(image.get_led_cycle_time(img) + d, 0, 15)
                    ),
                )
            ),
            hint=UNVERIFIED + ", n/a for Button Response and LED Off",
        ),
        Widget(
            "toggle",
            "symmetry",
            13,
            38,
            14,
            text="Symmetry",
            value=lambda img: "on" if img[0x3A] >> 6 & 1 else "off",
            toggle=lambda img: Edit(
                "symmetry",
                lambda im: "on" if im[0x3A] >> 6 & 1 else "off",
                (lambda on: lambda im: image.set_led_symmetry(im, on))(not img[0x3A] >> 6 & 1),
            ),
            selected=lambda img: bool(img[0x3A] >> 6 & 1),
        ),
        Widget("label", None, 14, 38, 40, text="( ) Clockwise    ( ) Anti Clockwise", dim=True),
        Widget("label", None, 15, 38, 40, text="( ) Two way      ( ) Overwrite", dim=True),
        Widget("label", None, 16, 38, 40, text="direction is not decoded yet", dim=True),
    ]
    return widgets


def build_widgets(model):
    """Return the widgets of every tab. Each list also holds the tab bar and the bottom bar."""
    common = tab_widgets() + footer_widgets()
    return {
        "Button": common + button_widgets(),
        "Macro": common,
        "Performance": common + performance_widgets(model),
        "Backlight": common + backlight_widgets(),
    }


def read_device():
    dev = device.Device()
    try:
        return burst.read_image(dev)
    finally:
        dev.close()


class Screen:
    def __init__(self, scr, model):
        self.scr, self.model = scr, model
        self.tabs = build_widgets(model)
        self.tab = 0
        self.focus = self.first_body()
        self.colours = False
        self.pairs = {}
        self.oy = self.ox = 0
        curses.set_escdelay(25)
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

    @property
    def widgets(self):
        return self.tabs[TABS[self.tab]]

    def first_body(self):
        body = [w for w in self.widgets if w.focusable and w.y >= 3 and w.y < 18]
        return min(body, key=lambda w: (w.y, w.x)) if body else self.widgets[0]

    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        y, x = y + self.oy, x + self.ox
        if 0 <= y < h and 0 <= x < w:
            try:
                self.scr.addstr(y, x, text[: max(0, w - x - 1)], attr)
            except curses.error:
                pass

    def line(self, y, x, n):
        try:
            self.scr.hline(y + self.oy, x + self.ox, curses.ACS_HLINE, n)
        except curses.error:
            pass

    def box(self, y, x, h, w):
        for yy in range(y + 1, y + h - 1):
            for xx in (x, x + w - 1):
                try:
                    self.scr.addch(yy + self.oy, xx + self.ox, curses.ACS_VLINE)
                except curses.error:
                    pass
        self.line(y, x + 1, w - 2)
        self.line(y + h - 1, x + 1, w - 2)
        for yy, xx, ch in (
            (y, x, curses.ACS_ULCORNER),
            (y, x + w - 1, curses.ACS_URCORNER),
            (y + h - 1, x, curses.ACS_LLCORNER),
            (y + h - 1, x + w - 1, curses.ACS_LRCORNER),
        ):
            try:
                self.scr.addch(yy + self.oy, xx + self.ox, ch)
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
        return name[:4].ljust(4), curses.A_BOLD

    def dirty(self, w):
        pending = self.model.pending
        if w.kind == "choice":
            return w.key in pending and w.selected(self.model.work)
        if w.key == "dpi-slider":
            return f"dpi.{self.model.dpi_sel + 1}" in pending
        return w.key in pending

    def draw_widget(self, w):
        work = self.model.work
        focused = w is self.focus
        attr = curses.A_DIM if not w.enabled or w.dim else 0
        if w.bold:
            attr |= curses.A_BOLD
        if focused:
            attr |= curses.A_REVERSE
        dirty = self.dirty(w)
        if dirty:
            attr |= curses.A_BOLD
            self.put(w.y, w.x - 1, "*", curses.A_BOLD)
        if w.kind == "label":
            self.put(w.y, w.x, w.text, attr)
        elif w.kind == "tab":
            current = self.tab == w.index
            self.put(w.y, w.x, f"[ {w.text} ]", attr | (curses.A_BOLD if current else 0))
        elif w.kind == "pick":
            text = w.value(work)
            s = f"[{text:<{w.w - 3}}v]" if w.w >= 12 else text.center(w.w)
            self.put(w.y, w.x, s, attr)
        elif w.kind == "toggle":
            on = w.selected(work)
            self.put(w.y, w.x, f"[{'x' if on else ' '}]" + (f" {w.text}" if w.text else ""), attr)
        elif w.kind == "choice":
            on = w.selected(work)
            self.put(w.y, w.x, f"({'o' if on else ' '}) {w.text}", attr | (curses.A_BOLD if on else 0))
        elif w.kind == "action":
            self.put(w.y, w.x, f"[ {w.text} ]", attr)
        elif w.kind == "slider":
            cur, lo, hi, text = w.bar(work)
            bw = w.w - len(text) - 3
            k = round((cur - lo) / (hi - lo) * (bw - 1)) if hi > lo else 0
            self.put(w.y, w.x, "[" + "=" * k + "o" + "-" * (bw - 1 - k) + "] " + text, attr)
        elif w.kind == "swatch":
            text, sattr = self.swatch(w.rgb[0](work))
            if focused:
                self.put(w.y, w.x - 1, "[", curses.A_REVERSE)
                self.put(w.y, w.x + 4, "]", curses.A_REVERSE)
            self.put(w.y, w.x, text, sattr | (curses.A_BOLD if dirty else 0))

    def draw_art(self, x, numbers):
        for y, line in enumerate(ART):
            self.put(4 + y, x, "".join(" " if c.isdigit() else c for c in line))
        for y, line in enumerate(ART if numbers else []):
            for dx, c in enumerate(line):
                if c.isdigit():
                    key = f"button.{c}"
                    on = self.focus.key == key
                    self.put(4 + y, x + dx, c, curses.A_REVERSE if on else curses.A_BOLD)

    def draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        if h < CANVAS_H or w < CANVAS_W:
            self.put(0, 0, "need 80x24")
            self.scr.refresh()
            return
        self.oy, self.ox = (h - CANVAS_H) // 2, (w - CANVAS_W) // 2
        model = self.model
        flags = ("  [offline]" if model.offline else "") + ("  [read only]" if model.structure else "")
        self.put(0, 2, "Aurora", curses.A_BOLD)
        self.put(0, 32, "E V O F O X   B L A Z E", curses.A_BOLD)
        self.put(0, 79 - len(flags), flags, curses.A_DIM)
        self.line(2, 1, 78)
        self.line(18, 1, 78)
        name = TABS[self.tab]
        if name == "Button":
            self.draw_art(30, True)
        elif name == "Macro":
            self.put(10, 26, "Macros are not supported yet", curses.A_DIM)
        elif name == "Backlight":
            self.draw_art(6, False)
            self.box(3, 35, 15, 44)
        else:
            active = model.work[0x18] - 0x18
            self.put(11, 41 + 6 * active + 2, "^", curses.A_BOLD)
        for w in self.widgets:
            self.draw_widget(w)
        if name == "Button" and profile_of(model.work):
            self.put(17, 3, "The active profile is not Office. These buttons are not in use.", curses.A_BOLD)
        hint = self.focus.hint
        if self.focus.kind == "swatch":
            r, g, b = self.focus.rgb[0](model.work)
            hint = f"R {r}  G {g}  B {b}   " + hint
        self.put(21, 2, hint, curses.A_DIM)
        count = len(model.pending)
        text = f"{count} pending change{'s' if count != 1 else ''}"
        self.put(20, 79 - len(text), text, curses.A_BOLD if count else curses.A_DIM)
        if model.structure:
            banner = "the device read looks wrong, writes are disabled: " + "; ".join(model.structure)
        elif model.drift:
            banner = "the device differs from the last verified state, press ! to accept it"
        else:
            banner = ""
        self.put(22, 2, model.msg or banner, curses.A_BOLD)
        self.put(23, 2, FOOTER, curses.A_DIM)
        self.scr.refresh()

    def say(self, text):
        self.model.msg = text
        self.draw()

    def ask(self, question):
        self.say(question + " (y/n)")
        while True:
            key = self.scr.getch()
            if key in (ord("y"), ord("Y")):
                return True
            if key in (ord("n"), ord("N"), 27):
                return False

    def popup(self, title, labels, current):
        """Show a list over the canvas. Return the chosen index, or None if it is cancelled."""
        height = min(len(labels), 14)
        width = max(len(s) for s in [*labels, title]) + 6
        y0, x0 = (CANVAS_H - height - 2) // 2, (CANVAS_W - width) // 2
        sel = current if current is not None else 0
        top = 0
        while True:
            top = clamp(top, max(0, sel - height + 1), min(sel, max(0, len(labels) - height)))
            for yy in range(y0, y0 + height + 2):
                self.put(yy, x0, " " * width)
            self.box(y0, x0, height + 2, width)
            self.put(y0, x0 + 2, f" {title} ", curses.A_BOLD)
            for i in range(height):
                j = top + i
                self.put(y0 + 1 + i, x0 + 2, labels[j].ljust(width - 4), curses.A_REVERSE if j == sel else 0)
            self.scr.refresh()
            key = self.scr.getch()
            if key in (curses.KEY_DOWN, ord("j")):
                sel = min(len(labels) - 1, sel + 1)
            elif key in (curses.KEY_UP, ord("k")):
                sel = max(0, sel - 1)
            elif key == curses.KEY_NPAGE:
                sel = min(len(labels) - 1, sel + height)
            elif key == curses.KEY_PPAGE:
                sel = max(0, sel - height)
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                return sel
            elif key in (27, ord("q")):
                return None

    def overlay(self):
        self.scr.erase()
        self.put(0, 2, "Keys", curses.A_BOLD)
        for i, line in enumerate(KEYS):
            self.put(2 + i, 2, line)
        self.put(3 + len(KEYS), 2, "Press any key to go back.", curses.A_DIM)
        self.scr.refresh()
        self.scr.getch()

    def move(self, direction):
        target = nearest(self.widgets, self.focus, direction)
        if target is not None:
            self.focus = target
            if target.stage is not None:
                self.model.dpi_sel = target.stage

    def switch_tab(self, index):
        self.tab = index % len(TABS)
        self.focus = self.first_body()
        if self.focus.stage is not None:
            self.model.dpi_sel = self.focus.stage

    def activate(self):
        w, model = self.focus, self.model
        if w.kind == "tab":
            self.switch_tab(w.index)
        elif w.kind == "pick":
            options = w.options(model.work)
            labels = [label for label, _ in options]
            current = w.value(model.work)
            index = next((i for i, label in enumerate(labels) if current in (label, label.split()[0])), None)
            choice = self.popup(w.key.replace(".", " "), labels, index)
            if choice is not None:
                model.change(options[choice][1])
        elif w.kind in ("toggle", "choice"):
            model.change((w.toggle or w.choose)(model.work))
        elif w.kind == "action" and w.action == "apply":
            self.apply()
        elif w.kind == "action" and w.action == "cancel":
            model.undo_all()
        elif w.kind == "slider":
            model.msg = "use + and - on a slider"

    def adjust(self, d, fine=False):
        w = self.focus
        if w.kind == "slider" and w.adjust is not None:
            edit = w.adjust(self.model.work, d, fine)
            if edit is not None:
                self.model.change(edit)

    def channel(self, index, d):
        w = self.focus
        if w.kind != "swatch":
            return
        rgb = list(w.rgb[0](self.model.work))
        rgb[index] = (rgb[index] + d) % 16
        rgb = tuple(rgb)
        self.model.change(Edit(w.key, w.rgb[0], lambda im: w.rgb[1](im, rgb)))

    def make_active(self):
        w = self.focus
        if w.stage is None:
            return
        n = w.stage
        value = lambda img: str(img[0x18] - 0x18 + 1)  # noqa: E731
        self.model.change(Edit("dpi-active", value, lambda im: image.set_active_dpi_stage(im, n)))

    def reload(self):
        self.say("Reading the mouse, about 7 seconds...")
        try:
            img = image.load_sample() if self.model.offline else read_device()
        except Exception as exc:
            self.model.msg = f"read failed: {exc}"
            return False
        self.model.reset(img)
        self.model.msg = "reloaded"
        return True

    def apply(self):
        model = self.model
        if not model.pending:
            model.msg = "nothing to apply"
            return
        if model.structure:
            model.msg = "the device read looks wrong, writes are disabled"
            return
        if not self.ask(f"Apply {len(model.pending)} change(s) to the mouse?"):
            model.msg = "cancelled"
            return
        if model.offline:
            model.reset(dict(model.work))
            model.msg = "offline: nothing was written"
            return
        self.say("Writing and verifying, about 25 seconds. Do not unplug the mouse...")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                ok = burst.apply(list(model.pending.values()), False)
            except Exception as exc:
                ok = False
                print(exc)
        self.scr.clear()
        tail = buf.getvalue().strip().splitlines()
        if ok and self.reload():
            model.drift = []
            model.msg = "applied and verified by read-back"
        elif ok:
            model.msg = "applied, but the reload failed: " + model.msg
        else:
            model.msg = "apply failed: " + (tail[-1] if tail else "unknown error")

    def accept(self):
        model = self.model
        if model.offline:
            model.msg = "offline mode has no device"
            return
        if model.pending:
            model.msg = "undo or apply the pending changes first"
            return
        if not self.ask("Accept the current device state as the last known good?"):
            return
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = burst.rebaseline()
        self.scr.clear()
        if ok:
            model.drift = []
        out = buf.getvalue().strip().splitlines()
        model.msg = out[-1] if out else "done"

    def run(self):
        arrows = {
            curses.KEY_UP: "up",
            curses.KEY_DOWN: "down",
            curses.KEY_LEFT: "left",
            curses.KEY_RIGHT: "right",
            ord("k"): "up",
            ord("j"): "down",
            ord("h"): "left",
            ord("l"): "right",
        }
        while True:
            self.draw()
            key = self.scr.getch()
            model = self.model
            if key in (ord("q"), ord("Q")):
                if not model.pending or self.ask("Discard the pending changes and quit?"):
                    return
            elif key in arrows:
                self.move(arrows[key])
            elif key == 9:
                self.switch_tab(self.tab + 1)
            elif key == curses.KEY_BTAB:
                self.switch_tab(self.tab - 1)
            elif key in (10, 13, curses.KEY_ENTER, ord(" ")):
                self.activate()
            elif key in (ord("+"), ord("=")):
                self.adjust(1)
            elif key == ord("-"):
                self.adjust(-1)
            elif key == ord("]"):
                self.adjust(1, True)
            elif key == ord("["):
                self.adjust(-1, True)
            elif key in (ord("r"), ord("g"), ord("b")):
                self.channel("rgb".index(chr(key)), 1)
            elif key in (ord("R"), ord("G"), ord("B")):
                self.channel("RGB".index(chr(key)), -1)
            elif key == ord("s"):
                self.make_active()
            elif key == ord("u"):
                target = self.focus.key
                if self.focus.key == "dpi-slider":
                    target = f"dpi.{model.dpi_sel + 1}"
                model.undo(target)
            elif key == ord("x"):
                model.undo_all()
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
        drift = [p for p in burst.validate_read(base, burst.load_last_good()) if p not in structure]
    model = Model(base, offline, structure, drift)
    curses.wrapper(lambda scr: Screen(scr, model).run())
    return 0


if __name__ == "__main__":
    sys.exit(main())

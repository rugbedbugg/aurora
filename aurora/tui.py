"""A curses front end for Aurora. It is laid out like the vendor app and styled like rmpc.

The screen is an 80x24 canvas of bordered panes. Every control has a fixed place in a pane.
The arrow keys and h, j, k and l move the focus to the nearest control in that direction.
"""

import contextlib
import curses
import io
import locale
import os
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
FOOTER = "hjkl move  Enter change  +/- adjust  Tab tab  : command  ? help  q quit"
KEYS = [
    "h j k l or arrows   move to the nearest control",
    "Enter or Space      open a list, toggle, select or press",
    "+ or = / -          adjust a slider by its step",
    "] / [               adjust a slider by 1",
    "s                   make the selected DPI stage the active one",
    "Tab / Shift-Tab     next / previous tab",
    "                    (Shift-Tab needs a terminal that sends it)",
    "1 2 3 4             go to a tab",
    "gt / gT             next / previous tab",
    "gg / G              first / last control",
    "u                   undo the selected control",
    "x                   undo every pending change (same as Cancel)",
    "a                   apply the pending changes",
    ":                   command line, for example :set polling=1000",
    "Ctrl-R              reload from the mouse",
    "!                   accept the device state as the last known good",
    "?                   this help",
    "q                   quit",
]
COMMANDS = [
    "set KEY=VALUE ...   stage settings, the same names as aurora set",
    "apply  (or w)       apply the pending changes",
    "cancel (or undo)    undo every pending change",
    "reload              read the mouse again",
    "rebaseline          accept the device state as the last known good",
    "tab NAME or NUMBER  go to a tab",
    "quit  (or q)        quit, asking first when changes are pending",
    "quit! (or q!)       quit without asking",
    "help                this list",
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

Edit = namedtuple("Edit", "key patch")
Pane = namedtuple("Pane", "y x h w title")
Command = namedtuple("Command", "action edits arg")

PANES = {
    "Button": [
        Pane(3, 1, 15, 26, "Buttons 1-4"),
        Pane(3, 27, 15, 26, "Blaze"),
        Pane(3, 53, 15, 26, "Buttons 5-8"),
    ],
    "Macro": [Pane(3, 1, 15, 78, "Macros")],
    "Performance": [Pane(3, 1, 15, 37, "Mouse"), Pane(3, 38, 15, 41, "Polling and DPI")],
    "Backlight": [Pane(3, 1, 15, 34, "Blaze"), Pane(3, 35, 15, 44, "Lighting")],
}
ACTION_PANE = Pane(18, 1, 4, 78, "")


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

    @property
    def focusable(self):
        return self.enabled and self.kind != "label"


class CommandError(Exception):
    pass


class Model:
    """The settings being edited. It holds the device image and the pending edits. It has no curses code."""

    def __init__(self, base, offline=False, structure=None, drift=None):
        self.base = base
        self.work = dict(base)
        self.pending = OrderedDict()
        self.offline = offline
        self.structure = structure or []
        self.drift = drift or []
        self.dpi_sel = 0
        self.msg = ""

    def image_with(self, pending):
        img = dict(self.base)
        for patch in pending.values():
            patch(img)
        return img

    def change(self, edit):
        """Apply an edit to the working image. Return False and set a message if it is refused."""
        trial = OrderedDict(self.pending)
        trial[edit.key] = edit.patch
        try:
            work = self.image_with(trial)
            image.check_invariants(work)
        except (ValueError, image.Unmapped) as exc:
            self.msg = f"refused: {exc}"
            return False
        rest = OrderedDict((k, p) for k, p in trial.items() if k != edit.key)
        if self.image_with(rest) == work:
            del trial[edit.key]
        self.pending, self.work, self.msg = trial, work, ""
        return True

    def undo(self, key):
        self.pending.pop(key, None)
        self.work = self.image_with(self.pending)

    def undo_all(self):
        self.pending.clear()
        self.work = dict(self.base)

    def reset(self, base):
        self.base = base
        self.undo_all()


def nearest(widgets, cur, direction):
    """Return the focusable widget closest to cur in a direction. Return None if there is none."""
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


def summary(img):
    """Return the one line the header shows: polling, active DPI and effect."""
    hz = image.get_polling(img)
    active = dpi_label(img[0x18] - 0x18)(img)
    return f"{hz} Hz | {active} DPI | {effect_label(img)}"


def parse_command(text):
    """Parse one command line. Raise CommandError for text that is not a command."""
    parts = text.split()
    if not parts:
        return Command("none", [], None)
    name, args = parts[0], parts[1:]
    if name == "set":
        if not args:
            raise CommandError("set needs KEY=VALUE")
        edits = []
        for arg in args:
            try:
                patch = cli.parse_setting(arg)
            except (ValueError, KeyError, image.Unmapped) as exc:
                raise CommandError(str(exc)) from exc
            edits.append(Edit(arg.split("=", 1)[0], patch))
        return Command("set", edits, None)
    simple = {
        "apply": "apply",
        "w": "apply",
        "cancel": "cancel",
        "undo": "cancel",
        "reload": "reload",
        "rebaseline": "rebaseline",
        "quit": "quit",
        "q": "quit",
        "quit!": "force-quit",
        "q!": "force-quit",
        "help": "help",
    }
    if name in simple:
        return Command(simple[name], [], None)
    if name == "tab":
        if len(args) != 1:
            raise CommandError("tab needs a name or a number")
        arg = args[0].lower()
        if arg.isdigit() and 1 <= int(arg) <= len(TABS):
            return Command("tab", [], int(arg) - 1)
        matches = [i for i, t in enumerate(TABS) if t.lower().startswith(arg)]
        if len(matches) == 1:
            return Command("tab", [], matches[0])
        raise CommandError(f"no tab {args[0]!r}")
    raise CommandError(f"unknown command {name!r}")


def tab_widgets():
    spec = [("Button", 2), ("Macro", 11), ("Performance", 19), ("Backlight", 33)]
    return [
        Widget("tab", f"tab.{name}", 2, x, len(name) + 2, text=name, index=i, hint="Enter opens the tab")
        for i, (name, x) in enumerate(spec)
    ]


def footer_widgets():
    widgets = []
    x = 3
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
                choose=lambda img, i=i: Edit("profile", lambda im: image.set_profile(im, i)),
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
    for text, x, w in (("Import", 3, 10), ("Export", 14, 10), ("Reset", 25, 9)):
        widgets.append(Widget("action", text.lower(), 20, x, w, text=text, enabled=False))
    return widgets


def button_widgets():
    widgets = []
    for n in range(1, 9):
        left = n <= 4
        y = 5 + 3 * ((n - 1) % 4)
        number_x, box_x = (3, 5) if left else (55, 57)
        widgets.append(Widget("label", None, y, number_x, 1, text=str(n)))

        def options(img, n=n):
            key = f"button.{n}"
            return [
                (FUNCTION_LABELS[name], Edit(key, lambda im, f=function: image.set_button(im, n, f)))
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
        Widget("label", None, 5, 3, 31, text="[-----------o------]  set by OS", dim=True),
        Widget("label", None, 7, 3, 12, text="Scroll Speed", dim=True),
        Widget("label", None, 8, 3, 31, text="[-----------o------]  set by OS", dim=True),
        Widget("label", None, 10, 3, 18, text="Double Click Speed"),
        Widget(
            "slider",
            "fire-time",
            11,
            3,
            32,
            bar=lambda img: (fire_time(img), 0, 300, f"{fire_time(img)} / 300ms"),
            adjust=lambda img, d, fine: Edit(
                "fire-time",
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
                choose=lambda img, hz=hz: Edit("polling", lambda im: image.set_polling(im, hz)),
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
                toggle=lambda img, n=n: Edit(
                    f"dpi-enable.{n + 1}",
                    (lambda on: lambda im: image.set_dpi_enabled(im, n, on))(not img[0x19] >> n & 1),
                ),
                selected=lambda img, n=n: bool(img[0x19] >> n & 1),
                stage=n,
                hint="at least one stage must stay enabled",
            )
        )

        def options(img, n=n, key=key):
            return [
                (f"{label} DPI", Edit(key, lambda im, i=index: image.set_dpi_stage(im, n, i)))
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
                text=f"DPI stage {n + 1} colour",
                stage=n,
                hint="Enter edits the colour. The vendor app shows stage pairs swapped",
            )
        )

    def dpi_bar(img):
        n = model.dpi_sel
        i = image.get_dpi_index(img, n)
        pos = KNOWN_DPI.index(i) if i in KNOWN_DPI else 0
        return pos, 0, len(KNOWN_DPI) - 1, f"stage {n + 1}: {dpi_label(n)(img)}"

    def dpi_adjust(img, d, fine):
        n = model.dpi_sel
        return Edit(f"dpi.{n + 1}", dpi_step(n)(img, d, fine))

    widgets.append(
        Widget(
            "slider",
            "dpi-slider",
            13,
            41,
            36,
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
                (name, Edit("effect", lambda im, i=i: image.set_led_effect(im, i)))
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
                text=f"Cycle colour {n + 1}",
                hint="Enter edits the colour",
            )
        )
        widgets.append(
            Widget(
                "toggle",
                f"cycle-colour.{n}",
                8,
                x,
                3,
                toggle=lambda img, n=n: Edit(
                    f"cycle-colour.{n}",
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
            bar=lambda img: (img[0x3F] >> 4, 0, 15, str(img[0x3F] >> 4)),
            adjust=lambda img, d, fine: Edit(
                "brightness",
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
            toggle=lambda img: Edit(
                "symmetry",
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


def read_device(progress=None):
    dev = device.Device()
    try:
        return burst.read_image(dev, progress)
    finally:
        dev.close()


def wants_unicode():
    """Return True when the terminal can show the box and block characters."""
    return (
        locale.getpreferredencoding(False).lower().replace("-", "") == "utf8"
        and os.environ.get("TERM") != "linux"
    )


class Screen:
    def __init__(self, scr, model, square=False):
        self.scr, self.model = scr, model
        self.tabs = build_widgets(model)
        self.tab = 0
        self.focus = self.first_body()
        self.colours = False
        self.pairs = {}
        self.unicode = wants_unicode()
        self.rounded = self.unicode and not square
        self.accent = self.current = self.mark = 0
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
                curses.init_pair(8, curses.COLOR_BLUE, -1)
                curses.init_pair(9, curses.COLOR_BLACK, curses.COLOR_BLUE)
                curses.init_pair(10, curses.COLOR_YELLOW, -1)
                self.colours = True
        except curses.error:
            self.colours = False
        if self.colours:
            self.accent = curses.color_pair(8)
            self.current = curses.color_pair(9) | curses.A_BOLD
            self.mark = curses.color_pair(10) | curses.A_BOLD
        else:
            self.current = curses.A_REVERSE | curses.A_BOLD
            self.mark = curses.A_BOLD

    @property
    def widgets(self):
        return self.tabs[TABS[self.tab]]

    def first_body(self):
        body = self.body()
        return body[0] if body else self.widgets[0]

    def body(self):
        found = [w for w in self.widgets if w.focusable and 3 < w.y < 18]
        return sorted(found, key=lambda w: (w.y, w.x))

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
            self.scr.hline(y + self.oy, x + self.ox, curses.ACS_HLINE, n, self.accent)
        except curses.error:
            pass

    def box(self, y, x, h, w, title="", right=False):
        """Draw a pane border with the title set into the top edge."""
        if self.unicode:
            tl, tr, bl, br = ("╭", "╮", "╰", "╯") if self.rounded else ("┌", "┐", "└", "┘")
            self.put(y, x, tl + "─" * (w - 2) + tr, self.accent)
            self.put(y + h - 1, x, bl + "─" * (w - 2) + br, self.accent)
            for yy in range(y + 1, y + h - 1):
                self.put(yy, x, "│", self.accent)
                self.put(yy, x + w - 1, "│", self.accent)
        else:
            for yy in range(y + 1, y + h - 1):
                for xx in (x, x + w - 1):
                    try:
                        self.scr.addch(yy + self.oy, xx + self.ox, curses.ACS_VLINE, self.accent)
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
                    self.scr.addch(yy + self.oy, xx + self.ox, ch, self.accent)
                except curses.error:
                    pass
        if title:
            title = title[: w - 8]
            self.put(y, x + w - len(title) - 4 if right else x + 2, f" {title} ")

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
        if focused:
            attr = self.current
        if self.dirty(w):
            self.put(w.y, w.x - 1, "*", self.mark)
        if w.kind == "label":
            self.put(w.y, w.x, w.text, attr)
        elif w.kind == "tab":
            active = self.tab == w.index
            style = self.current if active else attr
            self.put(w.y, w.x, f" {w.text} ", style | (curses.A_UNDERLINE if focused and not active else 0))
        elif w.kind == "pick":
            text = w.value(work)
            s = f"[{text:<{w.w - 3}}v]" if w.w >= 12 else text.ljust(w.w)
            self.put(w.y, w.x, s, attr)
        elif w.kind == "toggle":
            on = w.selected(work)
            self.put(w.y, w.x, f"[{'x' if on else ' '}]" + (f" {w.text}" if w.text else ""), attr)
        elif w.kind == "choice":
            on = w.selected(work)
            self.put(w.y, w.x, f"({'o' if on else ' '}) {w.text}", attr)
        elif w.kind == "action":
            self.put(w.y, w.x, f"[ {w.text} ]", attr)
        elif w.kind == "slider":
            cur, lo, hi, text = w.bar(work)
            bw = w.w - len(text) - 3
            k = round((cur - lo) / (hi - lo) * (bw - 1)) if hi > lo else 0
            full, empty = ("█", " ") if self.unicode else ("=", "-")
            self.put(w.y, w.x, "[", attr)
            self.put(w.y, w.x + 1, full * k, self.accent)
            self.put(w.y, w.x + 1 + k, "█" if self.unicode else "o", self.accent)
            self.put(w.y, w.x + 2 + k, empty * (bw - 1 - k) + "] " + text, attr)
        elif w.kind == "swatch":
            text, sattr = self.swatch(w.rgb[0](work))
            if focused:
                self.put(w.y, w.x - 1, "[", self.current)
                self.put(w.y, w.x + 4, "]", self.current)
            self.put(w.y, w.x, text, sattr)

    def draw_art(self, x, numbers):
        for y, line in enumerate(ART):
            self.put(4 + y, x, "".join(" " if c.isdigit() else c for c in line), self.accent)
        for y, line in enumerate(ART if numbers else []):
            for dx, c in enumerate(line):
                if c.isdigit():
                    on = self.focus.key == f"button.{c}"
                    self.put(4 + y, x + dx, c, self.current if on else 0)

    def draw_header(self):
        model = self.model
        flags = ("[offline]" if model.offline else "") + (" [read only]" if model.structure else "")
        self.put(0, 2, "Aurora", self.accent)
        self.put(0, 34, "EvoFox Blaze")
        profile = PROFILE_NAMES[profile_of(model.work)]
        self.put(0, 77 - len(profile), profile, self.accent)
        self.put(1, 2, summary(model.work), curses.A_DIM)
        self.put(1, 77 - len(flags), flags.strip(), curses.A_DIM)

    def draw_status(self):
        model = self.model
        if model.structure:
            banner = "read looks wrong, writes disabled: " + "; ".join(model.structure)
        elif model.drift:
            banner = "differs from the last verified state, press ! to accept it"
        else:
            banner = ""
        text = (model.msg or banner)[:60]
        self.put(22, 2, text, curses.A_BOLD if model.msg else 0)
        count = len(model.pending)
        pending = f"{count} pending change{'s' if count != 1 else ''}"
        self.put(22, 77 - len(pending), pending, self.mark if count else curses.A_DIM)

    def draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        if h < CANVAS_H or w < CANVAS_W:
            self.put(0, 0, "need 80x24")
            self.scr.refresh()
            return
        self.oy, self.ox = (h - CANVAS_H) // 2, (w - CANVAS_W) // 2
        name = TABS[self.tab]
        self.draw_header()
        for pane in PANES[name]:
            self.box(*pane)
        hint = self.focus.hint
        if self.focus.kind == "swatch":
            r, g, b = self.focus.rgb[0](self.model.work)
            hint = f"R {r} G {g} B {b}  " + hint
        self.box(*ACTION_PANE[:4], title=hint[:68], right=True)
        if name == "Button":
            self.draw_art(30, True)
        elif name == "Macro":
            self.put(10, 26, "Macros are not supported yet", curses.A_DIM)
        elif name == "Backlight":
            self.draw_art(6, False)
        else:
            active = self.model.work[0x18] - 0x18
            self.put(11, 41 + 6 * active + 2, "▲" if self.unicode else "^", self.accent)
        for widget in self.widgets:
            self.draw_widget(widget)
        if name == "Button" and profile_of(self.model.work):
            self.put(17, 3, " not Office: these buttons are not in use ", self.mark)
        self.draw_status()
        self.put(23, 2, FOOTER, curses.A_DIM)
        self.scr.refresh()

    def draw_progress(self, label, frac):
        """Draw a progress bar on the status row. The writer calls this while it works."""
        full = "█" if self.unicode else "#"
        room = 70 - len(label)
        k = int(room * clamp(frac, 0, 1))
        self.put(22, 0, " " * 79)
        self.put(22, 2, label, self.accent)
        self.put(22, 4 + len(label), full * k, self.accent)
        self.put(22, 74, f"{int(frac * 100):3d}%", curses.A_DIM)
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
        """Show a list over the canvas. Return the chosen index. Return None if it is cancelled."""
        height = min(len(labels), 12)
        width = max(len(s) for s in [*labels, title]) + 7
        y0, x0 = (CANVAS_H - height - 2) // 2, (CANVAS_W - width) // 2
        sel = current if current is not None else 0
        top = 0
        while True:
            top = clamp(top, max(0, sel - height + 1), min(sel, max(0, len(labels) - height)))
            for yy in range(y0, y0 + height + 2):
                self.put(yy, x0, " " * width)
            self.box(y0, x0, height + 2, width, title)
            for i in range(height):
                j = top + i
                self.put(y0 + 1 + i, x0 + 2, labels[j].ljust(width - 6), self.current if j == sel else 0)
            if len(labels) > height:
                self.draw_scrollbar(y0 + 1, x0 + width - 3, height, top, len(labels))
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

    def draw_scrollbar(self, y, x, height, top, total):
        """Draw a scrollbar with a thumb sized to the visible share of the list."""
        track, thumb, up, down = ("│", "█", "▲", "▼") if self.unicode else ("|", "#", "^", "v")
        size = max(1, round(height * height / total))
        start = round((height - size) * top / max(1, total - height))
        for i in range(height):
            on = start <= i < start + size
            self.put(y + i, x, thumb if on else track, self.accent if on else 0)
        self.put(y, x, up, self.accent)
        self.put(y + height - 1, x, down, self.accent)

    def colour_modal(self, w):
        """Edit the red, green and blue values of a swatch. Return True when the edit was confirmed."""
        rgb = list(w.rgb[0](self.model.work))
        channel = 0
        y0, x0, width = 8, 24, 32
        while True:
            for yy in range(y0, y0 + 7):
                self.put(yy, x0, " " * width)
            self.box(y0, x0, 7, width, w.text or "Colour")
            full = "█" if self.unicode else "#"
            for i, name in enumerate("RGB"):
                row = y0 + 1 + i
                bar = full * rgb[i] + " " * (15 - rgb[i])
                self.put(row, x0 + 2, f"{name} ", self.current if i == channel else 0)
                self.put(row, x0 + 5, bar, self.accent)
                self.put(row, x0 + 22, f"{rgb[i]:>2}")
            text, sattr = self.swatch(tuple(rgb))
            self.put(y0 + 4, x0 + 5, text, sattr)
            self.put(y0 + 5, x0 + 2, "j/k channel  +/- value  Enter ok", curses.A_DIM)
            self.scr.refresh()
            key = self.scr.getch()
            if key in (curses.KEY_DOWN, ord("j")):
                channel = (channel + 1) % 3
            elif key in (curses.KEY_UP, ord("k")):
                channel = (channel - 1) % 3
            elif key in (curses.KEY_RIGHT, ord("l"), ord("+"), ord("=")):
                rgb[channel] = min(15, rgb[channel] + 1)
            elif key in (curses.KEY_LEFT, ord("h"), ord("-")):
                rgb[channel] = max(0, rgb[channel] - 1)
            elif key in (10, 13, curses.KEY_ENTER):
                chosen = tuple(rgb)
                return self.model.change(Edit(w.key, lambda im, c=chosen: w.rgb[1](im, c)))
            elif key in (27, ord("q")):
                return False

    def help_modal(self):
        self.popup("Help", KEYS + ["", "Commands (press : first)", *COMMANDS], None)

    def command_line(self):
        """Read a command on the status row. Return the text, or None if it is cancelled."""
        text = ""
        while True:
            self.put(22, 0, " " * 79)
            self.put(22, 2, ":" + text + "_", self.accent)
            self.scr.refresh()
            key = self.scr.getch()
            if key in (10, 13, curses.KEY_ENTER):
                return text
            if key == 27:
                return None
            if key in (curses.KEY_BACKSPACE, 127, 8):
                if not text:
                    return None
                text = text[:-1]
            elif 32 <= key < 127 and len(text) < 70:
                text += chr(key)

    def run_command(self, text):
        """Run one command. Return False when the program should quit."""
        model = self.model
        try:
            command = parse_command(text)
        except CommandError as exc:
            model.msg = str(exc)
            return True
        if command.action == "set":
            for edit in command.edits:
                if not model.change(edit):
                    break
        elif command.action == "apply":
            self.apply()
        elif command.action == "cancel":
            model.undo_all()
        elif command.action == "reload":
            self.reload()
        elif command.action == "rebaseline":
            self.accept()
        elif command.action == "tab":
            self.switch_tab(command.arg)
        elif command.action == "help":
            self.help_modal()
        elif command.action == "force-quit":
            return False
        elif command.action == "quit":
            return bool(model.pending) and not self.ask("Discard the pending changes and quit?")
        return True

    def move(self, direction):
        target = nearest(self.widgets, self.focus, direction)
        if direction == "up" and target is not None and target.kind == "tab":
            # Enter the tab bar on the tab that is open.
            target = next(w for w in self.widgets if w.kind == "tab" and w.index == self.tab)
        if target is not None:
            self.focus = target
            if target.stage is not None:
                self.model.dpi_sel = target.stage

    def jump(self, last):
        body = self.body()
        if body:
            self.focus = body[-1] if last else body[0]
            if self.focus.stage is not None:
                self.model.dpi_sel = self.focus.stage

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
        elif w.kind == "swatch":
            self.colour_modal(w)
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

    def make_active(self):
        w = self.focus
        if w.stage is None:
            return
        n = w.stage
        self.model.change(Edit("dpi-active", lambda im: image.set_active_dpi_stage(im, n)))

    def reload(self):
        try:
            if self.model.offline:
                img = image.load_sample()
            else:
                img = read_device(lambda done, total: self.draw_progress("Reading", done / total))
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
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                ok = burst.apply(list(model.pending.values()), False, progress=self.draw_progress)
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
        prefix = ""
        while True:
            self.draw()
            key = self.scr.getch()
            model = self.model
            if prefix:
                chosen, prefix = prefix + (chr(key) if 0 < key < 256 else ""), ""
                if chosen == "gg":
                    self.jump(False)
                elif chosen == "gt":
                    self.switch_tab(self.tab + 1)
                elif chosen == "gT":
                    self.switch_tab(self.tab - 1)
                continue
            if key in (ord("q"), ord("Q")):
                if not model.pending or self.ask("Discard the pending changes and quit?"):
                    return
            elif key == ord("g"):
                prefix = "g"
            elif key == ord("G"):
                self.jump(True)
            elif key in arrows:
                self.move(arrows[key])
            elif key == 9:
                self.switch_tab(self.tab + 1)
            elif key == curses.KEY_BTAB:
                self.switch_tab(self.tab - 1)
            elif ord("1") <= key <= ord("4"):
                self.switch_tab(key - ord("1"))
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
            elif key == ord("s"):
                self.make_active()
            elif key == ord("u"):
                target = self.focus.key
                if target == "dpi-slider":
                    target = f"dpi.{model.dpi_sel + 1}"
                model.undo(target)
            elif key == ord("x"):
                model.undo_all()
            elif key == ord("a"):
                self.apply()
            elif key == ord(":"):
                text = self.command_line()
                model.msg = ""
                if text is not None and not self.run_command(text):
                    return
            elif key == 18:
                self.reload()
            elif key == ord("!"):
                self.accept()
            elif key == ord("?"):
                self.help_modal()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    offline = "--offline" in argv
    square = "--square" in argv or os.environ.get("AURORA_BORDERS") == "square"
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
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    curses.wrapper(lambda scr: Screen(scr, model, square).run())
    return 0


if __name__ == "__main__":
    sys.exit(main())

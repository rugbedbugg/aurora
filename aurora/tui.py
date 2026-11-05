"""A curses front end for Aurora. It is laid out like the vendor app and styled like rmpc.

The screen is a set of bordered panes that fill the terminal. A layout computed from the terminal
size gives every control its place, so the panes grow with the window down to 80x24.
The arrow keys and h, j, k and l move the focus to the nearest control in that direction.
"""

import contextlib
import curses
import io
import locale
import os
import sys
from collections import OrderedDict, namedtuple

from aurora import banner, burst, cli, device, image, logos, pointer, preview, sysinfo

MIN_W, MIN_H = 80, 24
MAX_BAR = 60
MAX_SWATCH_W, MAX_SWATCH_H = 16, 6
INLINE_DPI_W = 13
LABEL_W = 20
EFFECT_LABEL_W = 8
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
    "PgUp / PgDn         scroll the config preview",
    "Ctrl-U / Ctrl-D     scroll the config preview by half a page",
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
Edit = namedtuple("Edit", "key patch")
Pane = namedtuple("Pane", "y x h w title")
Command = namedtuple("Command", "action edits arg")
Layout = namedtuple("Layout", "h w body_y body_h action_y action_h status_y footer_y split")

COLOUR_MODAL_MIN_W, COLOUR_MODAL_MAX_W = 38, 72
COLOUR_HINT = "j/k channel  +/- value  Enter ok"
MIN_DIAGRAM_H, MIN_DIAGRAM_W = 9, 11
DIAGRAM_ASPECT = 1.5
BUTTONS_PANE_W = (30, 46)
NOT_OFFICE = " not Office: these buttons are not in use "
# The split layout has the banner, a 60/40 split and the config preview.
SPLIT_MIN_H, SPLIT_MIN_W = 30, 100
LEFT_SHARE = 0.60
BANNER_ROWS = 6
BUTTONS_PANE_H = 13
# The System section holds the stats (8 rows) or a logo, plus its border. The full logo needs 20 rows.
SYSTEM_SMALL_H, SYSTEM_FULL_H = 11, 23
MOUSE_PANE_H = (13, 23)
PREVIEW_MIN_H = 10
PREVIEW_TITLE = "aurora.toml"
PREVIEW_SECTION = {
    "Button": "buttons",
    "Macro": "header",
    "Performance": "performance",
    "Backlight": "backlight",
}


def clamp(value, lo, hi):
    return max(lo, min(hi, value))


def make_layout(h, w):
    """Return the rows of the screen for a terminal of h rows and w columns (at least 80x24).

    From SPLIT_MIN_H rows and SPLIT_MIN_W columns the screen has the banner and the split layout.
    """
    split = h >= SPLIT_MIN_H and w >= SPLIT_MIN_W
    action_h = (4 if h < 40 else 6) if split else (4 if h < 30 else 6)
    body_y = BANNER_ROWS + 1 if split else 3
    body_h = h - body_y - action_h - 2
    return Layout(h, w, body_y, body_h, body_y + body_h, action_h, h - 2, h - 1, split)


def diagram_size(room_w, room_h, reserve):
    """Return the width and height of the mouse drawing for a pane interior.

    reserve is the number of rows kept free below the top padding. The width is odd so that the
    divider sits in the middle. The body is about 1.5 times as wide as it is tall in cells.
    """
    height = max(MIN_DIAGRAM_H, room_h - reserve)
    width = round(height * DIAGRAM_ASPECT) // 2 * 2 + 1
    widest = room_w - 4 if (room_w - 4) % 2 else room_w - 5
    return max(MIN_DIAGRAM_W, min(width, widest)), height


def split_panes(layout):
    """Return the panes of every tab in the split layout.

    Settings sit on the left. The config preview sits on the right. The System section and the
    mouse pane appear only when the pane below them keeps its minimum height.
    """
    y, h, span = layout.body_y, layout.body_h, layout.w - 2
    left = round(span * LEFT_SHARE)
    right_x, right_w = 1 + left, span - left
    preview_pane = Pane(y, right_x, h, right_w, PREVIEW_TITLE)
    spare = h - BUTTONS_PANE_H
    system_h = SYSTEM_FULL_H if spare >= SYSTEM_FULL_H else SYSTEM_SMALL_H if spare >= SYSTEM_SMALL_H else 0
    button_panes = [Pane(y, 1, system_h, left, "System")] if system_h else []
    button_panes.append(Pane(y + system_h, 1, h - system_h, left, "Buttons"))
    mouse_h = clamp(h // 2, *MOUSE_PANE_H)
    if h - mouse_h >= PREVIEW_MIN_H:
        button_panes.append(Pane(y, right_x, mouse_h, right_w, "Blaze"))
        button_panes.append(Pane(y + mouse_h, right_x, h - mouse_h, right_w, PREVIEW_TITLE))
    else:
        button_panes.append(preview_pane)
    return {
        "Button": button_panes,
        "Macro": [Pane(y, 1, h, left, "Macros"), preview_pane],
        "Performance": [Pane(y, 1, h, left, "Performance"), preview_pane],
        "Backlight": [Pane(y, 1, h, left, "Lighting"), preview_pane],
    }


def make_panes(layout):
    """Return the panes of every tab and the pane of the bottom bar."""
    span = layout.w - 2
    action = Pane(layout.action_y, 1, layout.action_h, span, "")
    if layout.split:
        return split_panes(layout), action
    y, h = layout.body_y, layout.body_h
    buttons = clamp(round(span * 0.32), *BUTTONS_PANE_W)
    button_panes = [Pane(y, 1, h, buttons, "Buttons"), Pane(y, 1 + buttons, h, span - buttons, "Blaze")]
    perf = round(span * 0.40)
    light = clamp(diagram_size(10**6, h - 2, 2)[0] + 8, 24, round(span * 0.44))
    panes = {
        "Button": button_panes,
        "Macro": [Pane(y, 1, h, span, "Macros")],
        "Performance": [Pane(y, 1, h, perf, "Mouse"), Pane(y, 1 + perf, h, span - perf, "Polling and DPI")],
        "Backlight": [Pane(y, 1, h, light, "Blaze"), Pane(y, 1 + light, h, span - light, "Lighting")],
    }
    return panes, action


def pane_titled(panes, title):
    """Return the first pane with a title. Return None when there is none."""
    return next((p for p in panes if p.title == title), None)


def inner(pane):
    """Return x, y, width and height of the room inside a pane, after the border and the marker column."""
    return pane.x + 2, pane.y + 1, pane.w - 4, pane.h - 2


def stack(top, room, items, pad=1):
    """Return the y of each (height, gap) item.

    One row of padding goes above the first item when there is room for it. Spare rows widen the
    gaps, by at most one row each.
    """
    used = sum(h + g for h, g in items)
    pad = pad if room - used >= pad else 0
    gaps = sum(1 for _, g in items if g)
    extra = clamp((room - used - pad) // gaps, 0, 1) if gaps else 0
    ys, y = [], top + pad
    for h, g in items:
        ys.append(y)
        y += h + (g + extra if g else 0)
    return ys


class Widget:
    """One control or label at a place on the screen. h is its height in rows."""

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
        self.live = kw.get("live")
        self.h = kw.get("h", 1)
        self.area = kw.get("area", "body")
        self.group = self.area

    @property
    def focusable(self):
        return self.enabled and self.kind != "label"


class CommandError(Exception):
    pass


class Model:
    """The settings being edited. It holds the device image and the pending edits. It has no curses code."""

    def __init__(self, base, offline=False, structure=None, drift=None, pointer=None):
        self.base = base
        self.pointer = pointer
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
    """Return the focusable widget closest to cur in a direction. Return None if there is none.

    Up and down stay inside the pane of cur when it has a control in that direction.
    """
    cx, cy = cur.x + cur.w / 2, cur.y + (cur.h - 1) / 2
    best, same = None, None
    for w in widgets:
        if w is cur or not w.focusable:
            continue
        dx, dy = w.x + w.w / 2 - cx, w.y + (w.h - 1) / 2 - cy
        same_line = max(1, (cur.h + w.h) / 2 - 0.5)
        if direction == "up" and dy < 0:
            score = -dy * 10 + abs(dx)
        elif direction == "down" and dy > 0:
            score = dy * 10 + abs(dx)
        elif direction == "left" and dx < 0 and abs(dy) <= same_line:
            score = -dx + abs(dy) * 8
        elif direction == "right" and dx > 0 and abs(dy) <= same_line:
            score = dx + abs(dy) * 8
        else:
            continue
        if best is None or score < best[0]:
            best = (score, w)
        if w.group == cur.group and (same is None or score < same[0]):
            same = (score, w)
    if direction in ("up", "down") and same is not None:
        best = same
    return best[1] if best else None


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


def tab_widgets(layout):
    spec = [("Button", 2), ("Macro", 11), ("Performance", 19), ("Backlight", 33)]
    return [
        Widget(
            "tab",
            f"tab.{name}",
            layout.body_y - 1,
            x,
            len(name) + 2,
            text=name,
            index=i,
            hint="Enter opens the tab",
            area="tabs",
        )
        for i, (name, x) in enumerate(spec)
    ]


def footer_widgets(layout):
    small = layout.action_h == 4
    row = layout.action_y + (1 if small else 2)
    spare = layout.action_y + (2 if small else 4)
    pad = 2 if layout.w < 100 else 4
    widgets = []
    x = 3
    for i, name in enumerate(PROFILE_NAMES):
        w = len(name) + 4
        widgets.append(
            Widget(
                "choice",
                "profile",
                row,
                x,
                w,
                text=name,
                selected=lambda img, i=i: profile_of(img) == i,
                choose=lambda img, i=i: Edit("profile", lambda im: image.set_profile(im, i)),
                hint="the Button tab edits the Office table only",
                area="foot",
            )
        )
        x += w + pad
    cancel_x = layout.w - 13
    widgets.append(
        Widget(
            "action",
            "apply",
            row,
            cancel_x - 10,
            9,
            text="Apply",
            action="apply",
            hint="write the pending changes",
            area="foot",
        )
    )
    widgets.append(
        Widget(
            "action",
            "cancel",
            row,
            cancel_x,
            10,
            text="Cancel",
            action="cancel",
            hint="undo every change",
            area="foot",
        )
    )
    for text, x, w in (("Import", 3, 10), ("Export", 14, 10), ("Reset", 25, 9)):
        widgets.append(Widget("action", text.lower(), spare, x, w, text=text, enabled=False, area="foot"))
    return widgets


def button_widgets(layout):
    left = pane_titled(make_panes(layout)[0]["Button"], "Buttons")
    x0, y0, iw, ih = inner(left)
    music_y = y0 + ih - 1
    stride = clamp((ih - 3) // 8, 1, 2)
    first = y0 + max(1, (ih - 1 - (7 * stride + 1)) // 2)
    pick_w = min(iw - 2, 36)
    widgets = []
    for n in range(1, 9):
        y = first + stride * (n - 1)
        widgets.append(Widget("label", None, y, x0, 1, text=str(n)))

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
                x0 + 2,
                pick_w,
                value=button_label(n),
                options=options,
                index=n,
                hint="at least one button must stay Left Click",
            )
        )
    widgets.append(Widget("action", "music", music_y, x0, 18, text="Music-lighting", enabled=False))
    return widgets


def spread(width, count, lowest=0):
    """Return the item width, the gap and the left offset that centre count equal items in width cells."""
    for gap in (2, 1):
        item = min((width - gap * (count - 1)) // count, MAX_SWATCH_W)
        if item >= max(lowest, 8):
            break
    return item, gap, (width - (count * item + gap * (count - 1))) // 2


def pointer_widgets(model, x, ys, width, inline=False):
    """Return the Mouse Sensitivity and Scroll Speed controls. They work only inside Hyprland.

    ys holds one row for each control when inline is set. The label and the slider then share it.
    Otherwise it holds the label row and the slider row of each control.
    """
    live = model.pointer
    rows = [(ys[0], ys[0]), (ys[1], ys[1])] if inline else [(ys[0], ys[1]), (ys[2], ys[3])]
    shift = LABEL_W if inline else 0
    width = width - shift
    out = []
    for (label_y, bar_y), which, label, (lo, hi, _), fmt in zip(
        rows,
        ("sensitivity", "scroll"),
        ("Mouse Sensitivity", "Scroll Speed"),
        (pointer.SENSITIVITY, pointer.SCROLL),
        ("{:+.1f}", "{:.2f}x"),
        strict=True,
    ):
        if live is None:
            dashes = width - 14
            note = "[" + "-" * (dashes // 2) + "o" + "-" * (dashes - dashes // 2) + "]  set by OS"
            out.append(Widget("label", None, label_y, x, len(label), text=label, dim=True))
            out.append(Widget("label", None, bar_y, x + shift, width, text=note, dim=True))
            continue
        out.append(Widget("label", None, label_y, x, len(label), text=label))
        out.append(
            Widget(
                "slider",
                f"pointer.{which}",
                bar_y,
                x + shift,
                width,
                bar=lambda img, which=which, lo=lo, hi=hi, fmt=fmt: (
                    getattr(live, which),
                    lo,
                    hi,
                    fmt.format(getattr(live, which)),
                ),
                live=lambda d, fine, which=which: live.step(which, d),
                hint="applies at once, resets when Hyprland reloads",
            )
        )
    return out


def fire_time_slider(x, y, width):
    return Widget(
        "slider",
        "fire-time",
        y,
        x,
        width,
        bar=lambda img: (fire_time(img), 0, 300, f"{fire_time(img)} / 300ms"),
        adjust=lambda img, d, fine: Edit(
            "fire-time",
            (lambda ms: lambda im: image.set_fire_time(im, ms))(
                clamp(fire_time(img) + d * (1 if fine else 10), 0, 300)
            ),
        ),
        hint="+/- by 10, [ and ] by 1, up to 300 ms",
    )


def polling_widgets(x, label_y, choices_y, spacing):
    """Return the Polling Rate label and its four choices."""
    out = [Widget("label", None, label_y, x, 17, text="Polling Rate (Hz)")]
    for hz in POLLING:
        w = len(str(hz)) + 4
        out.append(
            Widget(
                "choice",
                "polling",
                choices_y,
                x,
                w,
                text=str(hz),
                selected=lambda img, hz=hz: image.get_polling(img) == hz,
                choose=lambda img, hz=hz: Edit("polling", lambda im: image.set_polling(im, hz)),
            )
        )
        x += w + spacing
    return out


def dpi_widgets(model, gx, ys, item_w, gap, inline, sh, group_w):
    """Return the six DPI stages and the DPI slider.

    ys holds the rows of the label, the toggle, the value, the swatch and the slider. A stage has
    its toggle and value on one row when inline is set.
    """
    widgets = [Widget("label", None, ys["label"], gx, 11, text="DPI Control")]
    for n in range(6):
        x = gx + (item_w + gap) * n
        key = f"dpi.{n + 1}"
        widgets.append(
            Widget(
                "toggle",
                f"dpi-enable.{n + 1}",
                ys["toggle"],
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
                ys["pick"],
                x + 4 if inline else x,
                item_w - 4 if inline else item_w,
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
                ys["swatch"],
                x,
                item_w,
                h=sh,
                rgb=(
                    lambda img, n=n: image.get_dpi_colour(img, n),
                    lambda im, c, n=n: image.set_dpi_colour(im, n, *c),
                ),
                text=f"DPI stage {n + 1} colour",
                stage=n,
                hint="Enter edits. The app shows stage pairs swapped",
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
            ys["slider"],
            gx,
            group_w,
            bar=dpi_bar,
            adjust=dpi_adjust,
            hint="+/- changes the selected stage, s makes it the active stage",
        )
    )
    return widgets


def dpi_rows(inline):
    """Return the (height, gap) rows of the DPI block. The toggle and the value share a row when inline."""
    return [(1, 0), (1, 0)] + ([] if inline else [(1, 0)]) + [(0, 0), (1, 1), (1, 0)]


def performance_widgets(model, layout):
    panes = make_panes(layout)[0]["Performance"]
    if layout.split:
        return performance_split(model, panes[0])
    left, right = panes
    x0, y0, iw, ih = inner(left)
    bar_w = min(iw - 1, MAX_BAR)
    ys = stack(y0, ih, [(1, 0), (1, 1), (1, 0), (1, 1), (1, 0), (1, 0)])
    widgets = pointer_widgets(model, x0, ys[:4], bar_w)
    widgets.append(Widget("label", None, ys[4], x0, 18, text="Double Click Speed"))
    widgets.append(fire_time_slider(x0, ys[5], bar_w))
    x0, y0, iw, ih = inner(right)
    item_w, gap, offset = spread(iw, 6, INLINE_DPI_W)
    inline = item_w >= INLINE_DPI_W
    group_w = 6 * item_w + 5 * gap
    gx = x0 + offset
    sh = clamp(ih - (9 if inline else 10), 2, min(MAX_SWATCH_H, max(2, (item_w + 1) // 2)))
    rows = [(1, 0), (1, 1)] + [(sh, 0) if h == 0 else (h, g) for h, g in dpi_rows(inline)]
    ys = stack(y0, ih, rows)
    widgets += polling_widgets(gx, ys[0], ys[1], 2 if iw < 60 else 4)
    if inline:
        ys.insert(3, ys[3])
    row = dict(label=ys[2], toggle=ys[3], pick=ys[4], swatch=ys[5], slider=ys[7])
    return widgets + dpi_widgets(model, gx, row, item_w, gap, inline, sh, group_w)


def performance_split(model, pane):
    """Return the controls of the Performance tab in one column."""
    x0, y0, iw, ih = inner(pane)
    item_w, gap, offset = spread(iw, 6, INLINE_DPI_W)
    inline = item_w >= INLINE_DPI_W
    group_w = 6 * item_w + 5 * gap
    gx = x0 + offset
    fixed = 12 + (0 if inline else 1)
    sh = clamp(ih - fixed, 2, min(MAX_SWATCH_H, max(2, (item_w + 1) // 2)))
    rows = [(1, 0), (1, 0), (1, 1), (1, 0), (1, 1)] + [
        (sh, 0) if h == 0 else (h, g) for h, g in dpi_rows(inline)
    ]
    ys = stack(y0, ih, rows)
    bar_w = min(group_w - LABEL_W, MAX_BAR)
    widgets = pointer_widgets(model, gx, ys[:2], group_w, inline=True)
    widgets.append(Widget("label", None, ys[2], gx, 18, text="Double Click Speed"))
    widgets.append(fire_time_slider(gx + LABEL_W, ys[2], bar_w))
    widgets += polling_widgets(gx, ys[3], ys[4], 2 if iw < 60 else 4)
    if inline:
        ys.insert(7, ys[6])
    row = dict(label=ys[5], toggle=ys[6], pick=ys[7], swatch=ys[8], slider=ys[10])
    return widgets + dpi_widgets(model, gx, row, item_w, gap, inline, sh, group_w)


def led_widgets(gx, item_w, gap, group_w, sh, ys, notes, inline_effect=False):
    """Return the lighting controls. ys holds the row of each part. notes are the direction notes."""
    effect_x = gx + EFFECT_LABEL_W if inline_effect else gx
    widgets = [
        Widget("label", None, ys["effect_label"], gx, 6, text="Effect"),
        Widget(
            "pick",
            "effect",
            ys["effect"],
            effect_x,
            min(group_w - (effect_x - gx), 40),
            value=effect_label,
            options=lambda img: [
                (name, Edit("effect", lambda im, i=i: image.set_led_effect(im, i)))
                for i, name in enumerate(EFFECT_LABELS)
            ],
            hint="Enter lists the effects",
        ),
        Widget("label", None, ys["cycle_label"], gx, 13, text="Cycle colours"),
    ]
    for n in range(7):
        x = gx + (item_w + gap) * n
        widgets.append(
            Widget(
                "swatch",
                f"led-colour.{n}",
                ys["swatch"],
                x,
                item_w,
                h=sh,
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
                ys["toggle"],
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
    bar_x, bar_w = gx + 12, min(group_w - 12, MAX_BAR)
    widgets += [
        Widget("label", None, ys["bright"], gx, 10, text="Brightness"),
        Widget(
            "slider",
            "brightness",
            ys["bright"],
            bar_x,
            bar_w,
            bar=lambda img: (img[0x3F] >> 4, 0, 15, str(img[0x3F] >> 4)),
            adjust=lambda img, d, fine: Edit(
                "brightness",
                (lambda v: lambda im: image.set_brightness(im, v))(clamp((img[0x3F] >> 4) + d, 0, 15)),
            ),
            hint=UNVERIFIED,
        ),
        Widget("label", None, ys["speed"], gx, 5, text="Speed"),
        Widget(
            "slider",
            "cycle-time",
            ys["speed"],
            bar_x,
            bar_w,
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
            hint="range unverified, n/a for Button Response and LED Off",
        ),
        Widget(
            "toggle",
            "symmetry",
            ys["symmetry"],
            gx,
            14,
            text="Symmetry",
            toggle=lambda img: Edit(
                "symmetry",
                (lambda on: lambda im: image.set_led_symmetry(im, on))(not img[0x3A] >> 6 & 1),
            ),
            selected=lambda img: bool(img[0x3A] >> 6 & 1),
        ),
    ]
    for y, note in zip(ys["notes"], notes, strict=False):
        widgets.append(Widget("label", None, y, gx, len(note), text=note, dim=True))
    return widgets


def direction_notes(roomy):
    if roomy:
        return [
            "( ) Clockwise    ( ) Anti Clockwise",
            "( ) Two way      ( ) Overwrite",
            "direction is not decoded yet",
        ]
    return ["direction is not decoded yet"]


def backlight_widgets(layout):
    panes = make_panes(layout)[0]["Backlight"]
    if layout.split:
        return backlight_split(panes[0])
    x0, y0, iw, ih = inner(panes[1])
    item_w, gap, offset = spread(iw, 7)
    group_w = 7 * item_w + 6 * gap
    roomy = ih >= 20
    sh = clamp(ih - (13 if roomy else 11), 2, min(MAX_SWATCH_H, max(2, (item_w + 1) // 2)))
    rows = [(1, 0), (1, 1), (1, 0), (sh, 0), (1, 1), (1, 0), (1, 1), (1, 0)] + [(1, 0)] * (3 if roomy else 1)
    ys = stack(y0, ih, rows)
    row = dict(
        effect_label=ys[0],
        effect=ys[1],
        cycle_label=ys[2],
        swatch=ys[3],
        toggle=ys[4],
        bright=ys[5],
        speed=ys[6],
        symmetry=ys[7],
        notes=ys[8:],
    )
    return led_widgets(x0 + offset, item_w, gap, group_w, sh, row, direction_notes(roomy))


def backlight_split(pane):
    """Return the controls of the Backlight tab in one column. The effect label and its list share a row."""
    x0, y0, iw, ih = inner(pane)
    item_w, gap, offset = spread(iw, 7)
    group_w = 7 * item_w + 6 * gap
    roomy = ih >= 20
    sh = clamp(ih - (12 if roomy else 10), 2, min(MAX_SWATCH_H, max(2, (item_w + 1) // 2)))
    rows = [(1, 1), (1, 0), (sh, 0), (1, 1), (1, 0), (1, 1), (1, 0)] + [(1, 0)] * (3 if roomy else 1)
    ys = stack(y0, ih, rows)
    row = dict(
        effect_label=ys[0],
        effect=ys[0],
        cycle_label=ys[1],
        swatch=ys[2],
        toggle=ys[3],
        bright=ys[4],
        speed=ys[5],
        symmetry=ys[6],
        notes=ys[7:],
    )
    return led_widgets(x0 + offset, item_w, gap, group_w, sh, row, direction_notes(roomy), inline_effect=True)


def build_widgets(model, layout):
    """Return the widgets of every tab. Each list also holds the tab bar and the bottom bar."""
    common = tab_widgets(layout) + footer_widgets(layout)
    tabs = {
        "Button": common + button_widgets(layout),
        "Macro": common,
        "Performance": common + performance_widgets(model, layout),
        "Backlight": common + backlight_widgets(layout),
    }
    panes = make_panes(layout)[0]
    for name, widgets in tabs.items():
        for w in widgets:
            if w.area == "body":
                w.group = next(
                    (
                        i
                        for i, p in enumerate(panes[name])
                        if p.x <= w.x < p.x + p.w and p.y <= w.y < p.y + p.h
                    ),
                    None,
                )
    return tabs


def mouse_shape(width, height, unicode):
    """Return the rows of the mouse drawing and the (row, column) of each button number.

    A column of -2 puts a number just outside the left edge of the body.
    """
    if unicode:
        tl, tr, bl, br, h, v, jt, jb, jl, jr = "╭╮╰╯─│┬┴├┤"
    else:
        tl = tr = bl = br = jt = jb = jl = jr = "+"
        h, v = "-", "|"
    grid = [[" "] * width for _ in range(height)]
    cx = width // 2
    top = max(4, round(height * 0.4))
    wheel = max(3, min(top - 2, round(top * 0.6)))
    grid[0] = [tl, *[h] * (width - 2), tr]
    grid[-1] = [bl, *[h] * (width - 2), br]
    for y in range(1, height - 1):
        grid[y][0] = grid[y][-1] = v
    grid[top] = [jl, *[h] * (width - 2), jr]
    grid[0][cx], grid[top][cx] = jt, jb
    for y in range(1 + wheel, top):
        grid[y][cx] = v
    grid[1][cx - 1 : cx + 2] = [tl, h, tr]
    grid[wheel][cx - 1 : cx + 2] = [bl, h, br]
    for y in range(2, wheel):
        grid[y][cx - 1], grid[y][cx + 1] = v, v
    top_row = 1 + (top - 2) // 3
    side = top + 2
    marks = {
        1: (top_row, cx // 2),
        2: (top_row, (cx + width - 1) // 2),
        3: (1 + wheel // 2, cx),
        8: (top - 1, cx // 2),
        6: (side, width // 4),
        7: (side, width - 1 - width // 4),
        4: (side, -2),
        5: (side + 1, -2),
    }
    return ["".join(row) for row in grid], marks


def read_device(progress=None):
    dev = device.Device()
    try:
        return burst.read_image(dev, progress)
    finally:
        dev.close()


def wants_unicode():
    """Return True when the C library locale is UTF-8. Curses can then draw the box and block characters."""
    codeset = locale.nl_langinfo(locale.CODESET).lower().replace("-", "")
    return codeset == "utf8" and os.environ.get("TERM") != "linux"


class Screen:
    def __init__(self, scr, model, square=False):
        self.scr, self.model = scr, model
        h, w = scr.getmaxyx()
        self.unicode = wants_unicode()
        self.rounded = self.unicode and not square
        self.os_key, self.os_name = logos.detect()
        self.stats = sysinfo.gather()
        self.banner = banner.render(self.unicode)
        self.preview_top = self.preview_len = 0
        self.preview_page = 1
        self.preview_sig = None
        self.layout = make_layout(max(h, MIN_H), max(w, MIN_W))
        self.panes, self.action_pane = make_panes(self.layout)
        self.tabs = build_widgets(model, self.layout)
        self.tab = 0
        self.focus = self.first_body()
        self.colours = False
        self.pairs = {}
        self.cube = {}
        self.accent = self.current = self.mark = self.cyan = 0
        self.red = self.green = self.magenta = 0
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
                curses.init_pair(11, curses.COLOR_CYAN, -1)
                curses.init_pair(12, curses.COLOR_RED, -1)
                curses.init_pair(13, curses.COLOR_GREEN, -1)
                curses.init_pair(14, curses.COLOR_MAGENTA, -1)
                self.colours = True
        except curses.error:
            self.colours = False
        if self.colours:
            self.accent = curses.color_pair(8)
            self.current = curses.color_pair(9) | curses.A_BOLD
            self.mark = curses.color_pair(10) | curses.A_BOLD
            self.cyan = curses.color_pair(11)
            self.red = curses.color_pair(12)
            self.green = curses.color_pair(13)
            self.magenta = curses.color_pair(14)
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
        found = [w for w in self.widgets if w.focusable and w.area == "body"]
        return sorted(found, key=lambda w: (w.y, w.x))

    def fit(self, h, w):
        """Lay the screen out again when the terminal size changed. Keep the focus on the same control."""
        if (self.layout.h, self.layout.w) == (h, w):
            return
        old = self.focus
        self.layout = make_layout(h, w)
        self.panes, self.action_pane = make_panes(self.layout)
        self.tabs = build_widgets(self.model, self.layout)
        same = (old.kind, old.key, old.text)
        self.focus = (
            next((x for x in self.widgets if (x.kind, x.key, x.text) == same), None) or self.first_body()
        )

    def put(self, y, x, text, attr=0):
        h, w = self.scr.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.scr.addstr(y, x, text[: max(0, w - x - 1)], attr)
            except (curses.error, UnicodeEncodeError):
                pass

    def line(self, y, x, n):
        try:
            self.scr.hline(y, x, curses.ACS_HLINE, n, self.accent)
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
                        self.scr.addch(yy, xx, curses.ACS_VLINE, self.accent)
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
                    self.scr.addch(yy, xx, ch, self.accent)
                except curses.error:
                    pass
        if title:
            title = title[: w - 8]
            self.put(y, x + w - len(title) - 4 if right else x + 2, f" {title} ")

    def swatch(self, rgb):
        """Return the colour name and the attribute that paints it. The attribute is None if it cannot."""
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
        name, color = names.get(on, ("off" if not any(rgb) else "dark", None))
        if not self.colours:
            return name, None
        cube = self.cube_pair(rgb)
        if cube is not None:
            return name, cube
        if color is not None:
            return name, curses.color_pair(self.pairs[color])
        return name, None

    def cube_pair(self, rgb):
        """Return the attribute for a colour from the 256 colour cube. Return None without such a cube."""
        if curses.COLORS < 256 or not any(rgb):
            return None
        index = 16 + sum(round(v * 5 / 15) * 6**i for i, v in zip((2, 1, 0), rgb, strict=True))
        if index == 16:
            return None
        if index not in self.cube:
            pair = 15 + len(self.cube)
            if pair >= curses.COLOR_PAIRS:
                return None
            curses.init_pair(pair, -1, index)
            self.cube[index] = pair
        return curses.color_pair(self.cube[index])

    def paint(self, y, x, w, h, rgb):
        """Fill a w by h block with a colour. Name the colour in the block when it cannot be painted."""
        name, attr = self.swatch(rgb)
        if attr is not None:
            for row in range(h):
                self.put(y + row, x, " " * w, attr)
            return
        fill = "░" if self.unicode else ":"
        for row in range(h):
            self.put(y + row, x, fill * w, curses.A_DIM)
        self.put(y + h // 2, x + (w - len(name)) // 2, name[:w], curses.A_BOLD)

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
        if self.dirty(w) and w.kind != "swatch":
            self.put(w.y, w.x - 1, "*", self.mark)
        if w.kind == "label":
            self.put(w.y, w.x, w.text, attr)
        elif w.kind == "tab":
            active = self.tab == w.index
            style = self.current if active else attr
            self.put(w.y, w.x, f" {w.text} ", style | (curses.A_UNDERLINE if focused and not active else 0))
        elif w.kind == "pick":
            text = w.value(work)
            s = f"[{text:<{w.w - 3}}v]" if w.w >= 9 else text.ljust(w.w)
            self.put(w.y, w.x, s, attr)
        elif w.kind == "toggle":
            on = w.selected(work)
            self.put(w.y, w.x, f"[{'*' if on else ' '}]" + (f" {w.text}" if w.text else ""), attr)
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
            self.paint(w.y, w.x, w.w, w.h, w.rgb[0](work))
            if focused:
                for row in range(w.h):
                    self.put(w.y + row, w.x - 1, "[", self.current)
                    self.put(w.y + row, w.x + w.w, "]", self.current)
            if self.dirty(w):
                self.put(w.y, w.x - 1, "*", self.mark)

    def draw_mouse(self, pane, numbers, reserve):
        """Draw the mouse in a pane. Highlight the number of the focused button when numbers is set."""
        ix, iy, iw, ih = inner(pane)
        bw, bh = diagram_size(iw, ih, reserve)
        x0 = ix + 2 + (iw - bw - 2) // 2
        y0 = iy + 1 + max(0, ih - reserve - bh) // 2
        rows, marks = mouse_shape(bw, bh, self.unicode)
        for dy, row in enumerate(rows):
            self.put(y0 + dy, x0, row, self.accent)
        if numbers:
            for n, (dy, dx) in marks.items():
                on = self.focus.key == f"button.{n}"
                self.put(y0 + dy, x0 + dx, str(n), self.current if on else 0)

    def draw_logo(self, pane, lines):
        """Draw a logo in the middle of a pane."""
        rows = logos.tones(lines)
        height, width = logos.size(lines)
        ix, iy, iw, ih = inner(pane)
        y, x = iy + (ih - height) // 2, ix + (iw - width) // 2
        for dy, row in enumerate(rows):
            for tone, text in row:
                self.put(y + dy, x, text, self.accent if tone == 1 else self.cyan or curses.A_BOLD)
                x += len(text)
            x = ix + (iw - width) // 2

    def draw_system(self, pane):
        """Draw the OS logo and the facts about this machine in the System section."""
        ix, iy, iw, ih = inner(pane)
        lines = logos.pick(self.os_key, ih, self.unicode)
        x = ix + 1
        if lines is not None:
            height, width = logos.size(lines)
            self.draw_logo(Pane(pane.y, pane.x, pane.h, width + 6, ""), lines)
            x += width + 4
        top = iy + max(0, (ih - len(self.stats)) // 2)
        for i, (label, value) in enumerate(self.stats):
            room = ix + iw - (x + 9)
            if room < 4:
                break
            self.put(top + i, x, label, curses.A_DIM)
            self.put(top + i, x + 9, preview.fit(value, room))

    def draw_banner(self):
        """Draw the AURORA banner and the profile name beside it."""
        model = self.model
        if self.colours:
            hues = [self.accent, self.accent, self.magenta, self.magenta, self.red, self.red]
            face = [hue | (curses.A_BOLD if i % 2 else 0) for i, hue in enumerate(hues)]
            shade = [hue | curses.A_DIM for hue in hues]
        else:
            face, shade = [curses.A_BOLD] * banner.ZONES, [curses.A_DIM] * banner.ZONES
        for run in self.banner.runs:
            attr = (face if run.layer == "face" else shade)[run.zone]
            self.put(run.y, 2 + run.x, run.text, attr)
        x = 2 + self.banner.width + 2
        flags = ("[offline]" if model.offline else "") + (" [read only]" if model.structure else "")
        self.put(2, x, PROFILE_NAMES[profile_of(model.work)], self.accent)
        self.put(3, x, flags.strip(), curses.A_DIM)

    def draw_header(self):
        model, w = self.model, self.layout.w
        if self.layout.split:
            self.draw_banner()
            text = summary(model.work)
            self.put(self.layout.body_y - 1, w - 3 - len(text), text, curses.A_DIM)
            return
        flags = ("[offline]" if model.offline else "") + (" [read only]" if model.structure else "")
        self.put(0, 2, "Aurora", self.accent)
        profile = PROFILE_NAMES[profile_of(model.work)]
        self.put(0, w - 3 - len(profile), profile, self.accent)
        self.put(1, 2, summary(model.work), curses.A_DIM)
        self.put(1, w - 3 - len(flags.strip()), flags.strip(), curses.A_DIM)

    def draw_preview(self, pane, tab):
        """Draw the config preview. A changed value shows in place as a red old line then a green new one."""
        ix, iy, iw, ih = inner(pane)
        width = iw - 2
        rows = preview.diff(preview.render(self.model.base, width), preview.render(self.model.work, width))
        sig = (tab, tuple(self.model.pending))
        if sig != self.preview_sig:
            self.preview_sig = sig
            change = preview.first_change(rows)
            target = change if change is not None else preview.anchor(rows, PREVIEW_SECTION[tab])
            self.preview_top = max(0, target - 1)
        top = clamp(self.preview_top, 0, max(0, len(rows) - ih))
        self.preview_top, self.preview_len, self.preview_page = top, len(rows), max(1, ih - 1)
        marks = {"-": self.red or curses.A_BOLD, "+": self.green or curses.A_BOLD}
        for i, row in enumerate(rows[top : top + ih]):
            if row.tag != " ":
                attr = marks[row.tag]
            elif row.text.startswith("["):
                attr = self.accent | curses.A_BOLD
            else:
                attr = curses.A_DIM
            self.put(iy + i, ix, f"{row.tag} {row.text}", attr)
        span = f" {top + 1}-{min(len(rows), top + ih)}/{len(rows)} "
        self.put(pane.y, pane.x + pane.w - len(span) - 3, span, curses.A_DIM)

    def scroll_preview(self, pages):
        """Scroll the config preview by a number of pages. A negative number scrolls up."""
        last = max(0, self.preview_len - self.preview_page - 1)
        self.preview_top = clamp(self.preview_top + round(pages * self.preview_page), 0, last)

    def draw_status(self):
        model, layout = self.model, self.layout
        if model.structure:
            banner = "read looks wrong, writes disabled: " + "; ".join(model.structure)
        elif model.drift:
            banner = "differs from the last verified state, press ! to accept it"
        else:
            banner = ""
        text = (model.msg or banner)[: layout.w - 22]
        self.put(layout.status_y, 2, text, curses.A_BOLD if model.msg else 0)
        count = len(model.pending)
        pending = f"{count} pending change{'s' if count != 1 else ''}"
        self.put(layout.status_y, layout.w - 3 - len(pending), pending, self.mark if count else curses.A_DIM)

    def draw(self):
        self.scr.erase()
        h, w = self.scr.getmaxyx()
        if h < MIN_H or w < MIN_W:
            self.put(0, 0, f"need {MIN_W}x{MIN_H}")
            self.scr.refresh()
            return
        self.fit(h, w)
        layout = self.layout
        name = TABS[self.tab]
        self.draw_header()
        for pane in self.panes[name]:
            self.box(*pane)
        hint = self.focus.hint
        if self.focus.kind == "swatch":
            r, g, b = self.focus.rgb[0](self.model.work)
            hint = f"R {r} G {g} B {b}  " + hint
        self.box(*self.action_pane[:4], title=hint[: w - 12], right=True)
        panes = self.panes[name]
        mouse = pane_titled(panes, "Blaze")
        if name == "Button":
            if mouse is not None:
                self.draw_mouse(mouse, True, 3)
                if self.focus.key and self.focus.key.startswith("button."):
                    text = f"Button {self.focus.index}: {self.focus.value(self.model.work)}"
                    self.put(mouse.y + mouse.h - 2, mouse.x + (mouse.w - len(text)) // 2, text, self.accent)
            if pane_titled(panes, "System") is not None:
                self.draw_system(pane_titled(panes, "System"))
        elif name == "Macro":
            pane = panes[0]
            note = "Macros are not supported yet"
            self.put(pane.y + pane.h - 3, pane.x + (pane.w - len(note)) // 2, note, curses.A_DIM)
        elif name == "Backlight":
            if mouse is not None:
                self.draw_mouse(mouse, False, 2)
        else:
            active = self.model.work[0x18] - 0x18
            stage = next(x for x in self.widgets if x.kind == "swatch" and x.stage == active)
            self.put(stage.y + stage.h, stage.x + stage.w // 2, "▲" if self.unicode else "^", self.accent)
        for widget in self.widgets:
            self.draw_widget(widget)
        if name == "Button" and profile_of(self.model.work):
            pane = pane_titled(panes, "Buttons") if layout.split else mouse
            self.put(pane.y + pane.h - 1, pane.x + 2, NOT_OFFICE, self.mark)
        if layout.split:
            self.draw_preview(pane_titled(panes, PREVIEW_TITLE), name)
        self.draw_status()
        self.put(layout.footer_y, 2, FOOTER, curses.A_DIM)
        self.scr.refresh()

    def draw_progress(self, label, frac):
        """Draw a progress bar on the status row. The writer calls this while it works."""
        full = "█" if self.unicode else "#"
        y, w = self.layout.status_y, self.layout.w
        room = w - 10 - len(label)
        k = int(room * clamp(frac, 0, 1))
        self.put(y, 0, " " * (w - 1))
        self.put(y, 2, label, self.accent)
        self.put(y, 4 + len(label), full * k, self.accent)
        self.put(y, w - 6, f"{int(frac * 100):3d}%", curses.A_DIM)
        self.scr.refresh()

    def say(self, text):
        self.model.msg = text
        self.draw()

    def ask(self, question):
        self.say(question + " (y/n)")
        while True:
            key = self.scr.getch()
            if key == curses.KEY_RESIZE:
                self.draw()
            elif key in (ord("y"), ord("Y")):
                return True
            elif key in (ord("n"), ord("N"), 27):
                return False

    def popup(self, title, labels, current):
        """Show a list over the screen. Return the chosen index. Return None if it is cancelled."""
        sel = current if current is not None else 0
        top = 0
        while True:
            h, w = self.scr.getmaxyx()
            height = min(len(labels), max(12, h - 12))
            width = min(max(len(s) for s in [*labels, title]) + 7, w - 2)
            width = max(width, min(36, w - 2))
            y0, x0 = (h - height - 2) // 2, (w - width) // 2
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
            if key == curses.KEY_RESIZE:
                self.draw()
            elif key in (curses.KEY_DOWN, ord("j")):
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
        channel_pairs = [curses.COLOR_RED, curses.COLOR_GREEN, curses.COLOR_BLUE]
        while True:
            h, sw = self.scr.getmaxyx()
            width = min(clamp(sw // 2, COLOUR_MODAL_MIN_W, COLOUR_MODAL_MAX_W), sw - 2)
            room = width - 4
            step = 2 if h >= 32 else 1
            preview = clamp(h - 4 - (2 * step + 5), 3, min(10, max(3, room // 4)))
            height = preview + 2 * step + 5
            y0, x0 = (h - height) // 2, (sw - width) // 2
            cell = max(1, (room - 7) // 15)
            for yy in range(y0, y0 + height):
                self.put(yy, x0, " " * width)
            self.box(y0, x0, height, width, w.text or "Colour")
            self.paint(y0 + 1, x0 + 2, room, preview, tuple(rgb))
            name = self.swatch(tuple(rgb))[0]
            self.put(y0 + preview + 1, x0 + 2, f"{name}  R {rgb[0]}  G {rgb[1]}  B {rgb[2]}", curses.A_DIM)
            for i, letter in enumerate("RGB"):
                row = y0 + preview + 2 + i * step
                self.put(row, x0 + 2, f"{letter} ", self.current if i == channel else 0)
                filled, empty = rgb[i] * cell, (15 - rgb[i]) * cell
                if self.colours:
                    self.put(row, x0 + 5, " " * filled, curses.color_pair(self.pairs[channel_pairs[i]]))
                else:
                    self.put(row, x0 + 5, ("█" if self.unicode else "#") * filled, self.accent)
                self.put(row, x0 + 5 + filled, ("·" if self.unicode else ".") * empty, curses.A_DIM)
                self.put(row, x0 + 6 + 15 * cell, f"{rgb[i]:>2}")
            self.put(y0 + height - 2, x0 + 2, COLOUR_HINT, curses.A_DIM)
            self.scr.refresh()
            key = self.scr.getch()
            if key == curses.KEY_RESIZE:
                self.draw()
            elif key in (curses.KEY_DOWN, ord("j")):
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
        """Read a command on the status row. Return the text. Return None if it is cancelled."""
        text = ""
        while True:
            y, w = self.layout.status_y, self.layout.w
            self.put(y, 0, " " * (w - 1))
            self.put(y, 2, ":" + text + "_", self.accent)
            self.scr.refresh()
            key = self.scr.getch()
            if key == curses.KEY_RESIZE:
                self.draw()
            elif key in (10, 13, curses.KEY_ENTER):
                return text
            elif key == 27:
                return None
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if not text:
                    return None
                text = text[:-1]
            elif 32 <= key < 127 and len(text) < w - 10:
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
        if w.kind == "slider" and w.live is not None:
            self.model.msg = w.live(d, fine)
        elif w.kind == "slider" and w.adjust is not None:
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
                result = burst.apply(list(model.pending.values()), False, progress=self.draw_progress)
            except Exception as exc:
                result = burst.Result(False)
                print(exc)
        self.scr.clear()
        tail = buf.getvalue().strip().splitlines()
        verified = getattr(result, "image", None)
        if result and verified is not None:
            model.reset(verified)
            model.drift = []
            model.msg = "applied and verified by read-back"
        elif result and self.reload():
            model.drift = []
            model.msg = "applied and verified by read-back"
        elif result:
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
            elif key in (curses.KEY_NPAGE, curses.KEY_PPAGE, 4, 21):
                pages = {curses.KEY_NPAGE: 1, curses.KEY_PPAGE: -1, 4: 0.5, 21: -0.5}[key]
                self.scroll_preview(pages)
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
    model = Model(base, offline, structure, drift, None if offline else pointer.Pointer.detect())
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    curses.wrapper(lambda scr: Screen(scr, model, square).run())
    return 0


if __name__ == "__main__":
    sys.exit(main())

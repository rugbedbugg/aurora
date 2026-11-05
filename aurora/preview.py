"""A read-only TOML-style view of the settings, with pending changes shown as an in-place diff.

The view is for display only. Its keys and values use the same names as `aurora get`.
"""

import difflib
from collections import namedtuple

from aurora import cli, image

# The narrowest text that fits the preview pane at the smallest split layout.
MIN_WIDTH = 33
SECTIONS = ("header", "performance", "backlight", "buttons")

Line = namedtuple("Line", "text section")
Row = namedtuple("Row", "tag text section")


def fit(text, width):
    """Cut text to width cells and mark the cut with an ellipsis."""
    return text if len(text) <= width else text[: width - 1] + "…"


def toml(value):
    """Return a value as TOML text."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml(v) for v in value) + "]"
    return str(value)


def render(img, width=MIN_WIDTH):
    """Return the lines of the file for an image. Lines longer than width are cut."""
    out = []

    def add(section, text=""):
        out.append(Line(fit(text, width), section))

    def key(section, name, value):
        add(section, f"{name} = {toml(value)}")

    add("header", "# aurora.toml")
    key("header", "profile", img[0x01] >> 5 & 3)
    add("performance")
    add("performance", "[performance]")
    key("performance", "polling", image.get_polling(img))
    key("performance", "fire-time", img[0x1A] | img[0x1B] << 8)
    key("performance", "dpi-active", img[0x18] - 0x18 + 1)
    for n in range(6):
        index = image.get_dpi_index(img, n)
        label = image.DPI_LABEL.get(index)
        add("performance")
        add("performance", f"[dpi.{n + 1}]")
        key("performance", "value", label if label else f"index {index}")
        key("performance", "enabled", bool(img[0x19] >> n & 1))
        key("performance", "rgb", list(image.get_dpi_colour(img, n)))
    effect = image.get_led_effect(img)
    known = effect is not None and effect < len(cli.EFFECTS)
    add("backlight")
    add("backlight", "[backlight]")
    key("backlight", "effect", cli.EFFECTS[effect] if known else f"unknown {img[0x1C]:02x}")
    key("backlight", "cycle-time", image.get_led_cycle_time(img))
    key("backlight", "brightness", img[0x3F] >> 4)
    key("backlight", "symmetry", bool(img[0x3A] >> 6 & 1))
    key("backlight", "cycle", [int(image.get_cycle_colour_enabled(img, n)) for n in range(7)])
    for slot in range(7):
        key("backlight", f"colour.{slot}", list(image.get_led_colour(img, slot)))
    add("buttons")
    add("buttons", "[buttons]")
    for button in range(1, 9):
        function, _ = image.get_button(img, button)
        key("buttons", str(button), cli.FUNCTION_NAME.get(function, "unknown"))
    return out


def diff(old, new):
    """Return the rows of the whole file with each change in place.

    A changed value shows as a '-' row with the old line followed by a '+' row with the new one.
    Unchanged lines have the tag ' '.
    """
    rows = []
    matcher = difflib.SequenceMatcher(a=[x.text for x in old], b=[x.text for x in new], autojunk=False)
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            rows += [Row(" ", x.text, x.section) for x in new[b0:b1]]
            continue
        rows += [Row("-", x.text, x.section) for x in old[a0:a1]]
        rows += [Row("+", x.text, x.section) for x in new[b0:b1]]
    return rows


def first_change(rows):
    """Return the index of the first changed row. Return None when nothing changed."""
    return next((i for i, row in enumerate(rows) if row.tag != " "), None)


def anchor(rows, section):
    """Return the index of the first row of a section. Return 0 when the section has no rows."""
    return next((i for i, row in enumerate(rows) if row.section == section), 0)

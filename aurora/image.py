"""Encode and decode the mouse's 0x2D0 byte config image.

Every setter patches an image dict in place. Setters raise ValueError for a value
outside the allowed range and Unmapped for a value that is not decoded yet.
"""

import json
from importlib import resources

# Map button 1..8 to its byte position.
BUTTON_POS = {1: 0x08, 2: 0x0A, 3: 0x09, 4: 0x0C, 5: 0x0B, 6: 0x0F, 7: 0x0D, 8: 0x10}
# Map each profile to the base of its button table. Only profile 0 is verified in full.
PROFILE_BASE = {0: 0x08, 1: 0x44, 2: 0x50, 3: 0x60}
# Map the app dropdown index to the wire function code.
FUNCTION_CODE = {
    0: 0x20,
    1: 0x21,
    2: 0x22,
    3: 0x23,
    4: 0x24,
    5: 0x25,
    6: 0x26,
    12: 0x27,
    13: 0x28,
    14: 0x29,
    15: 0x35,
    16: 0x2B,
    17: 0x2C,
    18: 0x34,
    19: 0x37,
    20: 0x38,
    21: 0x39,
}
POLLING_CODE = {125: 0x07, 250: 0x03, 500: 0x01, 1000: 0x00}
DPI_MAX_INDEX = 22
# Map the DPI indices whose values were read from the vendor app to their DPI value.
DPI_LABEL = {2: 600, 5: 1200, 8: 1800, 10: 2400, 13: 4800, 16: 7200, 22: 12800}
# Write fixed bytes for types 12 and 13. Only a cycle time of 1 is known.
LED_LITERAL = {12: 0x99, 13: 0x87}
INV_POLLING = {v: k for k, v in POLLING_CODE.items()}
INV_FUNCTION = {v: k for k, v in FUNCTION_CODE.items()}


class Unmapped(Exception):
    pass


def load_sample():
    """Return the bundled sample image, a real read from a mouse."""
    text = resources.files("aurora").joinpath("data/sample-image.json").read_text()
    return {int(k): v for k, v in json.loads(text).items()}


def _nibble(img, addr, high, value):
    if not 0 <= value <= 15:
        raise ValueError(f"nibble out of range: {value}")
    old = img[addr]
    img[addr] = (value << 4 | old & 0x0F) if high else (old & 0xF0 | value)


def _bit(img, addr, bit, on):
    img[addr] = img[addr] | 1 << bit if on else img[addr] & ~(1 << bit) & 0xFF


def set_polling(img, hz):
    if hz not in POLLING_CODE:
        raise ValueError(f"polling must be one of {sorted(POLLING_CODE)}")
    img[0x1E] = POLLING_CODE[hz]


def dpi_code(index):
    if not 0 <= index <= DPI_MAX_INDEX:
        raise Unmapped(f"DPI index {index} is outside 0..{DPI_MAX_INDEX}")
    if index <= 9:
        return index + 1, 0
    if index <= 13:
        return index + 2, 0
    return index - 14, 1


def set_dpi_stage(img, stage, index):
    if not 0 <= stage <= 5:
        raise ValueError("stage must be 0..5")
    nibble, flag = dpi_code(index)
    _nibble(img, 0x15 + stage // 2, stage % 2 == 0, nibble)
    _bit(img, 0x13, stage, flag)


def set_active_dpi_stage(img, stage):
    if not 0 <= stage <= 5:
        raise ValueError("stage must be 0..5")
    img[0x18] = 0x18 + stage


def set_dpi_enabled(img, stage, on):
    if not 0 <= stage <= 5:
        raise ValueError("stage must be 0..5")
    _bit(img, 0x19, stage, on)


def set_fire_time(img, ms):
    if not 0 <= ms <= 300:
        raise ValueError("fire time must be 0..300 ms")
    img[0x1A] = ms & 0xFF
    img[0x1B] = ms >> 8


def set_led_cycle_time(img, value):
    _nibble(img, 0x1C, False, value)


def set_led_effect(img, effect):
    if effect in LED_LITERAL:
        if img[0x1C] & 0x0F != 1:
            raise Unmapped("effects 12 and 13 are only known for a cycle time of 1")
        img[0x1C] = LED_LITERAL[effect]
        _bit(img, 0x33, 7, False)
    elif 0 <= effect <= 11:
        _nibble(img, 0x1C, True, 8 | effect & 7)
        _bit(img, 0x33, 7, effect >= 8)
    else:
        raise Unmapped(f"LED effect {effect} is not mapped")


def set_cycle_colours(img, mask):
    if not 0 <= mask <= 0x7F:
        raise ValueError("mask must be 7 bits")
    img[0x1D] = 0x80 | mask


def set_brightness(img, level):
    _nibble(img, 0x3F, True, level)


def set_dpi_colour(img, stage, r, g, b):
    if not 0 <= stage <= 5:
        raise ValueError("stage must be 0..5")
    for i, v in enumerate((r, g, b)):
        _nibble(img, 0x20 + 3 * stage + i, False, v)


def set_led_colour(img, slot, r, g, b):
    if 0 <= slot <= 5:
        for i, v in enumerate((r, g, b)):
            _nibble(img, 0x20 + 3 * slot + i, True, v)
    elif slot == 6:
        _nibble(img, 0x3E, True, r)
        _nibble(img, 0x3E, False, g)
        _nibble(img, 0x3F, False, b)
    else:
        raise ValueError("slot must be 0..6")


def set_led_symmetry(img, on):
    _bit(img, 0x3A, 6, on)


def set_led_direction(img, value):
    if not 0 <= value <= 1:
        raise Unmapped("only direction values 0 and 1 are verified")
    _bit(img, 0x3A, 4, value)


def set_button(img, button, function, profile=0):
    if button not in BUTTON_POS:
        raise ValueError("button must be 1..8")
    if function not in FUNCTION_CODE:
        raise Unmapped(f"function {function} is not mapped")
    if profile not in PROFILE_BASE:
        raise ValueError("profile must be 0..3")
    if profile and button != 8:
        raise Unmapped("profile button tables are verified for button 8 only")
    addr = PROFILE_BASE[profile] + BUTTON_POS[button] - 0x08
    img[addr] = img[addr] & 0xC0 | FUNCTION_CODE[function]


def set_button_reaction(img, button, kind):
    if not 0 <= kind <= 3:
        raise ValueError("reaction type must be 0..3")
    addr = BUTTON_POS[button]
    img[addr] = img[addr] & 0x3F | kind << 6


def set_profile(img, profile):
    if not 0 <= profile <= 3:
        raise ValueError("profile must be 0..3")
    img[0x01] = 0x03 | profile << 5
    img[0x76] = img[0x76] & 0xFC | profile


def set_mode_light(img, on):
    _bit(img, 0x76, 7, on)


def get_polling(img):
    return INV_POLLING.get(img[0x1E])


def get_dpi_index(img, stage):
    byte = img[0x15 + stage // 2]
    nibble = byte >> 4 if stage % 2 == 0 else byte & 0x0F
    if img[0x13] >> stage & 1:
        return nibble + 14 if nibble <= 8 else None
    if 1 <= nibble <= 10:
        return nibble - 1
    if 12 <= nibble <= 15:
        return nibble - 2
    return None


def get_led_effect(img):
    byte = img[0x1C]
    for effect, literal in LED_LITERAL.items():
        if byte == literal:
            return effect
    if not byte & 0x80:
        return None
    effect = byte >> 4 & 7
    return effect + 8 if img[0x33] >> 7 & 1 else effect


def get_led_cycle_time(img):
    return None if get_led_effect(img) in LED_LITERAL else img[0x1C] & 0x0F


def get_dpi_colour(img, stage):
    return tuple(img[0x20 + 3 * stage + i] & 0x0F for i in range(3))


def get_led_colour(img, slot):
    if slot <= 5:
        return tuple(img[0x20 + 3 * slot + i] >> 4 for i in range(3))
    return (img[0x3E] >> 4, img[0x3E] & 0x0F, img[0x3F] & 0x0F)


def get_button(img, button, profile=0):
    byte = img[PROFILE_BASE[profile] + BUTTON_POS[button] - 0x08]
    return INV_FUNCTION.get(byte & 0x3F), byte >> 6


def check_invariants(img):
    """Raise ValueError if the image breaks a rule the vendor app enforces."""
    if not any(get_button(img, b)[0] == 1 for b in BUTTON_POS):
        raise ValueError("at least one button must be Left Click")
    if not img[0x19] & 0x3F:
        raise ValueError("at least one DPI stage must be enabled")
    if not img[0x19] >> (img[0x18] - 0x18) & 1:
        raise ValueError("the active DPI stage must be enabled")

"""Map the vendor app's config.ini keys onto the image to check the encoder against recorded probes."""

from blazectl import image

# Keys that move no device bytes. The vendor app applies them through the OS.
HOST_SIDE = {"DPI_SPEED", "WHEEL_SPEED"}
CHANNEL = {"R": 0, "G": 1, "B": 2}


def apply_ini_key(img, section, key, value):
    """Apply one config.ini key to the image. Raise Unmapped for unknown keys."""
    v = int(value)
    if key in HOST_SIDE:
        return
    if section == "Init" and key == "CurConfig":
        return image.set_profile(img, v)
    if section == "ShareData":
        if key == "USB_SPEED":
            return image.set_polling(img, {0: 125, 1: 250, 2: 500, 3: 1000}[v])
        if key.startswith("DPI_SET_EN"):
            return image.set_dpi_enabled(img, int(key[10:]), bool(v))
        if key.startswith("DPI_SET"):
            return image.set_dpi_stage(img, int(key[7:]), v)
        if key == "DPI_LEVEL":
            return image.set_active_dpi_stage(img, v)
        if key == "FIRE_TIME":
            return image.set_fire_time(img, v)
        if key == "LED_TYPE":
            return image.set_led_effect(img, v)
        if key == "LED_CYCTIME":
            return image.set_led_cycle_time(img, v)
        if key == "CYC_7COL_EN":
            return image.set_cycle_colours(img, v)
        if key == "LED_BRIGHT":
            return image.set_brightness(img, v)
        if key == "LED_FEATURE_SYMMETRY":
            return image.set_led_symmetry(img, bool(v))
        if key == "LED_FEATURE_DIREC":
            return image.set_led_direction(img, v)
        if key == "MODE_LIGHT":
            return image.set_mode_light(img, bool(v & 1))
        if key[:3] == "DPI" and key[3].isdigit() and key[4] == "_":
            stage, c = int(key[3]), CHANNEL[key[5]]
            return image._nibble(img, 0x20 + 3 * stage + c, False, v)
        if key.startswith("LED_USER") and key[8].isdigit() and key[9] == "_":
            slot, c = int(key[8]), CHANNEL[key[10]]
            if slot <= 5:
                return image._nibble(img, 0x20 + 3 * slot + c, True, v)
            if c == 0:
                return image._nibble(img, 0x3E, True, v)
            if c == 1:
                return image._nibble(img, 0x3E, False, v)
            return image._nibble(img, 0x3F, False, v)
    if section.startswith("Config") and section[6:].isdigit():
        profile = int(section[6:])
        if key[0] == "K" and key[1:].isdigit() and int(key[1:]) <= 7 and profile <= 3:
            return image.set_button(img, int(key[1:]) + 1, v, profile)
        if key.startswith("LED_REACT_TYPE") and key[14:].isdigit() and int(key[14:]) <= 7 and profile == 0:
            return image.set_button_reaction(img, int(key[14:]) + 1, v)
    raise image.Unmapped(f"{section}.{key}")


def get_ini_view(img):
    """Return the decoded image as {"Section.Key": value} using config.ini names."""
    view = {"ShareData.USB_SPEED": {125: 0, 250: 1, 500: 2, 1000: 3}.get(image.get_polling(img))}
    for n in range(6):
        view[f"ShareData.DPI_SET{n}"] = image.get_dpi_index(img, n)
        view[f"ShareData.DPI_SET_EN{n}"] = img[0x19] >> n & 1
        for c, name in enumerate("RGB"):
            view[f"ShareData.DPI{n}_{name}"] = image.get_dpi_colour(img, n)[c]
            view[f"ShareData.LED_USER{n}_{name}"] = image.get_led_colour(img, n)[c]
    for c, name in enumerate("RGB"):
        view[f"ShareData.LED_USER6_{name}"] = image.get_led_colour(img, 6)[c]
    view["ShareData.DPI_LEVEL"] = img[0x18] - 0x18
    view["ShareData.FIRE_TIME"] = img[0x1A] | img[0x1B] << 8
    view["ShareData.LED_TYPE"] = image.get_led_effect(img)
    view["ShareData.LED_CYCTIME"] = image.get_led_cycle_time(img)
    view["ShareData.CYC_7COL_EN"] = img[0x1D] & 0x7F
    view["ShareData.LED_BRIGHT"] = img[0x3F] >> 4
    view["ShareData.LED_FEATURE_SYMMETRY"] = img[0x3A] >> 6 & 1
    view["ShareData.LED_FEATURE_DIREC"] = img[0x3A] >> 4 & 1
    view["ShareData.MODE_LIGHT"] = img[0x76] >> 7 & 1
    view["Init.CurConfig"] = img[0x01] >> 5 & 3
    for button in range(1, 9):
        function, reaction = image.get_button(img, button)
        view[f"Config0.K{button - 1}"] = function
        view[f"Config0.LED_REACT_TYPE{button - 1}"] = reaction
    return view

"""The blazectl command: read and change the mouse's settings."""

import argparse
import sys

from blazectl import burst, device, image

EFFECTS = [
    "dpi-breathing",
    "cycle-breathing",
    "light-on",
    "flowing-water",
    "mono-water",
    "comet-streak",
    "neon",
    "ambilight",
    "flicker",
    "star-trek",
    "ripple",
    "enraptured",
    "button-response",
    "led-off",
]
FUNCTIONS = {
    "none": 0,
    "left": 1,
    "middle": 2,
    "right": 3,
    "backward": 4,
    "forward": 5,
    "dpi-loop": 6,
    "show-desktop": 12,
    "double-click": 13,
    "rapid-fire": 14,
    "led-loop": 15,
    "dpi-up": 16,
    "dpi-down": 17,
    "fn": 18,
    "profile-office": 19,
    "profile-game-1": 20,
    "profile-game-2": 21,
}
FUNCTION_NAME = {v: k for k, v in FUNCTIONS.items()}
DPI_BY_VALUE = {v: k for k, v in image.DPI_LABEL.items()}

EPILOG = f"""settings for 'set' (KEY=VALUE):
  polling=125|250|500|1000        dpi.N=600|1200|1800|2400|4800|7200|12800 or idx:0..22 (N is 1..6)
  dpi-active=N                    dpi-enable.N=on|off        dpi-colour.N=R,G,B (0..15)
  fire-time=0..300                effect=NAME or 0..13       brightness=0..15
  cycle-time=0..15                led-colour.N=R,G,B (N is 0..6)
  button.N=FUNCTION (N is 1..8)   profile=0..3
effects: {", ".join(EFFECTS)}
button functions: {", ".join(FUNCTIONS)}
Only the DPI values read from the vendor app are accepted by value. Use idx: for the others.
dpi-colour.N follows the config byte order. The vendor app screen shows stage pairs (1,2), (3,4)
and (5,6) swapped, so check the real colours on the mouse.
A set sends one burst. If the burst fails midway the tool replays the previous settings.
After a change made in another tool, run 'blazectl rebaseline' to accept the mouse as it is."""


def parse_bool(text):
    if text not in ("on", "off"):
        raise ValueError("expected on or off")
    return text == "on"


def parse_rgb(text):
    parts = [int(x) for x in text.split(",")]
    if len(parts) != 3:
        raise ValueError("expected R,G,B")
    return parts


def stage(name, text, lo, hi):
    n = int(text)
    if not lo <= n <= hi:
        raise ValueError(f"{name} must be {lo}..{hi}")
    return n


def parse_setting(arg):
    """Return a patch function for one KEY=VALUE argument. Raise ValueError or Unmapped."""
    if "=" not in arg:
        raise ValueError(f"expected KEY=VALUE, got {arg!r}")
    key, value = arg.split("=", 1)
    name, _, index = key.partition(".")
    if name == "polling":
        return lambda img: image.set_polling(img, int(value))
    if name == "dpi":
        n = stage("stage", index, 1, 6) - 1
        if value.startswith("idx:"):
            i = int(value[4:])
        elif int(value) in DPI_BY_VALUE:
            i = DPI_BY_VALUE[int(value)]
        else:
            raise ValueError(f"unknown DPI value {value}, known: {sorted(DPI_BY_VALUE)}, or use idx:N")
        return lambda img: image.set_dpi_stage(img, n, i)
    if name == "dpi-active":
        n = stage("stage", value, 1, 6) - 1
        return lambda img: image.set_active_dpi_stage(img, n)
    if name == "dpi-enable":
        n = stage("stage", index, 1, 6) - 1
        on = parse_bool(value)
        return lambda img: image.set_dpi_enabled(img, n, on)
    if name == "dpi-colour":
        n = stage("stage", index, 1, 6) - 1
        rgb = parse_rgb(value)
        return lambda img: image.set_dpi_colour(img, n, *rgb)
    if name == "fire-time":
        return lambda img: image.set_fire_time(img, int(value))
    if name == "effect":
        effect = EFFECTS.index(value) if value in EFFECTS else int(value)
        return lambda img: image.set_led_effect(img, effect)
    if name == "brightness":
        return lambda img: image.set_brightness(img, int(value))
    if name == "cycle-time":
        return lambda img: image.set_led_cycle_time(img, int(value))
    if name == "led-colour":
        slot = stage("slot", index, 0, 6)
        rgb = parse_rgb(value)
        return lambda img: image.set_led_colour(img, slot, *rgb)
    if name == "button":
        n = stage("button", index, 1, 8)
        if value not in FUNCTIONS:
            raise ValueError(f"unknown button function {value!r}, known: {', '.join(FUNCTIONS)}")
        function = FUNCTIONS[value]
        return lambda img: image.set_button(img, n, function)
    if name == "profile":
        return lambda img: image.set_profile(img, int(value))
    raise ValueError(f"unknown setting {key!r}")


def describe(img):
    """Return (key, text) lines for every decoded setting."""
    lines = []
    hz = image.get_polling(img)
    lines.append(("polling", f"{hz} Hz" if hz else f"unknown code {img[0x1E]:02x}"))
    for n in range(6):
        i = image.get_dpi_index(img, n)
        label = image.DPI_LABEL.get(i)
        text = f"{label}" if label else f"index {i} (value not known yet)"
        on = "on" if img[0x19] >> n & 1 else "off"
        r, g, b = image.get_dpi_colour(img, n)
        lines.append((f"dpi.{n + 1}", f"{text}, {on}, colour {r},{g},{b}"))
    lines.append(("dpi-active", str(img[0x18] - 0x18 + 1)))
    lines.append(("fire-time", f"{img[0x1A] | img[0x1B] << 8} ms"))
    effect = image.get_led_effect(img)
    known = effect is not None and effect < len(EFFECTS)
    lines.append(("effect", EFFECTS[effect] if known else f"unknown {img[0x1C]:02x}"))
    lines.append(("cycle-time", str(image.get_led_cycle_time(img))))
    lines.append(("brightness", str(img[0x3F] >> 4)))
    for slot in range(7):
        lines.append((f"led-colour.{slot}", ",".join(str(x) for x in image.get_led_colour(img, slot))))
    for button in range(1, 9):
        function, reaction = image.get_button(img, button)
        lines.append((f"button.{button}", f"{FUNCTION_NAME.get(function, 'unknown')} (reaction {reaction})"))
    lines.append(("profile", str(img[0x01] >> 5 & 3)))
    return lines


def read_device_image():
    dev = device.Device()
    try:
        return burst.read_image(dev)
    finally:
        dev.close()


def cmd_get(args):
    img = read_device_image()
    problems = burst.validate_read(img, None)
    if problems:
        print("warning, the read looks wrong:", "; ".join(problems), file=sys.stderr)
    for key, text in describe(img):
        if not args.keys or key.split(".")[0] in args.keys or key in args.keys:
            print(f"{key} = {text}")
    return 1 if problems else 0


def cmd_set(args):
    try:
        patches = [parse_setting(a) for a in args.settings]
    except (ValueError, image.Unmapped, KeyError) as exc:
        print("error:", exc, file=sys.stderr)
        return 2
    if args.dry_run:
        before = read_device_image()
        after = dict(before)
        try:
            for patch in patches:
                patch(after)
            image.check_invariants(after)
        except (ValueError, image.Unmapped) as exc:
            print("error:", exc, file=sys.stderr)
            return 2
        for (k, a), (_, b) in zip(describe(before), describe(after), strict=True):
            if a != b:
                print(f"{k}: {a} -> {b}")
        print("changed addresses:", [hex(x) for x in sorted(before) if before[x] != after[x]] or "none")
        return 0
    try:
        ok = burst.apply(patches, args.force)
    except (ValueError, image.Unmapped) as exc:
        print("error:", exc, file=sys.stderr)
        return 2
    return 0 if ok else 1


def cmd_rewrite(args):
    return 0 if burst.apply([], args.force, rewrite=True) else 1


def cmd_rebaseline(args):
    return 0 if burst.rebaseline() else 1


def build_parser():
    parser = argparse.ArgumentParser(
        prog="blazectl",
        description="Read and change EvoFox Blaze settings.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("get", help="show settings read from the device")
    p.add_argument("keys", nargs="*")
    p.set_defaults(fn=cmd_get)
    p = sub.add_parser("set", help="change settings in one burst and verify by read-back")
    p.add_argument("settings", nargs="+", metavar="KEY=VALUE")
    p.add_argument("--force", action="store_true", help="write even if the pre-read looks wrong")
    p.add_argument("--dry-run", action="store_true", help="show the planned change and write nothing")
    p.set_defaults(fn=cmd_set)
    p = sub.add_parser("rewrite", help="send the full config again to clear a live lighting state")
    p.add_argument("--force", action="store_true", help="write even if the pre-read looks wrong")
    p.set_defaults(fn=cmd_rewrite)
    p = sub.add_parser("rebaseline", help="accept the current device state as the new last known good")
    p.set_defaults(fn=cmd_rebaseline)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except device.DeviceError as exc:
        print("error:", exc, file=sys.stderr)
        return 3

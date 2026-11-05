"""Pointer speed and scroll speed of the mouse, set through the running Hyprland compositor.

These two settings belong to the compositor and not to the mouse. Hyprland keeps them per input
device. They apply at once and reset when Hyprland reloads its configuration.
"""

import glob
import json
import os
import shutil
import subprocess

VENDOR, PRODUCT = "30fa", "1440"
# Each range is (lowest, highest, step).
SENSITIVITY = (-1.0, 1.0, 0.1)
SCROLL = (0.25, 4.0, 0.25)


class PointerError(Exception):
    pass


def internal_name(name):
    """Return the name Hyprland gives an input device. It lowercases the name and turns spaces into dashes."""
    return name.lower().replace(" ", "-")


def input_names(sysfs="/sys/class/input"):
    """Return the Hyprland names of the input nodes that belong to this mouse."""
    names = []
    for node in sorted(glob.glob(os.path.join(sysfs, "input*"))):
        try:
            with open(os.path.join(node, "id", "vendor")) as f:
                vendor = f.read().strip()
            with open(os.path.join(node, "id", "product")) as f:
                product = f.read().strip()
            with open(os.path.join(node, "name")) as f:
                name = f.read().rstrip("\n")
        except OSError:
            continue
        if (vendor, product) == (VENDOR, PRODUCT):
            names.append(internal_name(name))
    return names


def run_hyprctl(args):
    """Run hyprctl and return its output. Raise PointerError when it fails."""
    try:
        done = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PointerError(f"hyprctl failed: {exc}") from exc
    if done.returncode != 0:
        raise PointerError(f"hyprctl failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


class Pointer:
    """The pointer settings of the mouse. Each value is applied when it is set."""

    def __init__(self, devices, sensitivity, scroll, run=run_hyprctl):
        self.devices, self.run = devices, run
        self.sensitivity, self.scroll = sensitivity, scroll

    @classmethod
    def detect(cls, run=run_hyprctl, sysfs="/sys/class/input"):
        """Return a Pointer for this mouse. Return None without a Hyprland session or the mouse in it."""
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or shutil.which("hyprctl") is None:
            return None
        try:
            mice = {m["name"] for m in json.loads(run(["devices", "-j"])).get("mice", [])}
            devices = [n for n in input_names(sysfs) if n in mice]
            sensitivity = json.loads(run(["getoption", "input:sensitivity", "-j"]))["float"]
            scroll = json.loads(run(["getoption", "input:scroll_factor", "-j"]))["float"]
        except (PointerError, ValueError, KeyError):
            return None
        return cls(devices, sensitivity, scroll, run) if devices else None

    def push(self):
        """Send both values to Hyprland for every input node of the mouse."""
        for name in self.devices:
            if not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
                raise PointerError(f"cannot address the input device {name!r}")
            fields = (
                f"name = '{name}', sensitivity = {self.sensitivity:.2f}, scroll_factor = {self.scroll:.2f}"
            )
            self.run(["eval", f"hl.device({{ {fields} }})"])

    def step(self, which, direction):
        """Move one value by a step and apply it. Return the text for the status row."""
        lo, hi, step = SENSITIVITY if which == "sensitivity" else SCROLL
        value = round(min(hi, max(lo, getattr(self, which) + direction * step)), 2)
        if value == getattr(self, which):
            return ""
        old = getattr(self, which)
        setattr(self, which, value)
        try:
            self.push()
        except PointerError as exc:
            setattr(self, which, old)
            return str(exc)
        label = "sensitivity" if which == "sensitivity" else "scroll speed"
        return f"{label} {value:g}, resets when Hyprland reloads"

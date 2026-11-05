"""Write the config image to the mouse as one burst and verify it by reading it back.

The vendor app sends the whole image on every Apply. A template of that burst keeps the
fixed reports and leaves a hole for each data byte. Each write fills the holes from an
image that was read from the mouse and then patched.
"""

import json
import os
import signal
import time
from importlib import resources

from aurora import device, image

MIN_GAP = 0.003
PROGRESS_EVERY = 32
IMAGE_SIZE = 0x2D0
MAGIC_PAGE0 = bytes([0x5A, 0x03, 0xA5, 0x40, 0x14, 0xFA, 0x30, 0x10])


def load_template():
    return json.loads(resources.files("aurora").joinpath("data/apply-template.json").read_text())


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "aurora")


def last_good_path():
    return os.path.join(state_dir(), "last-good.json")


def load_last_good():
    """Return the last image that was verified on the mouse. Return None on a first run."""
    try:
        with open(last_good_path()) as f:
            return {int(k): v for k, v in json.load(f).items()}
    except FileNotFoundError:
        return None


def save_last_good(img):
    os.makedirs(state_dir(), exist_ok=True)
    path = last_good_path()
    with open(path + ".tmp", "w") as f:
        json.dump({str(a): v for a, v in img.items()}, f)
    os.replace(path + ".tmp", path)


def build(template, img):
    """Return the ordered (gap, report) pairs of a burst. A report of None marks the leading GET."""
    out = []
    for entry in template:
        if entry["op"] == "get":
            out.append((entry["dt"], None))
        elif entry["op"] == "fixed":
            out.append((entry["dt"], bytes.fromhex(entry["raw"])))
        else:
            head = bytes.fromhex(entry["head"])
            out.append((entry["dt"], head + bytes([img[entry["addr"]], entry["last"]])))
    return out


def replay(dev, template, img, progress=None):
    """Send one burst. Block SIGINT and SIGTERM until it ends so it cannot stop halfway.

    Call progress(done, total) every few reports when it is given.
    """
    reports = build(template, img)
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM})
    try:
        for i, (gap, report) in enumerate(reports):
            if progress is not None and i % PROGRESS_EVERY == 0:
                progress(i, len(reports))
            time.sleep(max(gap, MIN_GAP))
            if report is None:
                dev.get_report()
            else:
                dev.set_report(report)
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, blocked)
    if progress is not None:
        progress(len(reports), len(reports))
    dev.stale = True


def read_image(dev, progress=None):
    data = dev.read_range(0x000, IMAGE_SIZE, progress)
    return {a: data[a] for a in range(len(data))}


def validate_read(img, last_good):
    """Return the reasons a read cannot be trusted. An empty list means it looks sane."""
    problems = []
    page0 = bytes(img[a] for a in range(8))
    # Mask bits 5 and 6 of byte 1. They hold the profile. Its other bits are fixed.
    if not (
        page0[0] == MAGIC_PAGE0[0] and page0[1] & 0x9F == MAGIC_PAGE0[1] and page0[2:] == MAGIC_PAGE0[2:]
    ):
        problems.append("page 0 does not hold the expected header")
    pages = [bytes(img[a] for a in range(base, base + 8)) for base in range(0x08, 0x80, 8)]
    if MAGIC_PAGE0 in pages or len(set(pages)) < len(pages) // 2:
        problems.append("the config region repeats the page 0 header or is mostly identical pages")
    if last_good is not None:
        moved = [hex(a) for a in range(IMAGE_SIZE) if img[a] != last_good[a]]
        if moved:
            problems.append(f"device differs from the last known good dump at {moved[:8]}")
    return problems


def recover(template, before):
    """Replay the verified pre-read after a failed burst. Return True if the mouse matches it again."""
    try:
        dev = device.Device()
        try:
            replay(dev, template, before)
            ok = read_image(dev) == before
        finally:
            dev.close()
    except (OSError, device.DeviceError) as exc:
        print(f"recovery failed: {exc}. Replug the mouse and run 'aurora rewrite --force'.")
        return False
    print("restored the previous settings" if ok else "the mouse does not match the previous settings")
    return ok


def rebaseline():
    """Save the current device state as the last known good after a structure check only."""
    dev = device.Device()
    try:
        img = read_image(dev)
    finally:
        dev.close()
    problems = validate_read(img, None)
    if problems:
        print("refusing to rebaseline:", "; ".join(problems))
        return False
    save_last_good(img)
    print("saved the current device state as the last known good dump")
    return True


class Result:
    """The outcome of apply. It is true when the settings were written and verified.

    image holds the verified read-back of the device. It is None when nothing was verified.
    """

    def __init__(self, ok, image=None):
        self.ok, self.image = ok, image

    def __bool__(self):
        return self.ok


def phase(progress, label, lo, hi):
    """Return a progress(done, total) callback that reports label and a fraction between lo and hi."""
    if progress is None:
        return None
    return lambda done, total: progress(label, lo + (hi - lo) * done / total)


def apply(patches=None, force=False, rewrite=False, progress=None):
    """Read the device, apply every patch to that one image, send one burst and verify by read-back.
    Return a Result.

    Set rewrite to send the burst even when nothing changed. That clears a live lighting state.
    Call progress(label, fraction) while it reads, writes and verifies when progress is given.
    """
    template = load_template()
    dev = device.Device()
    try:
        before = read_image(dev, phase(progress, "Reading", 0.0, 0.41))
        problems = validate_read(before, load_last_good())
        if problems and not force:
            print("refusing to write:", "; ".join(problems))
            return Result(False)
        img = dict(before)
        for patch in patches or []:
            patch(img)
        image.check_invariants(img)
        if img == before and not rewrite:
            print("device already matches the requested state, no burst sent")
            return Result(True, before)
        try:
            replay(dev, template, img, phase(progress, "Writing", 0.41, 0.59))
        except (OSError, device.DeviceError) as exc:
            print(f"burst failed: {exc}")
            dev.close()
            recover(template, before)
            return Result(False)
        after = read_image(dev, phase(progress, "Verifying, settings are live", 0.59, 1.0))
        status = dev.status()
    finally:
        try:
            dev.close()
        except OSError:
            pass
    written = {e["addr"] for e in template if e["op"] == "data"}
    wrong = [a for a in sorted(written) if after[a] != img[a]]
    stray = [a for a in range(IMAGE_SIZE) if a not in written and after[a] != before[a]]
    print("status after:", device.hexs(status))
    print(
        "written addresses wrong:",
        [hex(a) for a in wrong] or "none",
        "| unwritten bytes changed:",
        [hex(a) for a in stray] or "none",
    )
    if wrong or stray:
        return Result(False)
    if rewrite:
        effect = image.get_led_effect(img)
        # Compare only the high nibble. The config verified already. Only the live effect is in doubt.
        if effect is not None and status[7] >> 4 != effect & 0x0F:
            print(f"live effect is not the stored one, status byte 7 is {status[7]:02x}, run rewrite again")
            return Result(False)
    save_last_good(after)
    return Result(True, after)

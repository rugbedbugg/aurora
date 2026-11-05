import json
from pathlib import Path

from blazectl import burst, image

DATA = Path(__file__).parent / "data"


def full_image():
    """Return the bundled sample padded to the full 0x2D0 bytes with the page 0 header."""
    img = {a: 0 for a in range(burst.IMAGE_SIZE)}
    img.update(image.load_sample())
    img.update(dict(enumerate(burst.MAGIC_PAGE0)))
    img[0x01] = 0x03
    return img


def load_json(name):
    return json.loads((DATA / name).read_text())


class FakeDevice:
    """An in-memory mouse that stages data writes and commits them like the real one."""

    def __init__(self, mem, fail_after=None):
        self.mem = mem
        self.staged = {}
        self.fail_after = fail_after
        self.sent = 0
        self.stale = False
        self.primer = b""
        self.flags = (0x62, 0x10)
        self.closed = False

    def set_report(self, data):
        self.sent += 1
        if self.fail_after is not None and self.sent > self.fail_after:
            raise OSError("device unplugged")
        data = bytes(data)
        if data[1] == 0x18 and data[2] == 0x03:
            self.staged[(data[5] << 8 | data[4]) + data[3]] = data[6]
        elif data[1] == 0x18 and data[2] == 0x09:
            self.mem.update(self.staged)
            self.staged = {}

    def get_report(self):
        return self.status()

    def status(self):
        effect = image.get_led_effect(self.mem) or 0
        return bytes([7, 0, 0x62, 0x09, 0x10, 0x00, 0x23, (effect & 0x0F) << 4 | 0x0B])

    def read_range(self, lo, hi):
        return bytes(self.mem[a] for a in range(lo, hi))

    def close(self):
        self.closed = True


def install_fake(monkeypatch, mem, fail_first=None):
    """Make blazectl open FakeDevice objects that share one memory. Return the list of opened devices."""
    opened = []

    def factory():
        dev = FakeDevice(mem, fail_first if not opened else None)
        opened.append(dev)
        return dev

    monkeypatch.setattr(burst.device, "Device", factory)
    return opened

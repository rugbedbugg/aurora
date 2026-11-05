"""The mouse's config interface, reached through its hidraw node.

The mouse takes 8 byte feature reports with report ID 7 on USB interface 1.
Reads are a command followed by a GET. Writes are a burst of reports.
"""

import fcntl
import glob
import os
import time

REPORT_ID = 7
REPORT_LEN = 8
IOC_WRITE, IOC_READ = 1, 2
HID_ID = "HID_ID=0003:000030FA:00001440"


def _ioc(direction, kind, nr, size):
    return direction << 30 | size << 16 | ord(kind) << 8 | nr


HIDIOCSFEATURE = _ioc(IOC_WRITE | IOC_READ, "H", 6, REPORT_LEN)
HIDIOCGFEATURE = _ioc(IOC_WRITE | IOC_READ, "H", 7, REPORT_LEN)


class DeviceError(Exception):
    pass


def find_node():
    """Return the hidraw node of the config interface (interface 1, usage page 0xFF01)."""
    for sys_dir in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        dev = os.path.realpath(os.path.join(sys_dir, "device"))
        try:
            with open(os.path.join(dev, "uevent")) as f:
                if HID_ID not in f.read():
                    continue
            with open(os.path.join(os.path.dirname(dev), "bInterfaceNumber")) as f:
                interface = f.read().strip()
            with open(os.path.join(dev, "report_descriptor"), "rb") as f:
                descriptor = f.read()
        except OSError:
            continue
        if interface == "01" and b"\x06\x01\xff" in descriptor and b"\x85\x07" in descriptor:
            return "/dev/" + os.path.basename(sys_dir)
    raise DeviceError("mouse config interface not found")


def vendor_app_running():
    """Return True while a Wine server runs. The vendor app would interleave its own writes."""
    for path in glob.glob("/proc/[0-9]*/comm"):
        try:
            with open(path) as f:
                if f.read().strip() == "wineserver":
                    return True
        except OSError:
            continue
    return False


def hexs(data):
    return " ".join(f"{b:02x}" for b in data)


class Device:
    def __init__(self):
        if vendor_app_running():
            raise DeviceError("wineserver is running, close the vendor app first")
        self.node = find_node()
        if not os.access(self.node, os.R_OK | os.W_OK):
            raise DeviceError(
                f"no access to {self.node}, install the udev rule or run: "
                f"sudo setfacl -m u:$USER:rw {self.node}"
            )
        self.fd = os.open(self.node, os.O_RDWR)
        # The first read of a session and the first read after a write burst are stale.
        # Discard one page before any real read.
        self.stale = True
        self.primer = b""
        self.flags = (0, 0)

    def close(self):
        os.close(self.fd)

    def set_report(self, data):
        buf = bytearray(data)
        if len(buf) != REPORT_LEN or buf[0] != REPORT_ID:
            raise ValueError("report must be 8 bytes starting with 07")
        n = fcntl.ioctl(self.fd, HIDIOCSFEATURE, buf)
        if n != REPORT_LEN:
            raise DeviceError(f"short write: {n}")

    def get_report(self):
        buf = bytearray(REPORT_LEN)
        buf[0] = REPORT_ID
        n = fcntl.ioctl(self.fd, HIDIOCGFEATURE, buf)
        # Check bytes 3 and 5, which held in every state seen. Bytes 2 and 4 are state flags
        # that change after a power cycle. Log them and do not depend on them.
        if n != REPORT_LEN or buf[0] != REPORT_ID or buf[3] != 0x09 or buf[5] != 0x00:
            raise DeviceError(f"unexpected reply: {bytes(buf).hex()}")
        self.flags = (buf[2], buf[4])
        return bytes(buf)

    def status(self):
        """Return the live status reply without sending a command first."""
        reply = self.get_report()
        self.stale = True
        return reply

    def read(self, addr):
        """Read one config byte. The data sits in reply byte 1."""
        base, off = addr & ~7, addr & 7
        self.set_report([REPORT_ID, 0x18, 0x05, off, base & 0xFF, base >> 8, 0x00, 0x07])
        time.sleep(0.004)
        return self.get_report()[1]

    def end_op(self):
        self.set_report([REPORT_ID, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

    def read_range(self, lo, hi, progress=None):
        """Read a range one page at a time and close each page like the vendor app.

        Call progress(done, total) after each page when it is given.
        """
        if self.stale:
            self.primer = self.read_range_raw(0, 8)
            self.stale = False
        return self.read_range_raw(lo, hi, progress)

    def read_range_raw(self, lo, hi, progress=None):
        out = bytearray()
        for base in range(lo & ~7, hi, 8):
            for addr in range(max(base, lo), min(base + 8, hi)):
                out.append(self.read(addr))
            self.end_op()
            if progress is not None:
                progress(len(out), hi - lo)
        return bytes(out)

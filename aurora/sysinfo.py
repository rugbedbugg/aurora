"""Facts about this machine for the System section of the Button tab."""

import os

from aurora import device


def read(root, path):
    """Return the text of a file below root. Return an empty string when it cannot be read."""
    try:
        with open(os.path.join(root, path.lstrip("/"))) as f:
            return f.read()
    except OSError:
        return ""


def pairs(text, sep="="):
    """Return the key and value pairs of a file. The first of a repeated key wins."""
    out = {}
    for line in text.splitlines():
        key, found, value = line.partition(sep)
        if found:
            out.setdefault(key.strip(), value.strip().strip("\"'"))
    return out


def uptime(seconds):
    """Return a short text for a time in seconds, such as 3h 12m."""
    minutes = int(seconds) // 60
    days, rest = divmod(minutes, 1440)
    hours, minutes = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def memory(meminfo):
    """Return used and total memory as text. Return an empty string when meminfo lacks the numbers."""
    info = pairs(meminfo, ":")
    try:
        total = int(info["MemTotal"].split()[0])
        free = int(info["MemAvailable"].split()[0])
    except (KeyError, ValueError, IndexError):
        return ""
    return f"{(total - free) / 1048576:.1f} / {total / 1048576:.1f} GiB"


def mouse_node():
    """Return the hidraw node of the mouse. Return an empty string when it is not found."""
    try:
        return device.find_node()
    except device.DeviceError:
        return ""


def gather(root="/", env=None, mouse=mouse_node):
    """Return the (label, value) rows to show. Rows without a value are left out."""
    env = os.environ if env is None else env
    release = pairs(read(root, "etc/os-release"))
    vendor = read(root, "sys/devices/virtual/dmi/id/sys_vendor").strip()
    product = read(root, "sys/devices/virtual/dmi/id/product_name").strip()
    cpu = pairs(read(root, "proc/cpuinfo"), ":").get("model name", "")
    seconds = read(root, "proc/uptime").split()
    session = " ".join(x for x in (env.get("XDG_CURRENT_DESKTOP"), env.get("XDG_SESSION_TYPE")) if x)
    node = mouse()
    rows = [
        ("OS", release.get("PRETTY_NAME") or release.get("NAME", "")),
        ("Kernel", read(root, "proc/sys/kernel/osrelease").strip()),
        ("Host", " ".join(x for x in (vendor, product) if x)),
        ("CPU", " ".join(cpu.split())),
        ("Memory", memory(read(root, "proc/meminfo"))),
        ("Uptime", uptime(float(seconds[0])) if seconds else ""),
        ("Session", session),
        ("Mouse", f"Blaze on {node}" if node else ""),
    ]
    return [(label, value) for label, value in rows if value]

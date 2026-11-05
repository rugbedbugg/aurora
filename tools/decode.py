import collections
import subprocess
import sys


def load(pcap, addr="8"):
    cmd = [
        "tshark",
        "-r",
        pcap,
        "-Y",
        f"usb.device_address=={addr} && usb.transfer_type==2",
        "-T",
        "fields",
        "-e",
        "frame.time_relative",
        "-e",
        "usb.urb_type",
        "-e",
        "usb.setup.bRequest",
        "-e",
        "usb.capdata",
        "-e",
        "usb.data_fragment",
        "-e",
        "usb.control.Response",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    rows = []
    for line in out.splitlines():
        f = line.split("\t") + [""] * 6
        t, typ, req, cap, frag, resp = f[:6]
        data = (cap or frag or resp).replace(":", "")
        rows.append((float(t), typ.strip("'"), req, data))
    return rows


def main(pcap, addr="8"):
    rows = load(pcap, addr)
    ops = []
    pending = None
    for t, typ, req, data in rows:
        if typ == "S" and req == "9":
            ops.append((t, "SET", data))
        elif typ == "S" and req == "1":
            pending = t
        elif typ == "C" and pending is not None:
            ops.append((pending, "GET", data))
            pending = None
    # bursts: split on gaps > 0.5 s
    bursts, cur = [], []
    for op in ops:
        if cur and op[0] - cur[-1][0] > 0.5:
            bursts.append(cur)
            cur = []
        cur.append(op)
    if cur:
        bursts.append(cur)
    print(f"{len(ops)} ops, {len(bursts)} bursts")
    for i, b in enumerate(bursts):
        c = collections.Counter(o[1] for o in b)
        print(f"burst {i}: t={b[0][0]:.2f}..{b[-1][0]:.2f} SET={c['SET']} GET={c['GET']}")
    return bursts


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "8")

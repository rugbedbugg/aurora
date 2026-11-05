import contextlib
import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import decode  # noqa: E402
import diffimg  # noqa: E402

SCRATCH = os.environ["BLAZE_SCRATCH"]
APP = f"{SCRATCH}/evofox-extracted/app"
INI = f"{APP}/skins/config/config.ini"
ENV = dict(os.environ, WINEPREFIX=f"{SCRATCH}/wineprefix", WINEDEBUG="-all")
WORK = os.environ.get("BLAZE_WORK", os.path.expanduser("~/evofox-blaze"))
STATE = os.path.join(WORK, "app-state")
SAVED_INI = os.path.join(STATE, "config.ini.current")
REF_IMAGE = os.path.join(STATE, "reference-image.json")
LOG = os.path.join(WORK, "captures", "automap-results.jsonl")
FINAL_COMMIT = "0718100000000000"


def find_mouse():
    base = "/sys/bus/usb/devices"
    for d in os.listdir(base):
        p = f"{base}/{d}"
        try:
            if (
                open(f"{p}/idVendor").read().strip() == "30fa"
                and open(f"{p}/idProduct").read().strip() == "1440"
            ):
                return int(open(f"{p}/busnum").read()), int(open(f"{p}/devnum").read())
        except OSError:
            continue
    raise SystemExit("mouse not found")


def set_key(ini, section, key, value):
    sec = re.search(
        rb"^\[" + re.escape(section.encode()) + rb"\][^\r\n]*\r\n(.*?)(?=^\[|\Z)", ini, re.M | re.S
    )
    if not sec:
        raise KeyError(section)
    body = sec.group(1)
    pat = rb"^" + re.escape(key.encode()) + rb"=[^\r\n]*"
    new, n = re.subn(pat, lambda m: key.encode() + b"=" + str(value).encode(), body, count=1, flags=re.M)
    if n != 1:
        raise KeyError(f"{section}.{key}")
    return ini[: sec.start(1)] + new + ini[sec.end(1) :]


def parse_ini(ini):
    secs, cur = {}, None
    for raw in ini.split(b"\r\n"):
        line = raw.decode("latin-1").strip()
        m = re.match(r"\[([^\]/]+)\]", line)
        if m:
            cur = m.group(1)
            secs[cur] = {}
        elif "=" in line and cur and not line.startswith("//"):
            k, v = line.split("=", 1)
            secs[cur][k.strip()] = v.strip()
    return secs


def attempt(ini_bytes, wait):
    bus, addr = find_mouse()
    subprocess.run(["wineserver", "-k"], env=ENV, stderr=subprocess.DEVNULL, check=False)
    time.sleep(1)
    with open(INI, "wb") as f:
        f.write(ini_bytes)
    pcap = tempfile.mktemp(suffix=".pcapng", dir=SCRATCH)
    cap = subprocess.Popen(
        ["dumpcap", "-i", f"usbmon{bus}", "-q", "-w", pcap], stderr=subprocess.DEVNULL, check=False
    )
    time.sleep(1)
    app = subprocess.Popen(
        ["wine", "Gaming Mouse 3.0.exe"],
        cwd=APP,
        env=ENV,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(wait)
    cap.send_signal(signal.SIGINT)
    cap.wait()
    subprocess.run(["wineserver", "-k"], env=ENV, stderr=subprocess.DEVNULL, check=False)
    app.wait()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            bursts = decode.main(pcap, str(addr))
    finally:
        os.remove(pcap)
    full = [b for b in bursts if sum(1 for o in b if o[1] == "SET") > 800]
    done = [b for b in full if any(o[2] == FINAL_COMMIT for o in b)]
    info = {"bursts": len(bursts), "full": len(full), "done": len(done)}
    if len(full) != 1 or len(done) != 1:
        return None, info
    b = done[0]
    info["start"] = round(b[0][0], 1)
    info["end"] = round(b[-1][0], 1)
    info["get"] = [o[2] for o in b if o[1] == "GET"]
    return diffimg.image(b), info


def run_once(ini_bytes):
    for wait in (9, 20):
        img, info = attempt(ini_bytes, wait)
        if img is not None:
            return img, info
        print(f"  run failed at wait={wait}: {info}", flush=True)
    return None, info


def diff(a, b):
    return [(x, a.get(x), b.get(x)) for x in sorted(set(a) | set(b)) if a.get(x) != b.get(x)]


def fmt(d):
    def f(v):
        return "--" if v is None else f"{v:02x}"

    return ", ".join(f"0x{x:03x}:{f(p)}>{f(q)}" for x, p, q in d)


def record(label, d, info):
    with open(LOG, "a") as f:
        f.write(json.dumps({"label": label, "diff": [[x, p, q] for x, p, q in d], "info": info}) + "\n")
    print(f"{label}: {len(d)} byte(s) {fmt(d)}", flush=True)


def probe_value(v):
    n = int(v)
    return n - 1 if n > 0 else n + 1


def probe_keys(orig, sections):
    parsed = parse_ini(orig)
    for sec in sections:
        for key, val in parsed.get(sec, {}).items():
            if re.match(r"(LEFT_MAC|MAC_COR)", key) or not re.fullmatch(r"-?\d+", val):
                continue
            yield sec, key, probe_value(val)


def restore(init=False):
    saved = open(SAVED_INI, "rb").read()
    subprocess.run(["wineserver", "-k"], env=ENV, stderr=subprocess.DEVNULL, check=False)
    img, info = run_once(saved)
    open(INI, "wb").write(saved)
    subprocess.run(["wineserver", "-k"], env=ENV, stderr=subprocess.DEVNULL, check=False)
    if img is None:
        print("restore FAILED", info, flush=True)
        return False
    if init:
        json.dump({str(k): v for k, v in img.items()}, open(REF_IMAGE, "w"))
        print("restore ok, reference image saved", info, flush=True)
        return True
    ref = {int(k): v for k, v in json.load(open(REF_IMAGE)).items()}
    d = diff(ref, img)
    print("restore:", "mouse matches reference image" if not d else f"MISMATCH {fmt(d)}", info, flush=True)
    return not d


def on_term(signum, frame):
    sys.exit(1)


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode in ("restore", "restore-init"):
        raise SystemExit(0 if restore(init=mode == "restore-init") else 1)
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGHUP, on_term)
    signal.signal(signal.SIGINT, signal.default_int_handler)
    orig = open(INI, "rb").read()
    base = None
    try:
        base, info = run_once(orig)
        if base is None:
            raise SystemExit("baseline run failed")
        print("baseline ok:", info, flush=True)
        if mode == "calib":
            again, info2 = run_once(orig)
            record("base-vs-base", diff(base, again), info2)
        elif mode == "sweep":
            done = set()
            if os.path.exists(LOG):
                done = {json.loads(line)["label"] for line in open(LOG)}
            for n, (sec, key, val) in enumerate(probe_keys(orig, sys.argv[2].split(","))):
                if f"{sec}.{key}={val}" in done:
                    continue
                img, info = run_once(set_key(orig, sec, key, val))
                if img is None:
                    print(f"{sec}.{key}={val}: no image", flush=True)
                    continue
                record(f"{sec}.{key}={val}", diff(base, img), info)
                if n % 20 == 19:
                    chk, info = run_once(orig)
                    if chk is None:
                        print("base-recheck FAILED", info, flush=True)
                    else:
                        record("base-recheck", diff(base, chk), info)
        elif mode == "values":
            done = set()
            if os.path.exists(LOG):
                done = {json.loads(line)["label"] for line in open(LOG)}
            for spec in sys.argv[2:]:
                target, rng = spec.split("=")
                sec, key = target.split(".")
                lo, hi = (int(x) for x in rng.split("-"))
                for val in range(lo, hi + 1):
                    if f"{sec}.{key}={val}" in done:
                        continue
                    img, info = run_once(set_key(orig, sec, key, val))
                    if img is None:
                        print(f"{sec}.{key}={val}: no image", flush=True)
                        continue
                    record(f"{sec}.{key}={val}", diff(base, img), info)
    finally:
        open(INI, "wb").write(orig)
        subprocess.run(["wineserver", "-k"], env=ENV, stderr=subprocess.DEVNULL, check=False)
        if base is not None:
            restore()

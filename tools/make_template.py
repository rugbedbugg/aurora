"""Rebuild the burst template and the golden burst from the captured bursts. Needs tshark.

Set AURORA_WORK to the directory that holds captures/01-baseline.pcapng and captures/02-changes.pcapng.
Run it with the tools directory on the path, for example: python3 tools/make_template.py
"""

import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import decode  # noqa: E402
import diffimg  # noqa: E402

from aurora import burst  # noqa: E402

WORK = os.environ.get("AURORA_WORK", os.path.expanduser("~/evofox-blaze"))


def capture_burst(pcap, index, addr="8"):
    with contextlib.redirect_stdout(io.StringIO()):
        return decode.main(pcap, addr)[index]


def make_template(ops):
    """Turn one captured burst into an ordered template. Data bytes become holes."""
    template, prev = [], ops[0][0]
    for t, kind, data in ops:
        entry = {"dt": round(t - prev, 6)}
        prev = t
        if kind == "GET":
            entry["op"] = "get"
        else:
            raw = bytes.fromhex(data)
            if raw[1] == 0x18 and raw[2] == 0x03:
                entry.update(op="data", addr=(raw[5] << 8 | raw[4]) + raw[3], head=raw[:6].hex(), last=raw[7])
            else:
                entry.update(op="fixed", raw=raw.hex())
        template.append(entry)
    return template


def equivalent(template, built, expected):
    """Compare two bursts. Accept a data difference only if a later write to the same address agrees."""
    if len(built) != len(expected):
        return False
    for i, (a, b) in enumerate(zip(built, expected, strict=True)):
        if a == b:
            continue
        if template[i]["op"] != "data":
            return False
        later = [j for j in range(i + 1, len(template)) if template[j].get("addr") == template[i]["addr"]]
        if not later or built[later[-1]] != expected[later[-1]]:
            return False
    return True


def main():
    final = capture_burst(os.path.join(WORK, "captures", "02-changes.pcapng"), 2)
    startup = capture_burst(os.path.join(WORK, "captures", "01-baseline.pcapng"), 0)
    template = make_template(final)
    expected = [None if kind == "GET" else bytes.fromhex(data) for _, kind, data in final]
    sample = {
        int(k): v
        for k, v in json.load(open(os.path.join(ROOT, "aurora", "data", "sample-image.json"))).items()
    }
    ok_final = equivalent(template, [r for _, r in burst.build(template, sample)], expected)
    expected_startup = [None if kind == "GET" else bytes.fromhex(data) for _, kind, data in startup]
    built_startup = [r for _, r in burst.build(template, diffimg.image(startup))]
    ok_startup = equivalent(template, built_startup, expected_startup)
    print("final burst reproduced:", ok_final, "| startup burst reproduced:", ok_startup)
    if not (ok_final and ok_startup):
        raise SystemExit("offline check failed, nothing written")
    with open(os.path.join(ROOT, "aurora", "data", "apply-template.json"), "w") as f:
        json.dump(template, f)
    with open(os.path.join(ROOT, "tests", "data", "final-burst.json"), "w") as f:
        json.dump([None if r is None else r.hex() for r in expected], f)


if __name__ == "__main__":
    main()

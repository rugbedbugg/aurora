import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import decode


def image(burst):
    img = {}
    for _, k, d in burst:
        if k != "SET":
            continue
        o = bytes.fromhex(d)
        if o[2] == 3:
            img[(o[5] << 8 | o[4]) + o[3]] = o[6]
    return img


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        bursts = decode.main(sys.argv[1])
    print(len(bursts), "bursts")
    imgs = [image(b) for b in bursts]
    for i in range(1, len(imgs)):
        a, b = imgs[i - 1], imgs[i]
        d = [(x, a.get(x), b.get(x)) for x in sorted(set(a) | set(b)) if a.get(x) != b.get(x)]
        print(f"burst {i - 1} -> {i}: {len(d)} byte(s) differ, t={bursts[i][0][0]:.1f}s")
        for x, p, q in d:

            def f(v):
                return "--" if v is None else f"{v:02x}"

            print(f"   0x{x:03x}: {f(p)} -> {f(q)}")

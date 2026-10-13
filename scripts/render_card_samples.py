"""Render sample READY PNG cards (LONG/SHORT, 1-3 TP, expensive and ultra-cheap coins) to a directory; asserts 1000x1230 PNG."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_ready_card as card
from PIL import Image

CASES = [
    ("BTCUSDT_LONG_3TP", "BTCUSDT", "LONG", 84200.0, [84200.0, 84350.0], 83900.0, [85100.0, 85800.0, 86900.0], 84250.0),
    ("ETHUSDT_SHORT_2TP", "ETHUSDT", "SHORT", 3120.55, [3118.2, 3124.9], 3151.4, [3079.0, 3040.2, None], 3121.0),
    ("TIAUSDT_LONG_1TP", "TIAUSDT", "LONG", 0.5942, [0.58322, 0.59376], 0.56865, [0.6254, None, None], 0.5942),
    ("1000PEPEUSDT_SHORT_3TP", "1000PEPEUSDT", "SHORT", 0.0098765, [0.0098321, 0.0099110], 0.0102450, [0.0094120, 0.0090015, 0.0085560], 0.0098800),
    ("SHIBLIKE_LONG_3TP", "1000SHIBUSDT", "LONG", 0.00001234, [0.00001221, 0.00001240], 0.00001198, [0.00001301, 0.00001377, 0.00001452], 0.00001236),
]


def candles(price, n=96, vol=0.004):
    out, p = [], price * 0.985
    for i in range(n):
        o = p
        c = o * (1 + vol * math.sin(i / 5.0) + 0.0006 * (1 if i % 7 else -2))
        h, l = max(o, c) * (1 + vol / 3), min(o, c) * (1 - vol / 3)
        out.append({"ts": f"2026-10-13T{(i // 4) % 24:02d}:{(i % 4) * 15:02d}:00+00:00", "open": o, "high": h, "low": l, "close": c, "volume": 1000 + i})
        p = c
    return out


def main(outdir):
    os.makedirs(outdir, exist_ok=True)
    paths = []
    for name, sym, d, entry, zone, sl, tps, ready in CASES:
        path = os.path.join(outdir, name + ".png")
        r = card.render(symbol=sym, direction=d, candles=candles(entry), entry=entry, zone=zone, sl=sl, tp1=tps[0], tp2=tps[1], tp3=tps[2],
                        ready_price=ready, key_level=zone[0], key_label="рівень", path=path)
        assert r.get("ok"), (name, r)
        with Image.open(path) as im:
            assert im.format == "PNG" and im.size == (1000, 1230), (name, im.format, im.size)
        paths.append(path)
    return paths


if __name__ == "__main__":
    for p in main(sys.argv[1] if len(sys.argv) > 1 else "card_samples"):
        print("ok", p)

#!/usr/bin/env python3
"""Докази READY на картці: геометрія береться з існуючих детекторів, малюється лише те, що дало підтвердження; без відтворюваної геометрії — не малюємо."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
import office_ready_card as rc  # noqa: E402
import office_ready_evidence as ev  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def walk(vertices, legs, pad=0.15):
    closes = [vertices[0]]
    for (a, b), n in zip(zip(vertices, vertices[1:]), legs):
        for k in range(1, n + 1):
            closes.append(a + (b - a) * k / n)
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        rows.append({"ts": (T0 + timedelta(minutes=15 * i)).isoformat(), "open": prev, "high": c + pad, "low": c - pad, "close": c})
        prev = c
    return rows


# SHORT-прапор: імпульс вниз 112→100, відкат до 102,5, пробій вниз
flag = walk([112, 100, 102.5, 99.2], [6, 8, 4])
e = ev.build(flag, "SHORT", 101.5, 102.5, ["flag", "level_retest"])
kinds = [i["kind"] for i in e["items"]]
check("flag" in kinds, f"прапор знайдено з геометрією: {e}")
fl = next((i for i in e["items"] if i["kind"] == "flag"), None)
check(fl is not None and len(fl["lines"]) == 2 and all(k in fl["lines"][0] for k in ("t0", "p0", "t1", "p1")), "дві межі прапора з часом і ціною")
json.dumps(e)   # зберігається у знімку: має бути JSON-сумісним
# тег без відтворюваної геометрії → не малюємо, а записуємо в missing
e2 = ev.build(flag, "SHORT", 101.5, 102.5, ["fvg_retest"])
check(not e2["items"] and "fvg_retest" in e2["missing"], f"FVG, якого не було, не вигадуємо: {e2}")
# теги-тригери без геометрії (engulf) ігноруються; максимум 3 елементи
e3 = ev.build(flag, "SHORT", 101.5, 102.5, ["engulf", "pin_bar"])
check(not e3["items"] and not e3["missing"], "тригерні теги не дають елементів")
check(len(ev.build(flag, "SHORT", 101.5, 102.5, list(ev.PRIORITY))["items"]) <= ev.MAX_ITEMS, "не більше 3")
check(ev.build(flag[:9], "SHORT", 101.5, 102.5, ["flag"])["items"] == [], "мало свічок → нічого")

# картинка з доказом
path = os.path.join(tempfile.gettempdir(), "test_ready_evidence.png")
r = rc.render(symbol="TESTUSDT", direction="SHORT", candles=flag, entry=102.0, zone=[101.5, 102.5], sl=103.5, tp1=99.0, tp2=97.0, ready_price=102.0, evidence=e["items"], path=path)
check(r.get("ok") and "flag" in r["drawn"]["evidence"], f"прапор намальовано: {r}")
r0 = rc.render(symbol="TESTUSDT", direction="SHORT", candles=flag, entry=102.0, zone=[101.5, 102.5], sl=103.5, tp1=99.0, tp2=97.0, ready_price=102.0, path=path + "0.png")
check(r0.get("ok") and r0["drawn"]["evidence"] == [] and r["sha256"] != r0["sha256"], "без доказів — картинка без них; з доказами — інша")
# канал і рівень/FVG як елементи: рендер не падає на всіх видах
items = [{"kind": "channel_edge", "label": "канал", "draw": "lines", "lines": [{"t0": 1767225600.0, "p0": 105.0, "t1": 1767241800.0, "p1": 101.0, "role": "upper"},
                                                                                  {"t0": 1767225600.0, "p0": 103.0, "t1": 1767241800.0, "p1": 99.0, "role": "mid"}]},
         {"kind": "fvg_retest", "label": "FVG", "draw": "band", "lo": 101.0, "hi": 101.6, "t0": 1767230000.0},
         {"kind": "sweep_pool", "label": "зняли стопи", "draw": "hline", "price": 103.0, "t0": 1767230000.0}]
r1 = rc.render(symbol="TESTUSDT", direction="SHORT", candles=flag, entry=102.0, zone=[101.5, 102.5], sl=103.5, tp1=99.0, ready_price=102.0, evidence=items, path=path + "1.png")
check(r1.get("ok") and set(r1["drawn"]["evidence"]) == {"channel_edge", "fvg_retest", "sweep_pool"}, f"усі види малюються: {r1}")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)

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

# --- контрольні картки: базові підписи читаються, докази видно, підписи не перетинаються, нічого не обрізано
import math  # noqa: E402
import random  # noqa: E402


def noise_rows(n, base, vol, start_min=-100000):
    random.seed(11)
    rows, p = [], base
    for i in range(n):
        o = p
        p = o * (1 + random.gauss(0, vol))
        rows.append({"ts": (T0 + timedelta(minutes=start_min + 15 * i)).isoformat(), "open": o, "high": max(o, p) * (1 + vol / 3), "low": min(o, p) * (1 - vol / 3), "close": p})
    return rows


def overlaps(a, b):
    return not (a[3] <= b[1] or b[3] <= a[1] or a[2] <= b[0] or b[2] <= a[0])


def check_card(name, res, expect_ev):
    check(res.get("ok"), f"{name}: картинка побудована {res.get('reason')}")
    if not res.get("ok"):
        return
    d = res["drawn"]
    boxes = d["label_boxes"]
    W, H = d["size_px"]
    check(all(b[1] >= 0 and b[2] >= 0 and b[3] <= W and b[4] <= H for b in boxes), f"{name}: підписи не обрізані: {[b for b in boxes if not (b[1] >= 0 and b[2] >= 0 and b[3] <= W and b[4] <= H)]}")
    bad = [(a[0], b[0]) for i, a in enumerate(boxes) for b in boxes[i + 1:] if overlaps(a[1:], b[1:])]
    check(not bad, f"{name}: підписи перетинаються: {bad}")
    names = " ".join(b[0] for b in boxes)
    check("SL" in names and "TP1" in names and "READY" in names and "ВХІД" in names, f"{name}: базові підписи на місці: {names}")
    check(set(d["evidence"]) == set(expect_ev), f"{name}: докази {d['evidence']} ≠ {expect_ev}")
    check(d["sl"] is not None and not math.isnan(d["sl"]), f"{name}: SL намальовано")
    check(all(x <= 90.0 for x in d["label_dist_px"]), f"{name}: підписи не далі 90 px від своєї геометрії: {d['label_dist_px']}")


# 1) flag + рівень: SHORT; прапор — з реального детектора на 96 свічках
pre = noise_rows(77, 112.0, 0.002, start_min=-77 * 15)
rows1 = pre + walk([112, 100, 102.5, 99.2], [6, 8, 4])
for i, r in enumerate(rows1):
    r["ts"] = (T0 + timedelta(minutes=15 * i)).isoformat()
for i in range(1, 77):   # зшиваємо ціну: префікс завершується там, де починається імпульс
    pass
e1 = ev.build(rows1, "SHORT", 101.5, 102.5, ["flag"])
band = {"kind": "level_retest", "label": "рівень", "draw": "band", "lo": 101.7, "hi": 102.4}
items1 = [x for x in e1["items"] if x["kind"] == "flag"] + [band]
check(bool(e1["items"]), f"flag знайдено детектором у 96 свічках: {e1}")
r1 = rc.render(symbol="TESTUSDT", direction="SHORT", candles=rows1[-96:], entry=102.0, zone=[101.5, 102.5], sl=103.5, tp1=99.0, tp2=97.0, ready_price=102.0, evidence=items1,
               path=os.path.join(tempfile.gettempdir(), "ctl_flag_level.png"))
check_card("flag+level", r1, [x["kind"] for x in items1])
# 2) FVG + sweep + BOS (усі три конкурують за місце біля входу)
rows2 = noise_rows(96, 100.0, 0.003)
rows2 = [dict(c, ts=(T0 + timedelta(minutes=15 * i)).isoformat()) for i, c in enumerate(rows2)]
tb = T0.timestamp()
last = rows2[-1]["close"]
items2 = [{"kind": "fvg_retest", "label": "FVG", "draw": "band", "lo": last * 0.998, "hi": last * 1.002, "t0": tb + 900 * 45, "t1": tb + 900 * 95, "direction": "SHORT", "status": "MITIGATED"},
          {"kind": "sweep_pool", "label": "зняли стопи", "draw": "sweep", "price": last * 1.003, "pool": "BSL", "type": "high", "t0": tb + 900 * 40, "t_sweep": tb + 900 * 90,
           "extreme": last * 1.006, "close": last * 1.001},
          {"kind": "bos", "label": "BOS", "draw": "break", "price": last * 0.9985, "t0": tb + 900 * 55, "t_break": tb + 900 * 80, "close": last * 0.997}]
r2 = rc.render(symbol="TESTUSDT", direction="SHORT", candles=rows2,
               entry=last, zone=[last * 0.999, last * 1.001], sl=last * 1.015, tp1=last * 0.97, tp2=last * 0.95, ready_price=last, evidence=items2,
               path=os.path.join(tempfile.gettempdir(), "ctl_fvg_sweep.png"))
check_card("fvg+sweep+bos", r2, ["fvg_retest", "sweep_pool", "bos"])
# 2b) sweep із реального детектора: рівень, тінь, закриття назад
sw_rows = []
for i in range(40):
    base = 100 + 0.2 * ((i % 3) - 1)
    h, l, o, c = base + 0.4, base - 0.4, base - 0.1, base + 0.1
    if i in (10, 20):
        h = 105
    if i == 36:
        h, c, o = 106, 103.2, 104.5
    sw_rows.append({"ts": (T0 + timedelta(minutes=15 * i)).isoformat(), "open": o, "high": h, "low": l, "close": c})
e_sw = ev.build(sw_rows, "SHORT", 103, 106, ["sweep_pool"])
it_sw = e_sw["items"][0] if e_sw["items"] else {}
check(it_sw.get("draw") == "sweep" and it_sw.get("price") == 105.0 and it_sw.get("extreme") == 106.0 and it_sw.get("close") == 103.2 and it_sw.get("type") == "high"
      and it_sw.get("t0") and it_sw.get("t_sweep"), f"sweep: рівень, тип, екстремум, закриття, час: {e_sw}")
r_sw = rc.render(symbol="TESTUSDT", direction="SHORT", candles=sw_rows, entry=103.0, zone=[102.5, 103.5], sl=106.5, tp1=100.0, ready_price=103.0, evidence=e_sw["items"],
                 path=os.path.join(tempfile.gettempdir(), "ctl_sweep_real.png"))
check_card("sweep(real)", r_sw, ["sweep_pool"])
# 2c) знімок графіка: свічки заморожені, докази = вихід детекторів на них, картка малює ті самі свічки 1:1, аудит зв'язує елементи зі свічками
for r_ in sw_rows:
    r_["src"] = "binance_futures"
decided = T0.timestamp() + 40 * 900 + 5
chart = ev.freeze_chart(sw_rows, decided, "15m")
check(chart["n"] == 40 and chart["source"] == "binance_futures" and chart["range"] == [T0.timestamp(), T0.timestamp() + 39 * 900], f"знімок: діапазон, джерело, кількість: {chart['range']} {chart['source']}")
gate = {"chart": chart}
e_fr = ev.build(ev.candles_from_chart(chart), "SHORT", 103, 106, ["sweep_pool"], now_ts=decided)
gate["evidence"] = e_fr["items"]
check(bool(e_fr["items"]), "докази на frozen-свічках знайдені")
vr = ev.verify(gate, "SHORT", [103, 106], ["sweep_pool"])
check(vr["ok"], f"докази відтворюються з frozen-свічок: {vr}")
bad = dict(gate, evidence=[dict(gate["evidence"][0], price=999.0)])
check(not ev.verify(bad, "SHORT", [103, 106], ["sweep_pool"])["ok"], "підміна координати доказу виявляється")
tam = dict(gate, chart=dict(chart, candles=[chart["candles"][0][:2] + [999.0] + chart["candles"][0][3:]] + chart["candles"][1:]))
check(not ev.verify(tam, "SHORT", [103, 106], ["sweep_pool"])["ok"], "підміна свічки у знімку виявляється (sha)")
rr = rc.render(symbol="TESTUSDT", direction="SHORT", candles=ev.candles_from_chart(chart), entry=103.0, zone=[102.5, 103.5], sl=106.5, tp1=100.0, ready_price=103.0, evidence=gate["evidence"],
               path=os.path.join(tempfile.gettempdir(), "ctl_snapshot.png"))
check(rr.get("ok") and rr["drawn"]["ohlc_sha"] == chart["sha256"], f"OHLC на картці = OHLC знімка (sha): {rr.get('drawn', {}).get('ohlc_sha')} vs {chart['sha256']}")
au = ev.audit(gate)
check(au and au[0]["detector"] == "office_smc.sweeps" and au[0]["rule"] and au[0]["anchors_on_real_candles"] is True and au[0]["proof_complete"], f"аудит: елемент → детектор → правило → свічки: {au}")
check(all(a["candle_exists"] and a["price_within_candle"] for a in au[0]["anchors"]), "опорні точки лежать на реальних свічках у межах їхнього high/low")
# неповний доказ чесно позначений
fl_gate = {"chart": ev.freeze_chart(rows1[-96:], T0.timestamp() + 10 ** 7, "15m")}
fl_gate["evidence"] = ev.build(ev.candles_from_chart(fl_gate["chart"]), "SHORT", 101.5, 102.5, ["flag"], now_ts=T0.timestamp() + 10 ** 7)["items"]
afl = ev.audit(fl_gate)
check(afl and afl[0]["proof_complete"] is False and afl[0]["proof_note"], f"прапор: неповний доказ позначений (детектор не віддає свінги): {afl}")
# 2d) походження знімка + звірка з «архівом» (синтетичний архів) і виявлення розбіжності
sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_snapshot_vs_archive as va  # noqa: E402

ch2 = ev.freeze_chart(sw_rows, decided, "15m", symbol="TESTUSDT")
pv = ch2["provenance"]
check(pv["exchange"] == "Binance USDT-M Futures" and pv["symbol"] == "TESTUSDT" and pv["interval"] == "15m" and pv["step_sec"] == 900 and pv["received_ts"] == decided
      and pv["close_time_last"] == ch2["range"][1] + 900 and pv["last_candle_forming"] is False and pv["known_gaps"], f"provenance: {pv}")
arch = {round(c[0]): tuple(c[1:6]) for c in ch2["candles"]}
check(all(r["status"] == "OK" for r in va.compare(ch2["candles"], arch, 5)), "звірка з архівом: збігається")
arch_bad = dict(arch)
k0 = round(ch2["candles"][0][0])
arch_bad[k0] = (arch[k0][0], arch[k0][1] + 0.5) + arch[k0][2:]
check(any(r["status"] == "DIFF" for r in va.compare(ch2["candles"], arch_bad, 5)), "розбіжність OHLC з архівом виявляється")
check(any(r["status"] == "NO_ARCHIVE_ROW" for r in va.compare(ch2["candles"], {}, 3)), "немає рядка архіву — чесно NO_ARCHIVE_ROW")
check(ev.freeze_chart(sw_rows[:-1] + [dict(sw_rows[-1], src="bybit_linear")], decided, "15m", symbol="X")["provenance"]["exchange"].startswith("змішане"), "запасне джерело не видається за Binance Futures")
# 3) channel_edge — канал із реального детектора
rows3 = []
for i in range(120):
    c = 100 - 0.04 * i + 1.2 * math.sin(i / 4.0)
    rows3.append({"ts": (T0 + timedelta(minutes=15 * i)).isoformat(), "open": c + 0.1, "high": c + 0.5, "low": c - 0.5, "close": c})
rows3 = rows3[-96:]
e3 = ev.build(rows3, "SHORT", 96, 97, ["channel_edge"])
ch_items = e3["items"] or [{"kind": "channel_edge", "label": "канал", "draw": "lines", "lines": []}]
check(bool(e3["items"]), f"канал побудований детектором: {e3}")
px3 = rows3[-1]["close"]
r3 = rc.render(symbol="TESTUSDT", direction="SHORT", candles=rows3, entry=px3, zone=[px3 - 0.3, px3 + 0.3], sl=px3 + 1.5, tp1=px3 - 2.5, ready_price=px3, evidence=ch_items,
               path=os.path.join(tempfile.gettempdir(), "ctl_channel.png"))
check_card("channel", r3, ["channel_edge"])
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)

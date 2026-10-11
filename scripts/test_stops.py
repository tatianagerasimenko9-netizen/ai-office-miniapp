#!/usr/bin/env python3
"""Три варіанти стопа: розрахунок (LONG/SHORT), ліквідність/кругле число, обґрунтованість, оцінка варіантів на свічках без підміни фактичного результату, аналіз руху після стопа, порівняльна статистика."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import office_bridge as OB  # noqa: E402
import test_office2_brain2 as TB  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import radar_text as RT  # noqa: E402
from office2 import radar_watch as RW  # noqa: E402
from office2 import stops as SV  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


# --- 1. розрахунок
v = SV.variants("LONG", 99.0, 0.05, 0.5, [], entry=100.0)
check("LONG: стопи нижче екстремуму; поточний = екстремум − люфт; запас ATR = 12,5 % ATR", abs(v["v1"]["sl"] - 98.95) < 1e-9 and abs(v["v3"]["sl"] - (99.0 - 0.125 * 0.5)) < 1e-9 and v["v2"]["sl"] < 99.0 and all(v[k]["beyond_extreme"] for k in ("v1", "v2", "v3")), str(v))
vs = SV.variants("SHORT", 101.0, 0.05, 0.5, [], entry=100.0)
check("SHORT: дзеркально — стопи вище екстремуму", abs(vs["v1"]["sl"] - 101.05) < 1e-9 and vs["v3"]["sl"] > 101.0 and vs["v2"]["sl"] > 101.0)
check("нормальний випадок: обґрунтований (за екстремумом, поза шумом, у межах ризику, не біля рівня)", v["v1"]["justified"] and v["v3"]["justified"], str(v["v1"]))
lv = [{"p": 98.94, "side": "low", "kind": "PDL", "strength": 2, "taken_ts": None}]
v2 = SV.variants("LONG", 99.0, 0.05, 0.5, lv, entry=100.0)
check("стоп біля очевидного рівня (мінімум попереднього дня) → сумнівний, є пояснення про ліквідність", v2["v1"]["liq"] and "PDL" in v2["v1"]["liq"] and not v2["v1"]["justified"], str(v2["v1"]))
check("кругле число поруч зі стопом розпізнається", SV.near_round(100.02, 0.5) == 100.0 and SV.near_round(97.3, 0.5) is None)
tight = SV.variants("LONG", 99.9, 0.01, 0.5, [], entry=100.0)
check("стоп у межах нормального шуму (< 1 ATR від входу) → не обґрунтований", not tight["v1"]["noise_ok"] and not tight["v1"]["justified"], str(tight["v1"]))
fe = SV.finalize_for_entry(v, "LONG", 100.0)
check("finalize_for_entry: рекомендація = найкращий обґрунтований варіант (v3 перший)", fe["recommended"] == "v3", str(fe.get("recommended")))
check("пояснення простою мовою", all(x.startswith(("Обґрунтований:", "Сумнівний:")) for x in SV.explain_ua(fe)) and "місця скупчення стопів" in " ".join(SV.explain_ua(SV.finalize_for_entry(v2, "LONG", 100.0))))

# --- 2. аналіз руху після стопа
def cds(bars, t0=1000.0):
    return [{"ts": t0 + 900 * i, "high": h, "low": l, "close": c} for i, (h, l, c) in enumerate(bars)]


hunt = SV.after_stop("LONG", cds([(99.2, 98.8, 99.0), (100.3, 99.0, 100.2), (101.0, 100.0, 100.9)]), 1000.0, 100.0, 98.9, 101.5, 99.0)
check("стоп вибито, ціна повернулась у бік ідеї без закриття за екстремумом → STOP_HUNT", hunt["verdict"] == "STOP_HUNT" and hunt["reclaimed_entry"], str(hunt))
broken = SV.after_stop("LONG", cds([(99.0, 97.0, 97.5), (98.0, 96.0, 96.2), (97.0, 95.5, 95.9)]), 1000.0, 100.0, 98.9, 101.5, 99.0)
check("закриття за екстремумом, рух проти ≥1 R → BROKEN", broken["verdict"] == "BROKEN" and broken["closed_beyond_extreme"], str(broken))
check("немає свічок після стопа → NO_DATA", SV.after_stop("LONG", [], 1000.0, 100.0, 98.9, 101.5, 99.0)["verdict"] == "NO_DATA")

# --- 3. Brain додає stops, не змінюючи рішення
c, seq = TB.closes_long()
orig = B.all_levels
B.all_levels = lambda ctx, now: TB.LEVELS
try:
    rdy = TB.run(c, seq["trigger"])
    wait = TB.run(c, seq["top"])
finally:
    B.all_levels = orig
check("Brain: READY містить три варіанти стопа, поточний збігається з sl", rdy["state"] == "READY" and abs(rdy["stops"]["v1"]["sl"] - rdy["sl"]) < 1e-9 and {"v1", "v2", "v3"} <= set(rdy["stops"]), str(rdy.get("stops"))[:200])
check("Brain: preview WAIT містить stops", wait["state"] == "WAIT" and wait["preview"].get("stops"))

# --- 4. картка: варіанти, оцінка без підміни фактичного результату
def new_db():
    td = tempfile.mkdtemp()
    db = os.path.join(td, "s.db")
    OB.init_office_db(db)
    EN.init_db(db)
    return db


NOW = 1_800_000_000.0
HEX = "abcdef012345"
th = {"id": "x", "dir": "LONG", "state": "NO_TRADE", "entry": 100.2, "sl": 98.9, "risk_pct": 1.3, "targets": [{"p": 101.4, "kind": "PDH", "r": 1.0}, {"p": 102.6, "kind": "D1H", "r": 2.0}, {"p": 104.0, "kind": "W1H", "r": 3.2}],
      "entry_zone": [100.0, 100.4], "level": {"p": 99.5, "kind": "PDL"}, "stops": SV.variants("LONG", 98.95, 0.05, 0.5, [], entry=100.2)}
db = new_db()
OB._execute(db, "INSERT INTO office2_live_scenario VALUES (?,?,?,?,?,?,?,?,?,?,?)", (f"O2|{HEX}", "AAAUSDT", "LONG", "SWEEP_SEQ", "NO_TRADE", NOW, NOW, None, "ємність сценаріїв: денний ліміт: 3 стопи за добу UTC", json.dumps(th), "t"))
RW.sync(db, NOW + 5)
RW.mark_sent(db, f"B|O2|{HEX}", 55, NOW + 10)
card = dict(zip(RW._COLS, OB._fetchall(db, "SELECT " + ",".join(RW._COLS) + f" FROM office2_radar_card WHERE card_id = 'B|O2|{HEX}'")[0]))
st = json.loads(card["stops_json"])
check("картка зберігає три варіанти з ризиком під фактичний вхід", st["v1"]["risk_pct"] and st["v3"]["sl"] < st["v1"]["sl"] and "recommended" in st, str(st)[:200])
tb = (card["sent_ts"] // 900 + 1) * 900
# сценарій: вхід, глибокий прокол під екстремум (98.9 — вибиває стопи 1 і 2, але не стоп 3 = 98.95−0.0625…), потім ціна летить до TP1
bars = [(100.5, 100.1, 100.3), (100.4, 98.9, 99.0), (101.6, 99.5, 101.5), (102.0, 101.0, 101.8)] + [(102.0, 101.0, 101.5)] * 8
cl = [{"ts": tb + 900 * i, "high": h, "low": l, "close": c_} for i, (h, l, c_) in enumerate(bars)]
sv = RW.evaluate_variants(card, cl, tb + 900 * 20)
prim = RW.evaluate_card(card, cl, tb + 900 * 20)
check("варіанти оцінені окремо; поточний варіант збігається з фактичним результатом картки (не підміняється)", sv["v1"]["status"] == prim["paper_status"] and sv["v1"]["r_net"] == prim["r_net"], f"{sv['v1']} {prim}")
check("тугі стопи вибито, широкий (стоп 3) вистояв — різні результати варіантів", sv["v1"]["status"] == "SL" and sv["v2"]["status"] == "SL" and sv["v3"]["status"] in ("TP1", "ENTERED") and sv["v3"]["r_net"] > 0, str(sv))
check("після стопа 1 ціна повернулась у бік ідеї → STOP_HUNT", (sv["v1"].get("after") or {}).get("verdict") == "STOP_HUNT", str(sv["v1"].get("after")))
OB._execute(db, "UPDATE office2_radar_card SET stop_eval = ?, paper_status = ?, r_net = ? WHERE card_id = ?", (json.dumps(sv), prim["paper_status"], prim["r_net"], f"B|O2|{HEX}"))
sm = RW.summary(db, NOW + 100000)
view = [x for x in sm["cards"] if x["card_id"] == f"B|O2|{HEX}"][0]["h"]["stops"]
check("Mini App отримує готовий показ трьох стопів із поясненнями й висновком після стопа", len(view["items"]) == 3 and view["items"][0]["after"] and view["items"][0]["explain"] and view["summary"], str(view)[:300])
study = sm["stats"]["stop_study"]
check("порівняльна статистика: замало даних → чесний вердикт без висновків", study["n"] <= 1 and "Замало даних" in study["verdict"], str(study)[:200])
# ≥30 угод: синтетична агрегація
rows = []
for i in range(30):
    ev = {"v1": {"status": "SL", "r_net": -1.2, "risk_pct": 1.2}, "v2": {"status": "SL", "r_net": -1.3, "risk_pct": 1.1}, "v3": {"status": "TP1" if i % 2 else "SL", "r_net": 0.8 if i % 2 else -1.1, "risk_pct": 1.4}}
    rows.append({"stop_eval": json.dumps(ev)})
z = RW.stop_study(rows)
check("≥30 угод: сума й різниця проти поточного стопа рахуються; вердикт називає найкращий", z["n"] == 30 and z["variants"]["v3"]["delta_sum_r_vs_current"] > 0 and "v3" in z["verdict"], str(z))
tx = RW.format_card(card)
check("Telegram: три варіанти стопа простою мовою з позначкою обґрунтований/сумнівний", "Три варіанти стопа" in tx and "Стоп 1 · поточний" in tx and "Стоп 3 · структура + запас ATR" in tx, tx)
JARGON = ("ATR(", "SL ", "TP1", "R ")
check("у тексті Telegram немає англійських скорочень стопів/цілей (лише ATR як назва в підписі варіанта)", "TP" not in tx.split("Технічно:")[0] and " SL" not in tx.split("Технічно:")[0], tx)
print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)

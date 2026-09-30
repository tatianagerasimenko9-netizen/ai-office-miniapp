"""Аналіз правила RR: формули старого/нового правила, симуляція плану виходу 40/30/30 у R, зведення дублів плану, відновлення TP2 без підглядання."""
import io
import os
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

import office_rr_analysis as rr  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


FEE = 0.10
# --- формули: AKE з журналу (ризик 3,04%, до TP1 4,56%) ---
p = rr.rr_pair(0.030477832, 0.029552060, 0.031866490, None, FEE)
check("AKE: RR до TP1 після комісій ≈ 1,42 (як у шлюзі production)", abs(p["rr_tp1"] - 1.42) < 0.01, str(p))
check("AKE без TP2: зважений RR = RR до TP1 (весь обсяг на TP1)", abs(p["rr_weighted"] - p["rr_tp1"]) < 1e-9)
check("AKE: старе відхиляє, нове теж (TP2 немає → 1,42 < 1,5)", not rr.passes_old(p) and not rr.passes_new(p))

p2 = rr.rr_pair(100.0, 97.0, 104.0, 110.0, FEE)       # ризик 3%, TP1 4%, TP2 10%
check("TP1 4%/ризик 3%: RR до TP1 = (4−0,1)/(3+0,1) = 1,258", abs(p2["rr_tp1"] - 3.9 / 3.1) < 1e-9)
check("зважений = (0,4·4 + 0,6·10 − 0,1)/(3,1) = 2,452", abs(p2["rr_weighted"] - (0.4 * 4 + 0.6 * 10 - 0.1) / 3.1) < 1e-9)
check("такий план: старе ВІДХИЛЯЄ (1,26<1,5), нове ПРОПУСКАЄ (2,45≥1,5 і 1,26≥1,0)", (not rr.passes_old(p2)) and rr.passes_new(p2))
p3 = rr.rr_pair(100.0, 97.0, 102.0, 130.0, FEE)       # TP1 2% → RR до TP1 0,61 <1,0, хоч зважений великий
check("RR до TP1 < 1,0 → нове відхиляє, навіть коли зважений великий", rr.rr_pair(100, 97, 102, 130, FEE)["rr_weighted"] >= 1.5 and not rr.passes_new(p3))
p4 = rr.rr_pair(100.0, 98.0, 103.0, 106.0, FEE)       # старе пройде (RR до TP1 = 2,9/2,1=1,38?) уточнюємо нижче
p5 = rr.rr_pair(100.0, 98.0, 104.0, None, FEE)        # RR до TP1 = 3,9/2,1 = 1,857
check("план, що проходить старе, проходить і нове (TP2 далі TP1 або немає)", rr.passes_old(p5) and rr.passes_new(p5))
check("SHORT рахується дзеркально", abs(rr.rr_pair(100, 103, 96, None, FEE)["rr_tp1"] - 3.9 / 3.1) < 1e-9)
check("геометрія: стоп не з того боку → BAD", not rr.geometry_ok("LONG", 100, 101, 104, None) and rr.geometry_ok("SHORT", 100, 103, 96, 92))

# --- симуляція ---
T0 = datetime(2026, 9, 20, 0, 0, tzinfo=timezone.utc)


def bar(i, o, h, l, c):
    return {"ts": (T0 + timedelta(minutes=15 * i)).isoformat(), "open": o, "high": h, "low": l, "close": c, "volume": 1.0}


start = T0.timestamp()
risk, d1, d2 = 3.0, 4.0, 10.0
ent, sl, t1, t2 = 100.0, 97.0, 104.0, 110.0
base = [bar(0, 100, 100.2, 99.8, 100)]        # вхід торкається ціни 100 на першій свічці
r = rr.simulate_R("LONG", ent, sl, t1, t2, base + [bar(1, 100, 100.5, 96.0, 97.5)], start, FEE)
check("стоп до TP1 → −(risk+fee)/risk = −1,033 R", r["status"] == "STOP" and abs(r["R"] - (-(3.0 + 0.1) / 3.0)) < 1e-9, str(r))
r = rr.simulate_R("LONG", ent, sl, t1, t2, base + [bar(1, 100, 105, 96, 101)], start, FEE)
check("стоп і TP1 в одній свічці → консервативно стоп", r["status"] == "STOP")
r = rr.simulate_R("LONG", ent, sl, t1, t2, base + [bar(1, 100, 104.5, 99.9, 104), bar(2, 104, 104.2, 99.5, 100)], start, FEE)
check("TP1 (40%) → повернення до входу → беззбиток: R = (0,4·4 − 0,1)/3 = 0,5", r["status"] == "TP1_THEN_BE" and abs(r["R"] - (0.4 * 4 - 0.1) / 3.0) < 1e-9, str(r))
r = rr.simulate_R("LONG", ent, sl, t1, t2, base + [bar(1, 100, 104.5, 99.9, 104), bar(2, 104, 110.5, 103, 110)], start, FEE)
check("TP1 і TP2: R = (0,4·4 + 0,6·10 − 0,1)/3 = 2,5", r["status"] == "TP2" and abs(r["R"] - (0.4 * 4 + 0.6 * 10 - 0.1) / 3.0) < 1e-9, str(r))
r = rr.simulate_R("LONG", ent, sl, t1, t2, base + [bar(1, 100, 101, 99.5, 100.5)], start, FEE)
check("ні стоп, ні ціль за горизонт → OPEN за ціною закриття", r["status"] == "OPEN" and abs(r["R"] - (0.5 - 0.1) / 3.0) < 1e-9, str(r))
r = rr.simulate_R("LONG", 90.0, 87.0, 94.0, None, base + [bar(1, 100, 101, 99.5, 100.5)], start, FEE)
check("ціна не торкнулась входу → NOT_FILLED", r["status"] == "NOT_FILLED")
r = rr.simulate_R("SHORT", 100.0, 103.0, 96.0, 90.0, base + [bar(1, 100, 100.4, 95.5, 96), bar(2, 96, 100.5, 95.9, 100.2)], start, FEE)
check("SHORT: TP1 → беззбиток", r["status"] == "TP1_THEN_BE" and abs(r["R"] - (0.4 * 4 - 0.1) / 3.0) < 1e-9, str(r))
r = rr.simulate_R("LONG", ent, sl, t1, None, base + [bar(1, 100, 104.5, 99.9, 104), bar(2, 104, 104.3, 103.9, 104.1)], start, FEE)
check("TP2 немає: залишок виходить разом із TP1 (R = (4−0,1)/3)", r["status"] == "TP1_ONLY" and abs(r["R"] - (4.0 - 0.1) / 3.0) < 1e-9, str(r))

# --- зведення дублів плану з БД ---
d = tempfile.mkdtemp()
db = os.path.join(d, "t.db")
con = sqlite3.connect(db)
con.executescript("""CREATE TABLE office_signals (signal_id TEXT, symbol TEXT, direction TEXT, entry_low REAL, entry_high REAL, sl REAL, tp1 REAL, tp2 REAL, ts_created TEXT);
CREATE TABLE trade_journal (trade_id TEXT, ts_open_utc TEXT, symbol TEXT, direction TEXT, entry_price REAL, stop_loss REAL, take_profit REAL, r_multiple REAL, outcome TEXT, status TEXT);""")
for i in range(5):   # той самий план щоциклу
    con.execute("INSERT INTO office_signals VALUES (?,?,?,?,?,?,?,?,?)", (f"lev-watch-x-{i}", "BTCUSDT", "LONG", 99.0, 101.0, 97.0, 104.0, None, f"2026-09-20T0{i}:00:00+00:00"))
con.execute("INSERT INTO office_signals VALUES (?,?,?,?,?,?,?,?,?)", ("SCN|BTCUSDT|SHORT|H1|a", "BTCUSDT", "SHORT", 99.0, 101.0, 103.0, 96.0, 92.0, "2026-09-21T00:00:00+00:00"))
con.execute("INSERT INTO office_signals VALUES (?,?,?,?,?,?,?,?,?)", ("watch-none", "ETHUSDT", "LONG", 1.0, 2.0, None, None, None, "2026-09-21T00:00:00+00:00"))
con.execute("INSERT INTO trade_journal VALUES (?,?,?,?,?,?,?,?,?,?)", ("t1", "2026-09-22T10:00:00+00:00", "ETHUSDT", "LONG", 100.0, 97.0, 104.0, 1.2, "WIN", "CLOSED"))
con.commit()
con.close()
plans = rr.load_unique_plans(db)
check("дублі плану зведено: 5 → 1, SHORT окремо, рядок без SL/TP1 пропущено", len(plans) == 2, str([(x["id"], x["direction"]) for x in plans]))
jr = rr.load_journal(db)
check("журнал угод: план і фактичний R зчитано", len(jr) == 1 and jr[0]["actual_R"] == 1.2 and jr[0]["tp1"] == 104.0)

# --- TP2 без підглядання: замало свічок → None ---
check("замало свічок до плану → TP2 не відновлюємо", rr.reconstruct_tp2("LONG", 100.0, 104.0, [bar(i, 100, 101, 99, 100) for i in range(10)]) is None)

# --- evaluate_plan на «архіві» ---
def make_zip(day):
    d0 = datetime.fromisoformat(day + "T00:00:00+00:00")
    lines = []
    for i in range(96):
        t = d0 + timedelta(minutes=15 * i)
        c = 100.0
        h, l = 100.3, 99.7
        if day == "2026-09-21" and i == 8:
            h = 104.5   # після плану 20.09 ціна доходить до TP1
        lines.append(f"{int(t.timestamp() * 1000)},{c},{h},{l},{c},1,0,0,0,0,0,0")
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", "\n".join(lines))
    return b.getvalue()


def getter(url):
    day = "-".join(url.rsplit("-", 3)[-3:]).replace(".zip", "")
    return make_zip(day)


rr._CACHE.clear()
ev = rr.evaluate_plan({"symbol": "BTCUSDT", "direction": "LONG", "entry": 100.0, "sl": 97.0, "tp1": 104.0, "tp2": 110.0, "ts": datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc).timestamp(), "id": "x"}, getter)
check("evaluate_plan: RR за обома правилами, проходження і симуляція", ev["status"] == "OK" and ev["new"] and not ev["old"] and ev["sim"]["status"] in ("TP1_THEN_BE", "OPEN_AFTER_TP1", "TP1_ONLY", "OPEN", "TP2"), str(ev)[:300])
check("джерело TP2 з БД позначено", ev["tp2_src"] == "БД")
bad = rr.evaluate_plan({"symbol": "BTCUSDT", "direction": "LONG", "entry": 100.0, "sl": 101.0, "tp1": 104.0, "ts": 1.0, "id": "b"}, getter)
check("невірна геометрія → BAD_GEOMETRY", bad["status"] == "BAD_GEOMETRY")

# --- підсумок ---
rows = [ev, bad]
sm = rr.summarize(rows)
check("summarize: враховує лише придатні, only_new містить план, що проходить тільки нове", sm["usable"] == 1 and sm["bad_geometry"] == 1 and sm["only_new"]["n"] == 1 and sm["old_pass"]["n"] == 0, str(sm)[:300])

# --- повний прогін run(): контрольні кейси + історія + журнал ---
rr._CACHE.clear()
lines = []
out = rr.run(db, printer=lines.append, getter=getter)
txt = "\n".join(lines)
check("run: друкує правило, 4 кейси, історію і журнал", "[rr] правило:" in txt and all(f"кейс {k}" in txt for k in ("AKE", "LONGXIA", "LSK", "ENA")) and "історія:" in txt and "журнал угод власниці: 1" in txt, txt[:400])
check("run: групи old_pass/new_pass/only_new/only_old у підсумку", all(k in out["history"] for k in ("old_pass", "new_pass", "only_new", "only_old", "rejected_by_both")))

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)

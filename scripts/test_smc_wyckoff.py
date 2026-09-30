#!/usr/bin/env python3
"""ICT/SMC і Вайкоф як формальні правила: пули ліквідності, sweep, BOS/CHoCH, displacement, FVG, OB/breaker, OTE; діапазон, spring/upthrust, тест, обсяг."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_smc as S  # noqa: E402
import office_wyckoff as W  # noqa: E402
from office_patterns import atr  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = (T0 + timedelta(days=5)).timestamp()


def ts(i):
    return (T0 + timedelta(minutes=15 * i)).isoformat()


def walk(vertices, legs, pad=0.15, vol=100.0):
    closes = [vertices[0]]
    for (a, b), n in zip(zip(vertices, vertices[1:]), legs):
        for k in range(1, n + 1):
            closes.append(a + (b - a) * k / n)
    rows, prev = [], closes[0]
    for i, c in enumerate(closes):
        rows.append({"ts": ts(i), "open": prev, "high": c + pad, "low": c - pad, "close": c, "volume": vol})
        prev = c
    return rows


def kinds(tags):
    return [t["kind"] for t in tags]


# ---- пули ліквідності BSL/SSL і sweep: два рівні максимуми ≈110, тінь 111 із закриттям 109,4 → SHORT
base = walk([100, 110, 104, 110.05, 104, 106], [5, 5, 5, 5, 3])
sw = base + [{"ts": ts(len(base)), "open": 106, "high": 111.0, "low": 105.8, "close": 109.4, "volume": 120}]
sw += [{"ts": ts(len(sw)), "open": 109.4, "high": 109.6, "low": 108.0, "close": 108.4, "volume": 90}]
rows = S._rows(sw, NOW)
a = atr(rows)
pools = S.liquidity_pools(rows, a)
assert pools["BSL"] and abs(pools["BSL"][0]["level"] - 110.2) < 0.3 and pools["BSL"][0]["touches"] >= 2, pools
assert kinds(S.tags_for(sw, "SHORT", now_ts=NOW)).count("sweep_pool") == 1
assert "sweep_pool" not in kinds(S.tags_for(sw, "LONG", now_ts=NOW))
# закріплення над рівнем — не sweep
held = base + [{"ts": ts(len(base)), "open": 106, "high": 112.0, "low": 105.8, "close": 111.5, "volume": 120}]
assert "sweep_pool" not in kinds(S.tags_for(held, "SHORT", now_ts=NOW))

# ---- структура: BOS (за трендом) і CHoCH (проти)
up = walk([100, 106, 103, 110, 107, 114, 111, 117], [4, 3, 4, 3, 4, 3, 4])       # HH/HL, закриття за останнім свінг-хаєм 114 → BOS
st = S.structure(S._rows(up, NOW))
assert st["trend"] == "UP" and st["events"] and st["events"][0]["kind"] == "bos" and st["events"][0]["side"] == "LONG", st
dn = walk([120, 114, 117, 108, 111, 102, 105, 113], [4, 3, 4, 3, 4, 3, 6])        # LH/LL, закриття за останнім свінг-хаєм 111 → CHoCH LONG
st = S.structure(S._rows(dn, NOW))
assert st["trend"] == "DOWN" and st["events"] and st["events"][0]["kind"] == "choch" and st["events"][0]["side"] == "LONG", st

# ---- displacement, FVG, OB → breaker
rng = walk([100, 101, 100.2, 101.2, 100.4, 101.0, 100.6, 101.1, 100.5, 101.0, 100.7, 100.9, 100.6, 101.0], [2] * 13)
ob_base = rng + [{"ts": ts(len(rng)), "open": 101.0, "high": 101.1, "low": 99.9, "close": 100.0, "volume": 80}]           # остання ведмежа свічка (OB)
ob_base += [{"ts": ts(len(ob_base)), "open": 100.0, "high": 104.5, "low": 99.95, "close": 104.3, "volume": 200}]      # displacement вгору
ob_base += [{"ts": ts(len(ob_base)), "open": 104.3, "high": 105.5, "low": 103.6, "close": 105.2, "volume": 150}]      # low 103.6 > high першої (101.1)? для FVG потрібна третя свічка
ob_base += [{"ts": ts(len(ob_base)), "open": 105.2, "high": 105.8, "low": 104.8, "close": 105.4, "volume": 100}]
rows = S._rows(ob_base, NOW); a = atr(rows)
assert any(d["side"] == "LONG" for d in S.displacement(rows, a))
g = [x for x in S.fvgs(rows, a) if x["side"] == "LONG"]
assert g and g[-1]["state"] == "OPEN" and g[-1]["lo"] < g[-1]["hi"], S.fvgs(rows, a)
obs = [o for o in S.order_blocks(rows, a) if o["side"] == "LONG"]
assert obs and obs[-1]["kind"] == "ob" and obs[-1]["state"] == "ACTIVE" and abs(obs[-1]["lo"] - 99.9) < 1e-9, obs
# ретест FVG: ціна повертається в проміжок → mitigated → тег fvg_retest
fv = ob_base + [{"ts": ts(len(ob_base)), "open": 105.4, "high": 105.5, "low": 101.0, "close": 102.2, "volume": 90}]
fv += [{"ts": ts(len(fv)), "open": 102.2, "high": 102.8, "low": 101.9, "close": 102.5, "volume": 70}]
fv += [{"ts": ts(len(fv)), "open": 102.5, "high": 103.0, "low": 102.0, "close": 102.9, "volume": 70}]
fv += [{"ts": ts(len(fv)), "open": 102.9, "high": 103.3, "low": 102.3, "close": 103.0, "volume": 70}]
assert "fvg_retest" in kinds(S.tags_for(fv, "LONG", now_ts=NOW)), kinds(S.tags_for(fv, "LONG", now_ts=NOW))
# закриття під OB → breaker (flip у протилежний бік), а не ob
brk = ob_base + [{"ts": ts(len(ob_base)), "open": 105.4, "high": 105.5, "low": 99.0, "close": 99.3, "volume": 150}]
rows_b = S._rows(brk, NOW)
bo = [o for o in S.order_blocks(rows_b, atr(rows_b)) if o["idx"] == obs[-1]["idx"]]
assert bo and bo[0]["kind"] == "breaker" and bo[0]["side"] == "SHORT", bo

# ---- premium/discount і OTE (діапазон 100–110)
r = {"high": 110.0, "low": 100.0, "mid": 105.0}
z = S.zone_of(103.5, r, "LONG")
assert z["zone"] == "DISCOUNT" and z["ote"] is True, z
assert S.zone_of(108.0, r, "LONG")["ote"] is False and S.zone_of(106.5, r, "SHORT")["ote"] is True

# ---- Вайкоф: діапазон 100–104 після падіння; spring (обсяг ×1,5) і тест на меншому обсязі
prior = walk([118, 104], [20], vol=100)
rangebars = []
for i in range(20):
    lo, hi = (100.0, 101.0) if i % 5 == 0 else ((103.0, 104.0) if i % 5 == 2 else (101.5, 102.5))
    rangebars.append({"open": 102.5, "high": hi, "low": lo, "close": (lo + hi) / 2, "volume": 100})
tail = [
    {"open": 102.0, "high": 102.5, "low": 101.5, "close": 102.0, "volume": 90},
    {"open": 102.0, "high": 102.5, "low": 101.4, "close": 101.8, "volume": 90},
    {"open": 101.8, "high": 102.0, "low": 98.5, "close": 101.2, "volume": 150},     # spring: тінь під 100, закриття всередині
    {"open": 101.2, "high": 102.4, "low": 100.9, "close": 102.0, "volume": 80},
    {"open": 102.0, "high": 102.6, "low": 98.8, "close": 102.3, "volume": 60},      # тест: біля екстремуму, обсяг ≤0,8×, екстремум не оновлено
    {"open": 102.3, "high": 103.0, "low": 101.8, "close": 102.9, "volume": 70},
    {"open": 102.9, "high": 103.4, "low": 102.4, "close": 103.2, "volume": 70},
    {"open": 103.2, "high": 103.6, "low": 102.8, "close": 103.4, "volume": 70},
]
wy = prior[:-1] + [dict(x) for x in prior[-1:]]
allrows = wy + rangebars + tail
for i, r_ in enumerate(allrows):
    r_["ts"] = ts(i)
ev = W.events(allrows, NOW)
assert ev["range"] and abs(ev["range"]["low"] - 100.0) < 0.2, ev["range"]
assert [e["kind"] for e in ev["events"]] == ["spring"] and ev["events"][0]["tested"] and ev["events"][0]["volume_ratio"] == 1.5, ev["events"]
assert ev["phase"].startswith("накопичення"), ev["phase"]
assert kinds(W.tags_for(allrows, "LONG", NOW)) == ["spring", "spring_test"] and W.tags_for(allrows, "SHORT", NOW) == []
# без обсягу spring не рахуємо; діапазон пробито закриттям — події немає; без діапазону — «фаза не визначена»
novol = [{**r_, "volume": 0} for r_ in allrows]
assert W.tags_for(novol, "LONG", NOW) == []
assert W.events(walk([100, 110], [40]), NOW)["phase"] == "фаза не визначена"
# upthrust дзеркально
mir = []
for r_ in allrows:
    mir.append({**r_, "open": 204 - r_["open"], "high": 204 - r_["low"], "low": 204 - r_["high"], "close": 204 - r_["close"]})
evm = W.events(mir, NOW)
assert [e["kind"] for e in evm["events"]] == ["upthrust"] and evm["events"][0]["tested"] and evm["phase"].startswith("розподіл"), evm
print("OK SMC+Wyckoff: pools/sweep, BOS/CHoCH, displacement, FVG, OB→breaker, OTE; range, spring/upthrust with volume, test, phase only when proven")

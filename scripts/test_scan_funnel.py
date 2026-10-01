#!/usr/bin/env python3
"""Воронка скану: ротація всього universe, окремі квоти Gainers/Losers, PULLBACK WATCH, T0-SKIP не губиться, напрям після сильного руху."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ["OFFICE_EXINFO_SEED"] = "1"
import office_scan_funnel as F  # noqa: E402
from office_market_scout import screen_futures_market  # noqa: E402

NOW = 1_800_000_000.0


def tick(sym, price, ch, vol=50e6, hi=None, lo=None):
    hi = hi if hi is not None else price * 1.01
    lo = lo if lo is not None else price * 0.99
    return {"symbol": sym, "lastPrice": str(price), "priceChangePercent": str(ch), "quoteVolume": str(vol), "highPrice": str(hi), "lowPrice": str(lo)}


# universe: 288 монет, більшість майже статичні; 6 сильних Gainers, 6 сильних Losers
tickers = [tick(f"C{i:03d}USDT", 1.0 + i / 100, (i % 7 - 3) * 0.2, vol=5e6 + i * 1e5) for i in range(270)]
tickers += [tick("BTCUSDT", 60000, 0.5, 5e9), tick("ETHUSDT", 3000, 0.4, 3e9)]
tickers += [tick(f"G{i}USDT", 2.0, 5.5 + i, 30e6, hi=2.2, lo=1.8) for i in range(8)]       # 5,5% … 12,5%
tickers += [tick(f"L{i}USDT", 2.0, -(5.5 + i), 30e6, hi=2.2, lo=1.8) for i in range(8)]
scr = screen_futures_market(tickers)
assert scr.screened >= 280, scr.screened
uni = scr.screened

# --- 1) ротація: за кілька циклів ВЕСЬ universe проходить глибокий аналіз, не лише ~24 монети
st = F.FunnelState()
seen = set()
cycles = 0
t = NOW
while cycles < 40:
    for r in scr.rows:
        if abs(r["change_pct"]) >= F.EXTENDED_PCT:
            F.register_pullback(r["symbol"], r, reason="x", now=t, state=st)
    F.update_pullbacks(scr.rows, t, st)
    ch = F.select_deep(scr.rows, scr.gainers, scr.losers, now=t, state=st)
    assert len(ch) <= F.CAP and len({c["symbol"] for c in ch}) == len(ch)
    for c in ch:
        F.mark_deep(c["symbol"], t, st)
        seen.add(c["symbol"])
    cycles += 1
    t += 600
    if len(seen) >= uni - len(st.pullbacks):
        break
assert cycles <= 40 and len(seen) >= uni - len(st.pullbacks), (cycles, len(seen), uni)
assert F.coverage(uni, t, st)["deep_distinct"] >= 0.9 * uni - len(st.pullbacks)
rot = [c for c in ch if c["tier"] == "rotation"]
assert len(rot) >= F.ROTATE_MIN, "ротація має зарезервовані місця і не витісняється"

# --- 2) Gainers і Losers — ОКРЕМІ квоти: ріст не витісняє падіння
st = F.FunnelState()
ch = F.select_deep(scr.rows, scr.gainers, scr.losers, now=NOW, state=st)
tiers = {}
for c in ch:
    tiers.setdefault(c["tier"], []).append(c["symbol"])
assert len(tiers.get("gainers", [])) == F.Q_GAINERS and len(tiers.get("losers", [])) == F.Q_LOSERS, tiers
assert all(s.startswith("G") for s in tiers["gainers"]) and all(s.startswith("L") for s in tiers["losers"])
# навіть якщо Gainers рухаються сильніше за всі Losers
tk2 = [tick(f"G{i}USDT", 2.0, 9.0 + i, 30e6) for i in range(8)] + [tick(f"L{i}USDT", 2.0, -5.1 - i * 0.1, 30e6) for i in range(8)]
s2 = screen_futures_market(tk2 + tickers[:50])
ch2 = F.select_deep(s2.rows, s2.gainers, s2.losers, now=NOW, state=F.FunnelState())
assert sum(1 for c in ch2 if c["tier"] == "losers") == F.Q_LOSERS

# --- 3) сильний рух ≥10% → PULLBACK WATCH, не займає слот звичайного кандидата
st = F.FunnelState()
for r in scr.rows:
    if abs(r["change_pct"]) >= F.EXTENDED_PCT:
        F.register_pullback(r["symbol"], r, reason="x", now=NOW, state=st)
assert set(st.pullbacks) == {"G5USDT", "G6USDT", "G7USDT", "L5USDT", "L6USDT", "L7USDT"}, set(st.pullbacks)
ext_rows = [{**r, "price": r["high"] * 0.999} if r["symbol"].startswith("G") else ({**r, "price": r["low"] * 1.001} if r["symbol"].startswith("L") else r) for r in scr.rows]
F.update_pullbacks(ext_rows, NOW, st)
assert all(e["status"] == "EXTENDED" for e in st.pullbacks.values())
ch = F.select_deep(scr.rows, scr.gainers, scr.losers, now=NOW, state=st)
picked = {c["symbol"] for c in ch}
assert not (picked & set(st.pullbacks)), "перегріті не займають слотів, поки немає відкату"
assert F.counts_report(ch, st)["pullback_watch_total"] == 6

# --- 4) відкат сформувався → монета «до перевірки»; T0-SKIP не губиться (стан живе, поки рух не зійшов/не протух)
pb = {**tick("G7USDT", 2.0, 12.5, 30e6, hi=2.4, lo=1.8)}      # ріст був до 2,4; зараз 2,0 → відкат 67% від діапазону
rows_pb = [r for r in screen_futures_market([pb]).rows]
st2 = F.FunnelState()
F.register_pullback("G7USDT", {**rows_pb[0], "high": 2.4, "low": 1.8}, reason="T0/ATR", now=NOW, t0_blocked=True, state=st2)
rows_pb[0]["price"] = 2.0
c = F.update_pullbacks(rows_pb, NOW + 60, st2)
e = st2.pullbacks["G7USDT"]
assert e["status"] == "PULLBACK" and 0.3 <= e["retrace"] <= 0.8 and e["t0_blocked"], e
assert F.due_pullbacks(NOW + 60, st2) == ["G7USDT"]
ch = F.select_deep(screen_futures_market(tickers).rows, [], [], now=NOW + 60, state=st2)
assert any(x["symbol"] == "G7USDT" and x["tier"] == "pullback" for x in ch)
F.mark_checked("G7USDT", NOW + 60, st2)
assert F.due_pullbacks(NOW + 120, st2) == [], "не частіше за RECHECK_SEC"
assert F.due_pullbacks(NOW + 60 + F.RECHECK_SEC + 1, st2) == ["G7USDT"]
# ще на екстремумі — відкату нема
rows_pb[0]["price"] = 2.39
F.update_pullbacks(rows_pb, NOW + 90, st2)
assert st2.pullbacks["G7USDT"]["status"] == "EXTENDED" and F.due_pullbacks(NOW + 90 + F.RECHECK_SEC, st2) == []
# віддано майже весь рух
rows_pb[0]["price"] = 1.85
F.update_pullbacks(rows_pb, NOW + 95, st2)
assert st2.pullbacks["G7USDT"]["status"] == "REVERSAL_ZONE"
# TTL і «рух зійшов нанівець»
F.update_pullbacks(rows_pb, NOW + F.TTL_SEC + 10, st2)
assert "G7USDT" not in st2.pullbacks

# --- 5) напрям після сильного руху
assert F.direction_gate("LONG", "UP", reversal_ok=False)[0]            # після росту LONG на відкаті — можна
ok, why = F.direction_gate("SHORT", "UP", reversal_ok=False)
assert not ok and "CHoCH" in why                                        # SHORT без підтвердженого розвороту — ні
assert F.direction_gate("SHORT", "UP", reversal_ok=True)[0]
assert F.direction_gate("SHORT", "DOWN", reversal_ok=False)[0]          # після падіння SHORT за трендом — можна
assert not F.direction_gate("LONG", "DOWN", reversal_ok=False)[0] and F.direction_gate("LONG", "DOWN", reversal_ok=True)[0]
assert F.direction_gate("SHORT", None, reversal_ok=False)[0]            # без сильного руху обмежень немає


def bars(closes):
    return [{"ts": f"2026-10-01T{i // 60:02d}:{i % 60:02d}:00+00:00", "open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1} for i, c in enumerate(closes)]


up = [100 + i * 0.4 for i in range(60)]
assert F.reversal_confirmed(bars(up), "UP") is False                    # лише ріст — розвороту немає
assert F.reversal_confirmed([], "UP") is False

# --- 6) реєстр переживає перезапуск (БД)
import office_bridge as B  # noqa: E402

db = os.path.join(tempfile.mkdtemp(), "t.db")
B.init_office_db(db)
st3 = F.FunnelState()
F.register_pullback("G7USDT", {**rows_pb[0], "high": 2.4, "low": 1.8, "change_pct": 12.5}, reason="T0/ATR", now=NOW, t0_blocked=True, state=st3)
F.mark_deep("BTCUSDT", NOW, st3)
F.persist(db, st3, now=NOW)
st4 = F.FunnelState()
assert F.hydrate(db, st4, now=NOW + 60) == 1 and st4.pullbacks["G7USDT"]["t0_blocked"] and "BTCUSDT" in st4.last_deep
assert F.hydrate(db, F.FunnelState(), now=NOW + F.TTL_SEC + 5) == 0

print("OK scan funnel: ротація всього universe, окремі Gainers/Losers, PULLBACK WATCH, T0-стан зберігається, напрям після сильного руху")

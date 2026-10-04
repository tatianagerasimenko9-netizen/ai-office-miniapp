#!/usr/bin/env python3
"""Оптимізація signal_track.tick/check_false_expiry: пропуск проходу, коли не закрилась нова 15m-свічка, НЕ змінює результати (еквівалентність з базовою поведінкою),
а кількість запитів свічок падає. Тест на «0 порівнянь» падає: порівняння мають відбутись."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_signal_track as trk  # noqa: E402
from office_bridge import init_office_db, log_event  # noqa: E402

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc).timestamp()
FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


def price(sym_i, k):
    """Детермінований шлях ціни по 15m-барах k (високі/низькі діапазони різні для кожного символу)."""
    base = 100.0 + sym_i
    drift = (k - 8) * 0.12 * (1 if sym_i % 2 == 0 else -1)
    return base + drift


def candles_upto(sym_i, now):
    out = []
    k = 0
    while T0 + 900 * k <= now:
        o = price(sym_i, k)
        c = price(sym_i, k + 1)
        out.append({"ts": datetime.fromtimestamp(T0 + 900 * k, tz=timezone.utc).isoformat(), "open": o, "close": c, "high": max(o, c) + 0.3, "low": min(o, c) - 0.3})
        k += 1
    return out


def make_db():
    db = str(Path(tempfile.mkdtemp()) / "t.db")
    init_office_db(db)
    for i in range(6):
        sym = f"S{i}USDT"
        direction = "LONG" if i % 2 == 0 else "SHORT"
        e = 100.0 + i
        sl = e - 1.0 if direction == "LONG" else e + 1.0
        tp1 = e + 1.5 if direction == "LONG" else e - 1.5
        trk.record_plan(db, scenario_id=f"SCN|{sym}|{direction}|H1|x{i}", symbol=sym, direction=direction, tf="H1", entry=e, sl=sl, tp1=tp1, tp3=tp1 + (1 if direction == "LONG" else -1),
                        confirmed_ts=T0 + 900 * 3, valid_until_ts=T0 + 900 * 3 + 86400, confirm_msg_id=100 + i)
    # одне зняття за часом для check_false_expiry
    log_event(db, trk.EV_EXPIRY, {"scenario_id": "SCN|S1USDT|SHORT|H1|exp", "symbol": "S1USDT", "direction": "SHORT", "expired_ts": T0 + 900 * 4, "zone_lo": 100.5, "zone_hi": 101.5,
                                  "sl": 103.0, "tp1": 98.0}, "SCN|S1USDT|SHORT|H1|exp")
    return db


def run(use_memo):
    db = make_db()
    calls = {"n": 0}
    written = []
    now = T0 + 900 * 5 + 120
    end = T0 + 900 * 400
    while now < end:
        if not use_memo:
            trk._BAR_MEMO.clear()

        def fetch(sym, tf, n=300, _now=now):
            calls["n"] += 1
            return candles_upto(int(sym[1]), _now)
        for r in trk.tick(db, fetch=fetch, now_ts=now):
            written.append(("tick", r["scenario_id"], r["outcome"], r["mfe_pct"], r["mae_pct"], r["time_to_result_sec"]))
        for r in trk.check_false_expiry(db, fetch=fetch, now_ts=now):
            written.append(("false", r["scenario_id"], r["false_expiry"], r["after_expiry_outcome"]))
        now += 600   # як цикл relay: раз на 10 хв
    return written, calls["n"]


trk._BAR_MEMO.clear()
base, n_base = run(False)
trk._BAR_MEMO.clear()
opt, n_opt = run(True)
check(len(base) >= 6, f"порівняння відбулись (базових записів {len(base)}): інакше це «0 порівнянь», а не PASS")
check(sorted(map(str, base)) == sorted(map(str, opt)), f"результати ідентичні: base={sorted(map(str, base))[:3]} opt={sorted(map(str, opt))[:3]}")
check(n_opt < n_base, f"запитів свічок стало менше: {n_opt} < {n_base}")
check(n_opt <= n_base * 0.8, f"економія не менш ніж 20% при кроці 10 хв і барі 15 хв: {n_opt}/{n_base}")
# затримка даних: якщо вибірка не містить останньої закритої свічки, бар не запамʼятовується і наступний прохід повторює запит
trk._BAR_MEMO.clear()
db = make_db()
now = T0 + 900 * 20 + 60
stale = lambda sym, tf, n=300: candles_upto(int(sym[1]), now - 1800)  # noqa: E731
trk.tick(db, fetch=stale, now_ts=now)
check(not trk._BAR_MEMO, "застарілі дані не блокують наступний прохід")
print(f"запитів: база {n_base} → з пропуском {n_opt} ({(1 - n_opt / n_base) * 100:.0f}% менше); записів результатів: {len(base)}")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)

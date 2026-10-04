#!/usr/bin/env python3
"""READY лише на свічках Binance USDT-M Futures: запасне джерело (спот Vision, Bybit) виявляється й не дозволяє видати READY."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
import office_ready_core as rc  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


fut = [{"close": 1, "src": "binance_futures"}] * 5
spot = [{"close": 1, "src": "binance_futures"}] * 4 + [{"close": 1, "src": "binance_spot_vision"}]
nosrc = [{"close": 1}] * 5   # WS-потік без позначки: не вважається запасним
check(rc.non_futures_sources(fut, fut) == [], "тільки Futures → порожньо")
check(rc.non_futures_sources(fut, spot) == ["binance_spot_vision"], "спот серед M15-свічок виявлено")
check(rc.non_futures_sources(spot, [{"src": "bybit_linear"}]) == ["binance_spot_vision", "bybit_linear"], "обидва запасні джерела")
check(rc.non_futures_sources(nosrc, {}, None) == [], "без позначки / порожньо / не список — не запасне")
src = Path(rc.__file__).resolve().parent.joinpath("office_relay_wizard.py").read_text()
i = src.index("non_futures_sources(ltf, _m15)")
j = src.index("_tp2_m, _tp3_m = _rc.message_targets", i)
check("continue" in src[i:j] and "READY_HELD_NON_FUTURES" in src[i:j], "у relay: не Futures → continue до розрахунку й відправки (сценарій лишається в очікуванні)")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)

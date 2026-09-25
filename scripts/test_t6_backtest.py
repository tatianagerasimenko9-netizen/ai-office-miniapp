#!/usr/bin/env python3
"""Офлайн T6 backtest: файл OHLCV, без look-ahead, без генерації свічок."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_radar import evaluate_radar  # noqa: E402
from office_t6_backtest import (  # noqa: E402
    BacktestDataError,
    closed_asof,
    close_time,
    load_ohlcv_file,
    run_t6_backtest,
    simulate_exit_on_bar,
)
from office_btc_liquidations import CREATES_ENTER  # noqa: E402
from office_radar import RADAR_SYMBOLS  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if RADAR_SYMBOLS != ("BTCUSDT",):
        return _fail("T6 radar symbols unchanged")
    if CREATES_ENTER:
        return _fail("T7 must stay no ENTER")
    missing = Path(tempfile.mkdtemp()) / "nope.json"
    try:
        load_ohlcv_file(missing)
        return _fail("missing file must stop")
    except BacktestDataError as exc:
        if "не генеру" not in str(exc) and "немає файлу" not in str(exc):
            return _fail(f"missing msg {exc}")

    ctrl = ROOT / "fixtures" / "t6_backtest_control.json"
    data = load_ohlcv_file(ctrl)
    asof = datetime(2026, 1, 15, 13, 15, tzinfo=timezone.utc)
    m15 = closed_asof(data["timeframes"]["15m"], "15m", asof)
    if any(float(c["close"]) >= 199 for c in m15):
        return _fail("look-ahead 15m")
    d1 = closed_asof(data["timeframes"]["1d"], "1d", asof)
    if any(str(c["ts"]).startswith("2026-01-15") for c in d1):
        return _fail("look-ahead daily Jan 15 still open")

    unordered = {
        "symbol": "BTCUSDT",
        "source": "bad",
        "timeframes": {
            "1d": data["timeframes"]["1d"],
            "1h": data["timeframes"]["1h"],
            "15m": list(reversed(data["timeframes"]["15m"][:5])),
        },
    }
    badp = Path(tempfile.mkdtemp()) / "bad.json"
    badp.write_text(json.dumps(unordered), encoding="utf-8")
    try:
        load_ohlcv_file(badp)
        return _fail("must reject non-chrono")
    except BacktestDataError:
        pass

    if simulate_exit_on_bar(side="SHORT", sl=108.3, tp=104.8, high=109.0, low=103.0) != "SL_CONSERVATIVE":
        return _fail("same-bar SL+TP must be conservative SL")

    bar = [c for c in data["timeframes"]["15m"] if str(c["ts"]).startswith("2026-01-15T13:00")][0]
    asof2 = close_time(bar, "15m")
    res = evaluate_radar(
        symbol="BTCUSDT",
        price=float(bar["close"]),
        daily_candles=closed_asof(data["timeframes"]["1d"], "1d", asof2),
        sweep_candles=closed_asof(data["timeframes"]["1h"], "1h", asof2),
        m15_candles=closed_asof(data["timeframes"]["15m"], "15m", asof2),
        day_used_pct=11.0,
        utc_now=asof2,
    )
    if res.status != "SIGNAL":
        return _fail(f"control should SIGNAL via evaluate_radar {res.status} {res.reason}")
    if res.opens_position:
        return _fail("radar still must not open position")

    rep = run_t6_backtest(ctrl)
    d = rep.as_dict()
    if "не прогноз" not in d["disclaimer"]:
        return _fail("disclaimer")
    if d["confirmed_setups"] < 1:
        return _fail("need confirmed setup on control")
    if d["watching"] < 1:
        return _fail("need WATCHING counts")
    if d["skip"] < 1:
        return _fail("need SKIP counts")
    if "SKIP_NO_M15" not in d["reject_reasons"] and "SKIP_NONE" not in d["reject_reasons"]:
        return _fail("need skip reasons")
    if d["trades"] < 1:
        return _fail("control trade")
    if d["wr_pct"] == "немає даних":
        return _fail("closed trades should have WR")
    if not any(t.conservative_sl_tp for t in rep.trades):
        return _fail("control fill bar hits SL+TP")
    empty = Path(tempfile.mkdtemp()) / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    try:
        run_t6_backtest(empty)
        return _fail("empty json must stop")
    except BacktestDataError:
        pass
    print("OK t6 backtest offline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Real MANTA OHLCV replay of WATCHING-zone safety gates, NOT a strategy PnL test.

Zones are previous CLOSED H1 candle ranges, solely to exercise the gate on
actual price observations. No fabricated candles, no Telegram, no orders.
"""
import argparse
import json
from datetime import timedelta
from office_t6_backtest import load_ohlcv_file, parse_ts, day_used_pct_offline
from office_zone_alert import plan_watching_zone_hit, zone_reached_to_telegram
from office_alert_gate import text_grants_entry


def replay(path):
    data = load_ohlcv_file(path)
    if data["symbol"] != "MANTAUSDT":
        raise ValueError("MANTA replay requires MANTAUSDT historical candles")
    h1 = data["timeframes"]["1h"]
    d1 = data["timeframes"]["1d"]
    m15 = data["timeframes"]["15m"]
    hi = di = 0
    checks = hits = atr_blocked = 0
    for candle in m15:
        asof = parse_ts(candle["ts"]) + timedelta(minutes=15)
        while hi < len(h1) and parse_ts(h1[hi]["ts"]) + timedelta(hours=1) <= asof:
            hi += 1
        while di < len(d1) and parse_ts(d1[di]["ts"]) + timedelta(days=1) <= asof:
            di += 1
        if hi < 1:
            continue
        previous = h1[hi - 1]
        day_used = day_used_pct_offline(d1[:di])
        plan = plan_watching_zone_hit(
            current_price=candle["close"], entry_low=previous["low"],
            entry_high=previous["high"], day_used_pct=day_used,
            sl=None, tp1=None, symbol="MANTAUSDT",
        )
        checks += 1
        if plan.in_zone:
            hits += 1
            atr_blocked += bool(plan.entry_blocked and day_used is not None and day_used > 90)
            if plan.promote_active or zone_reached_to_telegram(plan) or text_grants_entry(plan.message):
                raise AssertionError("WATCHING zone granted entry on real MANTA candles")
            if not plan.entry_blocked:
                raise AssertionError("incomplete SL/TP must block MANTA entry")
    if checks < 100 or hits < 1:
        raise AssertionError("insufficient real MANTA observations")
    return {"symbol":"MANTAUSDT","scope":"WATCHING safety gate only, not Lev strategy or PnL",
            "real_m15_checks":checks,"zone_hits":hits,"atr_blocked_hits":atr_blocked,
            "unauthorized_entries":0}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    print("REAL_MANTA_GATE", json.dumps(replay(ap.parse_args().file), ensure_ascii=False))

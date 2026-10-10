#!/usr/bin/env python3
"""Ізольований replay на РЕАЛЬНИХ свічках Binance Futures (data.binance.vision): Brain v2.1 vs SMC на закритих барах (без майбутнього) + контрфактуальні правила.
Використання: python scripts/learning_binance_replay.py <SYMBOL> <END_DATE YYYY-MM-DD> <DAYS> <OUT.json>
Рішення приймаються на барах у (END−DAYS, END 00:00Z]; результати рахуються по наступних барах (до +2 діб даних). Нічого не пише в БД і не торкається production."""
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import binance_vision_fetch as BV  # noqa: E402
from office2.learning import counterfactual as CF  # noqa: E402
from office2.smc import replay as RP  # noqa: E402


def main(sym, end, days, out):
    end_day = date.fromisoformat(end)
    t_to = float(datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc).timestamp())
    t_from = t_to - days * 86400
    arrs = BV.build_arrays(sym, end_day, days)
    if not arrs:
        Path(out).write_text(json.dumps({"symbol": sym, "error": "немає даних в архіві"}))
        print("немає даних", sym)
        return
    btc = arrs["m15"] if sym == "BTCUSDT" else BV.fetch("BTCUSDT", "15m", end_day.fromordinal(end_day.toordinal() - days - 55), end_day.fromordinal(end_day.toordinal() + 2))
    q = arrs.pop("quality")
    print("[replay] старт", sym, q, flush=True)
    t0 = time.time()
    run = RP.replay_arrays(sym, arrs, t_from, t_to, btc=btc, outcome_end=None)
    rows = CF.per_event(run["events"], arrs["m15"])
    run["elapsed_total_s"] = round(time.time() - t0, 1)
    Path(out).write_text(json.dumps({"symbol": sym, "window": [t_from, t_to], "data_quality": q, "run": run, "counterfactual_rows": rows}, ensure_ascii=False, default=float))
    print(sym, "bars", run["bars"], "events", len(run["events"]), "elapsed", run["elapsed_total_s"], "s", q)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4])

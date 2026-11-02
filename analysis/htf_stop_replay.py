"""B2: read-only HTF structural-stop and stop-hunt replay (HYPOTHESIS).

Inputs:
  PSV files: docs/handoff/br-profitability/data/br_plans_*.psv
  OHLC CSV: --candles-dir/{SYMBOL}/1m.csv and 1h.csv, 4h.csv, 1d.csv
  CSV columns: open_time (UTC unix seconds), open, high, low, close.
No future HTF candles allowed. Does not import or modify LIVE.
"""
import argparse
import csv
import glob
import json
from bisect import bisect_left
from pathlib import Path

OFFSET = 1790000000


def load_bars(path):
    with open(path, newline="", encoding="utf8") as fh:
        records = list(csv.DictReader(fh))
    return [
        dict(t=int(r["open_time"]), o=float(r["open"]), h=float(r["high"]),
             l=float(r["low"]), c=float(r["close"]))
        for r in records
    ]


def confirmed_swings(bars, asof, timeframe_seconds, k=2):
    """Only bars closed by asof, with k completed confirming bars."""
    closed = [b for b in bars if b["t"] + timeframe_seconds <= asof]
    return [(i, closed[i]) for i in range(k, len(closed) - k)
            if all(closed[i]["l"] < closed[j]["l"] for j in range(i-k, i+k+1) if j != i)
            or all(closed[i]["h"] > closed[j]["h"] for j in range(i-k, i+k+1) if j != i)]


def structural_stop(bars, asof, tf_seconds, direction, current_sl, buffer_frac=0.0, k=2):
    """For LONG: nearest swing low below SL; SHORT: nearest swing high above SL.

    buffer_frac is an experimental proportion of current entry-stop distance
    supplied by caller. Candidate is undefined if no confirmed swing exists.
    """
    swings = confirmed_swings(bars, asof, tf_seconds, k=k)
    if direction == "L":
        prices = [b["l"] for _, b in swings if b["l"] < current_sl]
        return max(prices) if prices else None
    prices = [b["h"] for _, b in swings if b["h"] > current_sl]
    return min(prices) if prices else None


def follow(bars, entry_ts, direction, entry, stop, target, horizon_seconds=48*3600):
    """Bar high/low path; SL wins same-minute ties, including entry candle."""
    sign = 1 if direction == "L" else -1
    started = False
    entry_at = None
    stop_at = None
    target_at = None
    for b in bars:
        if b["t"] < entry_ts or b["t"] > entry_ts + horizon_seconds:
            continue
        if not started:
            if not b["l"] <= entry <= b["h"]:
                continue
            started, entry_at = True, b["t"]
        hit_stop = b["l"] <= stop if sign == 1 else b["h"] >= stop
        hit_target = b["h"] >= target if sign == 1 else b["l"] <= target
        if hit_stop:
            stop_at = b["t"]
            break
        if hit_target:
            target_at = b["t"]
            break
    return {"entry_at": entry_at, "stop_at": stop_at, "target_at": target_at}


def stop_hunt(bars, stop_at, direction, target, horizon_seconds):
    """Observe post-stop price path, never treat as realized trade profit."""
    if stop_at is None:
        return None
    for b in bars:
        if stop_at < b["t"] <= stop_at + horizon_seconds:
            if (b["h"] >= target) if direction == "L" else (b["l"] <= target):
                return True
    return False


def read_plans(pattern):
    for path in sorted(glob.glob(pattern)):
        for line in Path(path).read_text().splitlines():
            p = line.split("|")
            if len(p) < 8 or not p[0].isdigit():
                continue
            yield dict(seq=p[0], symbol=p[1]+"USDT", direction=p[2],
                       ts=int(p[3]), entry=float(p[4]), sl=float(p[5]),
                       tp1=float(p[6].split(",")[0].split(":")[0]),
                       events=[(a.split("@")[0], int(a.split("@")[1])+OFFSET)
                               for a in p[7].split(",") if "@" in a])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", required=True, help="glob to exported PSV chunks")
    ap.add_argument("--candles-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--buffer-ratios", default="0,0.1,0.2",
                    help="HYPOTHESIS grid, fraction of current stop distance")
    ap.add_argument("--stop-hunt-hours", type=int, default=24, help="HYPOTHESIS look-ahead window after stop")
    a = ap.parse_args()
    ratios = [float(x) for x in a.buffer_ratios.split(",")]
    data = []
    cache = {}
    for p in read_plans(a.plans):
        sym = p["symbol"]
        try:
            if sym not in cache:
                root = Path(a.candles_dir) / sym
                cache[sym] = {tf: load_bars(root / (tf+".csv")) for tf in ("1m","1h","4h","1d")}
            bars = cache[sym]
        except FileNotFoundError:
            data.append({"seq":p["seq"],"status":"MISSING_CANDLES"})
            continue
        current = follow(bars["1m"], p["ts"], p["direction"], p["entry"],p["sl"],p["tp1"])
        if current["entry_at"] is None:
            data.append({"seq":p["seq"],"status":"NO_ENTRY_IN_CANDLES"})
            continue
        event_names = {e[0] for e in p["events"]}
        if "AMB" in event_names:
            # Conservative bars still evaluate it, but keep exchange/order ambiguity visible.
            audit_status = "AMBIGUOUS_DB"
        else:
            audit_status = "RECONCILE"
        risk = abs(p["entry"]-p["sl"])
        current_r = (abs(p["tp1"]-p["entry"])/risk
                     if current["target_at"] is not None else -1) - .0015*p["entry"]/risk
        result = {"seq":p["seq"], "symbol":sym, "direction":p["direction"],
                  "ts":p["ts"],"status":audit_status,"original":current,
                  "original_net_r":current_r,
                  "stop_hunt":stop_hunt(bars["1m"], current["stop_at"], p["direction"],p["tp1"],a.stop_hunt_hours*3600),
                  "variants":[]}
        for tf,seconds in (("1h",3600),("4h",14400),("1d",86400)):
            swing = structural_stop(bars[tf],p["ts"],seconds,p["direction"],p["sl"])
            if swing is None:
                continue
            for factor in ratios:
                proposed = (swing - factor*risk if p["direction"]=="L" else swing + factor*risk)
                if abs(p["entry"]-proposed)<=0:
                    continue
                alternative = follow(bars["1m"],p["ts"],p["direction"],p["entry"],proposed,p["tp1"])
                alternative_risk = abs(p["entry"]-proposed)
                net = ((abs(p["tp1"]-p["entry"])/alternative_risk)
                       if alternative["target_at"] is not None else -1) - .0015*p["entry"]/alternative_risk
                result["variants"].append({"timeframe":tf,"buffer_ratio":factor,
                                           "sl_htf_price":proposed,
                                           "net_r":net,"path":alternative})
        data.append(result)
    out=Path(a.out);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"model":"HYPOTHESIS","rows":data},ensure_ascii=False,indent=2))
    print(json.dumps({"plans":len(data),"with_candles":sum("original" in r for r in data),
                      "stop_hunts":sum(r.get("stop_hunt") is True for r in data),
                      "note":"No CI until clustered aggregation and independent holdout"}))


if __name__ == "__main__":
    main()

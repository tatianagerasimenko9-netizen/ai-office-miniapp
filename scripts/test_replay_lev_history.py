#!/usr/bin/env python3
"""Replay harness self-test on SYNTHETIC candles (pipeline check only - never a result).

Checks: determinism, no look-ahead (full data with `until=T` == data cut at T),
H4 aggregation uses closed H1 only, forming-day rebuild, Wilson interval,
regime validation section present, report has provenance. Offline, no network.
"""
import json
import math
import random
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay_lev_history as rp  # noqa: E402
from office_t6_backtest import parse_ts  # noqa: E402


def synth(days=45, seed=7):
    rnd = random.Random(seed)
    start = datetime(2026, 5, 1, tzinfo=timezone.utc)
    px, m15 = 100.0, []
    for i in range(days * 96):
        drift = 0.0006 * math.sin(i / 300.0)
        o = px
        c = o * (1 + drift + rnd.gauss(0, 0.0035))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.0015)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.0015)))
        m15.append({"ts": (start + timedelta(minutes=15 * i)).isoformat(), "open": o, "high": h, "low": l,
                    "close": c, "volume": 100.0})
        px = c

    def agg(n):
        out = []
        for k in range(0, len(m15) - n + 1, n):
            g = m15[k:k + n]
            out.append({"ts": g[0]["ts"], "open": g[0]["open"], "close": g[-1]["close"],
                        "high": max(x["high"] for x in g), "low": min(x["low"] for x in g), "volume": 100.0 * n})
        return out
    return {"symbol": "SYNTHUSDT", "months": ["2026-05", "2026-06"],
            "timeframes": {"15m": m15, "1h": agg(4), "1d": agg(96)}}


def cut(data, until):
    out = {**data, "timeframes": {}}
    for tf, sec in (("15m", 900), ("1h", 3600), ("1d", 86400)):
        out["timeframes"][tf] = [c for c in data["timeframes"][tf]
                                 if parse_ts(c["ts"]) + timedelta(seconds=sec) <= until]
    return out


def write(d):
    f = Path(tempfile.mkdtemp()) / "x.json"
    f.write_text(json.dumps(d), encoding="utf-8")
    return f


data = synth()
eval_from = datetime(2026, 6, 1, tzinfo=timezone.utc)
full = write(data)
r1 = rp.replay_file(full, stride=4, eval_from=eval_from)
r2 = rp.replay_file(full, stride=4, eval_from=eval_from)
assert r1 == r2, "replay must be deterministic"
assert r1["decisions"] > 100 and sum(r1["actions"].values()) == r1["decisions"], r1["actions"]
assert "by_regime" in r1["regime_validation"] and r1["regime_validation"]["by_regime"], "regime validation empty"
assert r1["input_sha256"]
for m in ("model_a_next_open_immediate", "model_b_zone_limit_no_ltf_confirm"):
    tr = r1[m]["trades"]
    assert tr["n"] == tr["wins"] + tr["losses"], m
assert sum(r1["model_b_zone_limit_no_ltf_confirm"]["scenario_fates"].values()) >= 1
assert r1["send_decisions"] == r1["actions"].get("SEND", 0)
g = r1["send_geometry"]
assert g["n"] == r1["send_decisions"] and g["median_stop_pct"] > 0 and g["median_tp1_pct"] > 0
assert 0 <= g["share_tp1_below_rule"] <= 1 and g["unique_setup_keys"] <= g["n"]

# No look-ahead: stopping the full data at T equals data that never contained the future.
T = datetime(2026, 6, 12, 6, 0, tzinfo=timezone.utc)
a = rp.replay_file(full, stride=4, eval_from=eval_from, until=T)
b = rp.replay_file(write(cut(data, T)), stride=4, eval_from=eval_from)
for k in ("decisions", "actions", "actions_by_direction", "actions_by_regime", "top_reasons",
          "send_decisions", "model_a_next_open_immediate", "model_b_zone_limit_no_ltf_confirm"):
    assert a[k] == b[k], (k, a[k], b[k])
assert a["regime_validation"]["by_regime"] == b["regime_validation"]["by_regime"], "regime labels used the future"

# H4 aggregation: only complete, closed 4-hour groups.
h1 = [{"ts": (datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(hours=i)).isoformat(),
       "open": 1, "high": 2 + i, "low": 0.5, "close": 1.5, "volume": 1} for i in range(10)]
h4 = rp.aggregate_h4(h1, parse_ts)
assert len(h4) == 2 and h4[0]["high"] == 5 and h4[1]["high"] == 9, h4  # hours 8,9 are a partial group

# Forming day = closed M15 bars since 00:00 UTC only.
m15 = data["timeframes"]["15m"]
asof = parse_ts(m15[200]["ts"]) + timedelta(minutes=15)
fd = rp.forming_day(m15[:201], asof, parse_ts)
day0 = asof.replace(hour=0, minute=0)
assert fd["ts"] == day0.isoformat() and fd["high"] == max(c["high"] for c in m15[:201] if parse_ts(c["ts"]) >= day0)

assert rp.wilson(0, 0) is None and rp.wilson(5, 10) == [23.7, 76.3], rp.wilson(5, 10)
# Fill-model unit checks on a hand-made tape (no Lev involved).
def tape(rows):
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return [{"ts": (t0 + timedelta(minutes=15 * k)).isoformat(), "open": o, "high": h, "low": l, "close": c, "volume": 1}
            for k, (o, h, l, c) in enumerate(rows)]


def ctx_for(rows):
    from office_t6_backtest import close_time, simulate_exit_on_bar
    return {"m15": tape(rows), "simulate_exit_on_bar": simulate_exit_on_bar, "atr_h1_at": lambda j: None,
            "close_time": close_time, "parse_ts": parse_ts, "symbol": "ALTUSDT"}


t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
send = {"i": 0, "asof": t0 + timedelta(minutes=15), "side": "LONG", "regime": "RANGE", "entry": 100.0, "sl": 96.0,
        "tp": 108.0, "key": "K", "ttl": timedelta(hours=4)}
# limit fills when low<=100, then TP (+8%) later -> WIN; TP on the fill bar itself is NOT credited.
rows = [(101, 101.5, 100.6, 101), (101, 101.2, 99.9, 100.5), (100.5, 109, 100.2, 108.5)]
b = rp.simulate_zone_limit([send], ctx_for(rows))
assert b["fates"] == {"FILLED": 1} and b["trades"][0]["outcome"] == "WIN", b
rows = [(101, 101.5, 100.6, 101), (101, 109, 99.9, 105), (105, 106, 104, 105)]  # TP touched only on the fill bar
b = rp.simulate_zone_limit([send], ctx_for(rows))
assert b["trades"] == [] and b["fates"] == {"FILLED_OPEN_AT_END": 1}, b
# same bar SL and TP after fill -> SL
rows = [(101, 101.5, 100.6, 101), (101, 101.2, 99.9, 100.5), (100.5, 109, 95, 100)]
b = rp.simulate_zone_limit([send], ctx_for(rows))
assert b["trades"][0]["outcome"] == "LOSS" and b["trades"][0]["conservative"] is True
# close beyond invalidation before touch -> cancelled, no trade
rows = [(101, 101.5, 100.6, 101), (101, 101.2, 100.2, 95.0), (95, 101, 94, 100)]
b = rp.simulate_zone_limit([send], ctx_for(rows))
assert b["fates"] == {"INVALIDATED_BEFORE_ENTRY": 1} and not b["trades"], b
# TTL expiry without touch
rows = [(101, 102, 100.6, 101)] * 20
b = rp.simulate_zone_limit([send], ctx_for(rows))
assert b["fates"] == {"EXPIRED": 1}, b
# duplicate key inside 24h is one scenario
rows = [(101, 102, 100.6, 101)] * 4
b = rp.simulate_zone_limit([send, {**send, "asof": send["asof"] + timedelta(hours=1)}], ctx_for(rows))
assert b["fates"].get("DUPLICATE_KEY") == 1
# Model A: fills at NEXT open (+slippage), not at the card price.
rows = [(100, 100.5, 99.5, 100), (100.2, 100.4, 99.9, 100.1), (100.1, 110, 100, 109)]
a = rp.simulate_immediate([{**send, "entry": 90.0}], ctx_for(rows))
assert a["trades"] and abs(a["trades"][0]["entry"] - 100.2 * 1.0005) < 1e-9, a

# --- what-if variants (offline, never enabled) ---
sd = {"side": "LONG", "entry": 100.0, "sl": 98.0, "pivots": {"high": [101.0, 103.5, 104.0], "low": []}}
assert rp._r_tp(1.5)(sd) == 103.0 and rp._r_tp(1.0)(sd) == 102.0 and rp._r_tp(2.0)(sd) == 104.0
assert rp._structure_tp(sd) == 103.5  # 101 is < 1R away, 103.5 is the nearest swing >= 1R
assert rp._structure_tp({**sd, "pivots": {"high": [101.0], "low": []}}) is None  # no level -> no target, not invented
ss = {"side": "SHORT", "entry": 100.0, "sl": 102.0, "pivots": {"high": [], "low": [99.0, 96.5, 90.0]}}
assert rp._structure_tp(ss) == 96.5
# pivots need k confirmed bars on each side: a peak in the last two bars is NOT a pivot yet (no look-ahead)
bars = [{"high": h, "low": h - 1} for h in (1, 2, 3, 9, 3, 2, 1, 2, 3, 10)]
assert rp._pivots(bars)["high"] == [9.0], rp._pivots(bars)
# current rules reproduce the production gate; relaxed rules only relax
assert rp._fill_checks("LONG", 100.0, 98.5, 102.5, "SOLUSDT", None) == "TP1_MIN"
assert rp._fill_checks("LONG", 100.0, 98.5, 102.5, "SOLUSDT", None, {"min_tp1": False, "min_rr": 1.5}) is None
assert rp._fill_checks("LONG", 100.0, 98.0, 101.0, "SOLUSDT", None, {"min_tp1": False, "min_rr": 1.5}) == "RR_AT_FILL"
fr = rp.frequency_report([{**send, "n_tags": 3}, {**send, "asof": send["asof"] + timedelta(hours=1), "n_tags": 1}], 10, 2.0)
assert fr["send_all"]["n"] == 2 and fr["send_unique_scenario_24h"]["n"] == 1 and fr["unique_and_confluences_ge_3"]["n"] == 1, fr
d = write(synth())
rep = rp.replay_file(d, stride=4, eval_from=None)
assert set(rep["variants_what_if"]) == {v[0] for v in rp.VARIANTS} and "send_frequency" in rep
assert rep["variants_what_if"]["V0_current"]["trades"] == rep["model_b_zone_limit_no_ltf_confirm"]["trades"], "V0 must equal the current model"

print("OK Lev replay harness: deterministic, no look-ahead, closed-only H4, forming day, Wilson CI (synthetic)")

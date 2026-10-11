#!/usr/bin/env python3
"""Тренажер: рішення на T не залежить від майбутніх свічок і не містить їх; reveal оцінює план за тими ж paper-правилами; захист від свіжого T."""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import o2live_synth as S  # noqa: E402
import test_office2_brain2 as TB  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import features as F  # noqa: E402
from office2 import trainer as TR  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  {extra}"))
    if not cond:
        FAILS.append(name)


c, seq = TB.closes_long()
rng = np.random.default_rng(7)
pre = list(100.3 + np.cumsum(rng.normal(0, 0.04, 4200)) * 0.3)
base = c[:seq["bear_in_zone"]]
fut_closes = [100.4, 100.9, 101.5, 102.2, 103.0, 103.7] + [104.0] * 20
full = S._bars_from_closes(pre + base + fut_closes)
n_cut = len(pre) + len(base)
widths = {"15m": 900, "4h": 4 * 3600, "1d": 86400, "1w": 7 * 86400, "1M": 30 * 86400}


def mk_getter(src, log=None):
    def getter(url, params):
        w = widths[params["interval"]]
        a = src if w == 900 else F.resample(src, w, offset=(F.WEEK_OFFSET if w == 7 * 86400 else 0))
        rows = []
        for i in range(len(a["t"])):
            if a["t"][i] * 1000 >= params.get("endTime", 1e18):
                break
            if a["t"][i] * 1000 < params.get("startTime", 0):
                continue
            rows.append([a["t"][i] * 1000, a["o"][i], a["h"][i], a["l"][i], a["c"][i], a["v"][i], (a["t"][i] + w) * 1000 - 1, 0, 0, a["tbv"][i]])
        if log is not None:
            log.append((params["interval"], params.get("endTime")))
        return rows[-int(params["limit"]):]
    return getter


T = float(full["t"][n_cut - 1] + 900)
orig = B.all_levels
B.all_levels = lambda ctx, now: TB.LEVELS
try:
    calls = []
    d_full = TR.decide("XUSDT", T, TR._hist_feed(mk_getter(full, calls)))
    cut = {k: v[:n_cut] for k, v in full.items()}
    d_cut = TR.decide("XUSDT", T, TR._hist_feed(mk_getter(cut)))
    dump = lambda r: json.dumps(r, sort_keys=True, default=str)  # noqa: E731
    check("рішення на T однакове з майбутніми свічками й без них (немає підглядання)", d_full["ok"] and dump(d_full) == dump(d_cut))
    check("у відповіді decide немає жодної свічки ≥ T", all(x["time"] + 900 <= T for x in d_full["candles"]) and len(d_full["candles"]) > 20)
    check("усі запити до біржі мають endTime = T", all(e == int(T * 1000) for _, e in calls), str(calls[:3]))
    long = [x for x in d_full["decisions"] if x["dir"] == "LONG"][0]
    check("Brain на T бачить LONG WAIT із планом-орієнтиром", long["state"] == "WAIT" and long["plan"] and long["plan"]["source"] == "WATCH-орієнтир", str(long)[:300])
    now = T + 30 * 3600
    rv = TR.reveal("XUSDT", T, TR._hist_feed(mk_getter(full)), now=now)
    check("reveal повертає майбутнє (свічки ≥ T) і результат плану", rv["ok"] and rv["future"] and all(x["time"] >= T for x in rv["future"]) and rv["results"], str(rv)[:300])
    rl = [x for x in rv["results"] if x["dir"] == "LONG"][0]
    check("результат LONG-плану оцінено (paper): вхід/TP або чесне «без входу»", rl["outcome"] in ("TP1", "TP2", "TP3", "ENTERED", "SL", "NO_ENTRY", "WAITING_ENTRY"), str(rl))
    check("рух ціни після T рахується від ціни на T", rv["move"] and rv["move"]["max_up_pct"] > 0, str(rv["move"]))
    check("reveal занадто свіжого T відхиляється", TR.reveal("XUSDT", now - 600, TR._hist_feed(mk_getter(full)), now=now)["ok"] is False)
finally:
    B.all_levels = orig
check("pick_time: у межах 1 год…14 діб, кратний 15 хв", all(TR.pick_time(None, now=2_000_000_000.0, seed=s) % 900 == 0 and 2_000_000_000.0 - 14 * 86400 <= TR.pick_time(None, now=2_000_000_000.0, seed=s) <= 2_000_000_000.0 - 3600 for s in range(20)))
print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)

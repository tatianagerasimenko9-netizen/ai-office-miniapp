#!/usr/bin/env python3
"""Point-in-time replay of the FULL Lev cycle (lev_cycle) on real OHLCV files.

Offline, read-only: no network, Telegram, database or orders. Input is the
JSON produced by scripts/fetch_binance_archive.py (1d/1h/15m, contiguous).

What is measured (kept separate on purpose):
  1. Lev's decisions (SEND / WAIT / WATCHING / SKIP), by direction, regime and
     top reasons - independent of any trade simulation.
  2. A conservative fill simulator applied ONLY to SEND decisions: next M15
     open + adverse slippage, geometry/RR/TP1/H1-ATR-stop checks on the actual
     fill price, exit on first touch, SL wins when SL and TP share a bar,
     round-trip commission. One position at a time (like T6).
  3. Regime classifier validation: label at each H1 close vs what the next
     24 H1 bars actually did (no look-ahead: the label sees closed bars only).

Every input to a decision is the state at the close of that M15 bar: only
fully closed candles, the forming UTC day is rebuilt from closed M15 bars
(as the live fetch_atr_context sees it), H4 is aggregated from closed H1.

These numbers are historical diagnostics, not a forecast. Win rate is shown
with a Wilson 95% interval and a sample-size warning.

Usage:
  python3 scripts/replay_lev_history.py FILE.json [FILE2.json ...]
      [--stride 4] [--eval-from YYYY-MM-DD] [--out report.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

VERSION = "lev-replay-v1"
MIN_TRADES_FOR_CONCLUSION = 30
COMMISSION_PCT = 0.0004  # per side
SLIPPAGE_PCT = 0.0005
FWD_H1 = 24


def _git_sha() -> str:
    sha = os.getenv("GITHUB_SHA")
    if sha:
        return sha
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def wilson(wins: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    if n <= 0:
        return None
    p = wins / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)]


def aggregate_h4(h1_closed: List[Dict[str, Any]], parse_ts) -> List[Dict[str, Any]]:
    """H4 (00/04/08/12/16/20 UTC) from CLOSED H1 only; a partial group is dropped."""
    out: List[Dict[str, Any]] = []
    group: List[Dict[str, Any]] = []
    key = None
    for c in h1_closed:
        t = parse_ts(c["ts"])
        k = (t.date(), t.hour // 4)
        if key is not None and k != key:
            if len(group) == 4:
                out.append(_merge(group))
            group = []
        key = k
        group.append(c)
    if len(group) == 4:
        out.append(_merge(group))
    return out


def _merge(g: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "ts": g[0]["ts"], "open": g[0]["open"], "close": g[-1]["close"],
        "high": max(float(x["high"]) for x in g), "low": min(float(x["low"]) for x in g),
        "volume": sum(float(x.get("volume") or 0.0) for x in g),
    }


def forming_day(m15_closed: List[Dict[str, Any]], asof: datetime, parse_ts) -> Optional[Dict[str, Any]]:
    day0 = asof.replace(hour=0, minute=0, second=0, microsecond=0)
    if asof == day0:
        day0 -= timedelta(days=1)
    bars = [c for c in m15_closed[-96:] if parse_ts(c["ts"]) >= day0]
    if not bars:
        return None
    return {
        "ts": day0.isoformat(), "open": bars[0]["open"], "close": bars[-1]["close"],
        "high": max(float(b["high"]) for b in bars), "low": min(float(b["low"]) for b in bars),
    }


def _pivots(h1: List[Dict[str, Any]], k: int = 2) -> Dict[str, List[float]]:
    """Confirmed H1 swing highs/lows (k bars each side) — only bars fully known at decision time."""
    hi, lo = [], []
    for n in range(k, len(h1) - k):
        h = float(h1[n]["high"])
        l = float(h1[n]["low"])
        if all(h > float(h1[n + d]["high"]) for d in range(-k, k + 1) if d) :
            hi.append(h)
        if all(l < float(h1[n + d]["low"]) for d in range(-k, k + 1) if d):
            lo.append(l)
    return {"high": hi[-12:], "low": lo[-12:]}


def _block(ts: List[Dict[str, Any]]) -> Dict[str, Any]:
    w = sum(1 for t in ts if t["outcome"] == "WIN")
    n = len(ts)
    return {"n": n, "wins": w, "losses": n - w,
            "wr_pct": round(w / n * 100, 1) if n else None,
            "wr_ci95_pct": wilson(w, n), "sum_r": round(sum(t["r"] for t in ts), 3),
            "avg_r": round(sum(t["r"] for t in ts) / n, 3) if n else None}


CURRENT_RULES = {"min_tp1": True, "min_rr": 1.5}


def _fill_checks(side: str, fill: float, sl: float, tp: float, symbol: str, h1_atr: Optional[float],
                 rules: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Same gates as T6, on the ACTUAL fill price. None = passed, else the rejection tag.

    `rules` exists ONLY for the offline variants experiment; production rules are CURRENT_RULES.
    """
    rules = rules or CURRENT_RULES
    if (side == "LONG" and not sl < fill < tp) or (side == "SHORT" and not tp < fill < sl):
        return "GEOMETRY_AT_FILL"
    if rules.get("min_tp1", True) and abs(tp - fill) / fill * 100 < (1.2 if symbol in ("BTCUSDT", "ETHUSDT") else 3.0):
        return "TP1_MIN"
    risk = abs(fill - sl)
    if rules.get("min_rr") is not None and abs(tp - fill) / risk < rules["min_rr"]:
        return "RR_AT_FILL"
    if h1_atr and risk < h1_atr:
        return "H1_ATR_STOP"
    return None


def _run_trade(trade: Dict[str, Any], start_j: int, ctx: Dict[str, Any], *, skip_tp_on_first: bool = False):
    """Walk M15 bars from start_j; SL wins ties; TP is not credited on the fill bar itself."""
    m15 = ctx["m15"]
    risk = abs(trade["entry"] - trade["sl"])
    for j in range(start_j, len(m15)):
        bar = m15[j]
        hi, lo = float(bar["high"]), float(bar["low"])
        if skip_tp_on_first and j == start_j:
            hit = ctx["simulate_exit_on_bar"](side=trade["side"], sl=trade["sl"], tp=1e18 if trade["side"] == "LONG" else 1e-18,
                                              high=hi, low=lo)
        else:
            hit = ctx["simulate_exit_on_bar"](side=trade["side"], sl=trade["sl"], tp=trade["tp"], high=hi, low=lo)
        trade["bars"] = j - start_j + 1
        if hit:
            costs_r = trade["entry"] * 2 * COMMISSION_PCT / risk if risk > 0 else 0.0
            if hit.startswith("SL"):
                trade.update(outcome="LOSS", r=-1.0 - costs_r, conservative=hit == "SL_CONSERVATIVE")
            else:
                trade.update(outcome="WIN", r=abs(trade["tp"] - trade["entry"]) / risk - costs_r)
            trade["exit_ts"] = ctx["close_time"](bar, "15m")
            return trade, j
    return None, len(m15)


def simulate_immediate(sends: List[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Model A (T6 parity): fill at the NEXT M15 open + slippage right after the SEND decision."""
    m15, symbol = ctx["m15"], ctx["symbol"]
    trades: List[Dict[str, Any]] = []
    rejects: Counter = Counter()
    free_from = None
    open_at_end = 0
    for sd in sends:
        j = sd["i"] + 1
        if j >= len(m15):
            rejects["NO_NEXT_BAR"] += 1
            continue
        if free_from is not None and sd["asof"] < free_from:
            rejects["POSITION_OPEN"] += 1
            continue
        side = sd["side"]
        fill = float(m15[j]["open"]) * (1 + SLIPPAGE_PCT if side == "LONG" else 1 - SLIPPAGE_PCT)
        bad = _fill_checks(side, fill, sd["sl"], sd["tp"], symbol, ctx["atr_h1_at"](sd["i"]))
        if bad:
            rejects[bad] += 1
            continue
        t = {"side": side, "entry": fill, "sl": sd["sl"], "tp": sd["tp"], "regime": sd["regime"],
             "entry_ts": ctx["parse_ts"](m15[j]["ts"]).isoformat(), "bars": 0}
        done, _ = _run_trade(t, j, ctx)
        if done is None:
            open_at_end += 1
            free_from = datetime.max.replace(tzinfo=timezone.utc)
            continue
        trades.append(done)
        free_from = done["exit_ts"]
    for t in trades:
        t["exit_ts"] = t["exit_ts"].isoformat() if not isinstance(t["exit_ts"], str) else t["exit_ts"]
    return {"trades": trades, "rejects": rejects, "open_at_end": open_at_end}


def simulate_zone_limit(sends: List[Dict[str, Any]], ctx: Dict[str, Any],
                        rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Model B (closer to the product): the SEND is a plan waiting for price to come back to the zone.

    One scenario per setup_key. Entry = Lev's zone-mid `entry` when price trades into it (LONG low <= entry,
    SHORT high >= entry), adverse slippage added. Cancelled if a bar CLOSES beyond the invalidation (SL) first,
    expired after the H1 TTL. TP is not credited on the fill bar. The LTF confirmation step (M15/M5 SFP)
    is NOT modelled, so this is an upper-bound-of-opportunity check, not the full product flow.
    """
    m15, symbol = ctx["m15"], ctx["symbol"]
    trades: List[Dict[str, Any]] = []
    fates: Counter = Counter()
    rejects: Counter = Counter()
    seen: Dict[str, datetime] = {}
    free_j = 0
    open_at_end = 0
    for sd in sends:
        prev = seen.get(sd["key"])
        if prev is not None and sd["asof"] - prev < timedelta(hours=24):
            fates["DUPLICATE_KEY"] += 1
            continue
        seen[sd["key"]] = sd["asof"]
        side = sd["side"]
        fate = "EXPIRED"
        j = max(sd["i"] + 1, free_j)
        deadline = sd["asof"] + sd["ttl"]
        while j < len(m15):
            bar = m15[j]
            t_close = ctx["close_time"](bar, "15m")
            if t_close > deadline:
                break
            hi, lo, cl = float(bar["high"]), float(bar["low"]), float(bar["close"])
            if (side == "LONG" and cl < sd["sl"]) or (side == "SHORT" and cl > sd["sl"]):
                fate = "INVALIDATED_BEFORE_ENTRY"
                break
            if (side == "LONG" and lo <= sd["entry"]) or (side == "SHORT" and hi >= sd["entry"]):
                fill = sd["entry"] * (1 + SLIPPAGE_PCT if side == "LONG" else 1 - SLIPPAGE_PCT)
                bad = _fill_checks(side, fill, sd["sl"], sd["tp"], symbol, ctx["atr_h1_at"](j), rules)
                if bad:
                    fate = "REJECTED_" + bad
                    break
                t = {"side": side, "entry": fill, "sl": sd["sl"], "tp": sd["tp"], "regime": sd["regime"],
                     "entry_ts": ctx["parse_ts"](bar["ts"]).isoformat(), "bars": 0}
                done, end_j = _run_trade(t, j, ctx, skip_tp_on_first=True)
                if done is None:
                    open_at_end += 1
                    fate = "FILLED_OPEN_AT_END"
                    free_j = len(m15)
                else:
                    trades.append(done)
                    fate = "FILLED"
                    free_j = end_j + 1
                break
            j += 1
        fates[fate] += 1
    for t in trades:
        t["exit_ts"] = t["exit_ts"].isoformat() if not isinstance(t["exit_ts"], str) else t["exit_ts"]
    return {"trades": trades, "fates": fates, "rejects": rejects, "open_at_end": open_at_end}


def _with_tp(sends: List[Dict[str, Any]], fn) -> List[Dict[str, Any]]:
    out = []
    for sd in sends:
        tp = fn(sd)
        if tp is not None:
            out.append({**sd, "tp": tp})
    return out


def _r_tp(mult: float):
    return lambda sd: sd["entry"] + (1 if sd["side"] == "LONG" else -1) * mult * abs(sd["entry"] - sd["sl"])


def _structure_tp(sd: Dict[str, Any]) -> Optional[float]:
    """Nearest confirmed H1 swing beyond >= 1R in the trade direction; no such level -> no target -> scenario skipped."""
    risk = abs(sd["entry"] - sd["sl"])
    if sd["side"] == "LONG":
        c = sorted(p for p in sd["pivots"]["high"] if p >= sd["entry"] + risk)
        return c[0] if c else None
    c = sorted((p for p in sd["pivots"]["low"] if p <= sd["entry"] - risk), reverse=True)
    return c[0] if c else None


VARIANTS = [
    # name, description, tp function, rules
    ("V0_current", "TP1=1.5R, чинні правила (мін. TP1% + RR>=1.5)", _r_tp(1.5), CURRENT_RULES),
    ("V1_no_min_tp1", "TP1=1.5R, без правила мінімального TP1%", _r_tp(1.5), {"min_tp1": False, "min_rr": 1.5}),
    ("V2_tp1.0R", "TP1=1.0R, без мін. TP1% і без порогу RR", _r_tp(1.0), {"min_tp1": False, "min_rr": None}),
    ("V3_tp2.0R", "TP1=2.0R, без мін. TP1%, RR>=1.5", _r_tp(2.0), {"min_tp1": False, "min_rr": 1.5}),
    ("V4_structure", "TP1 = найближчий H1-свінг >= 1R, без мін. TP1%, RR>=1.5", _structure_tp, {"min_tp1": False, "min_rr": 1.5}),
]


def run_variants(sends: List[Dict[str, Any]], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Offline what-if for TP1 definition / min-TP1 rule. Nothing here is enabled anywhere."""
    out: Dict[str, Any] = {}
    for name, desc, fn, rules in VARIANTS:
        sim = simulate_zone_limit(_with_tp(sends, fn), ctx, rules)
        out[name] = {"description": desc, "trades": _block(sim["trades"]), "fates": dict(sim["fates"]),
                     "rejected_at_fill": dict(sim["rejects"]), "open_at_end": sim["open_at_end"],
                     "sum_r_per_100_scenarios": None}
        n_sc = sum(sim["fates"].values()) - sim["fates"].get("DUPLICATE_KEY", 0)
        if n_sc:
            out[name]["sum_r_per_100_scenarios"] = round(out[name]["trades"]["sum_r"] / n_sc * 100, 2)
        out[name]["unique_scenarios"] = n_sc
    return out


def frequency_report(sends: List[Dict[str, Any]], decisions: int, days: float) -> Dict[str, Any]:
    """How often would the desk speak under stricter, still-hypothetical send rules. Counts only."""
    seen: Dict[str, datetime] = {}
    uniq = []
    for sd in sends:
        prev = seen.get(sd["key"])
        if prev is None or sd["asof"] - prev >= timedelta(hours=24):
            uniq.append(sd)
        seen[sd["key"]] = sd["asof"]
    d = max(days, 1e-9)
    rep = {"decisions": decisions, "days": round(days, 1),
           "send_all": {"n": len(sends), "per_day": round(len(sends) / d, 2), "share_of_decisions": round(len(sends) / decisions, 3) if decisions else None},
           "send_unique_scenario_24h": {"n": len(uniq), "per_day": round(len(uniq) / d, 2)}}
    for k in (2, 3, 4):
        sub = [x for x in uniq if x["n_tags"] >= k]
        rep[f"unique_and_confluences_ge_{k}"] = {"n": len(sub), "per_day": round(len(sub) / d, 2)}
    return rep


def replay_file(path: Path, *, stride: int, eval_from: Optional[datetime],
                until: Optional[datetime] = None) -> Dict[str, Any]:
    from office_confluence import reset_live, ttl_sec
    from office_lev_verdict import lev_cycle
    from office_market_regime import MIN_BARS, classify_regime
    from office_t6_backtest import (
        close_time, day_used_pct_offline, load_ohlcv_file, parse_ts, simulate_exit_on_bar,
    )
    from office_trade_steer import atr_from_candles

    data = load_ohlcv_file(path)
    symbol = str(data["symbol"])
    d1_all, h1_all, m15_all = data["timeframes"]["1d"], data["timeframes"]["1h"], data["timeframes"]["15m"]
    months = data.get("months") or []
    if eval_from is None and months:
        eval_from = datetime.strptime(months[-1], "%Y-%m").replace(tzinfo=timezone.utc)
    if eval_from is None:
        eval_from = parse_ts(m15_all[0]["ts"]) + timedelta(days=16)
    reset_live()

    actions: Counter = Counter()
    by_dir: Counter = Counter()
    by_regime_action: Dict[str, Counter] = defaultdict(Counter)
    reasons: Counter = Counter()
    errors: Counter = Counter()
    sends: List[Dict[str, Any]] = []
    d_end = h_end = 0
    n_dec = 0
    for i, bar in enumerate(m15_all):
        asof = close_time(bar, "15m")
        if until is not None and asof > until:
            break
        if asof < eval_from or (i % stride):
            continue
        while d_end < len(d1_all) and close_time(d1_all[d_end], "1d") <= asof:
            d_end += 1
        while h_end < len(h1_all) and close_time(h1_all[h_end], "1h") <= asof:
            h_end += 1
        d1c, h1c, m15c = d1_all[:d_end], h1_all[:h_end], m15_all[:i + 1]
        if len(d1c) < 14 or len(h1c) < 48 or len(m15c) < 96:
            continue
        today = forming_day(m15c, asof, parse_ts)
        day_used = day_used_pct_offline(d1c[-14:] + ([today] if today else []))
        h4c = aggregate_h4(h1c[-200:], parse_ts)[-48:]
        d1w, h1w, m15w = d1c[-30:], h1c[-48:], m15c[-96:]
        price = float(bar["close"])
        try:
            cyc = lev_cycle(
                symbol=symbol, price=price, timeframe="H1",
                candles_m5=m15w, candles_m15=m15w, candles_h1=h1w, candles_h4=h4c, candles_d1=d1w,
                candles_ltf=m15w, atr_h1=atr_from_candles(h1w), day_used_pct=day_used,
                now_ts=asof.timestamp(), market_context={"data_status": "DATA_UNAVAILABLE"},
            )
        except Exception as exc:  # a crash is a finding, not a skipped step
            errors[f"LEV_ERROR_{type(exc).__name__}"] += 1
            continue
        n_dec += 1
        action = str(cyc.get("action") or "?")
        side = str(cyc.get("direction") or "")
        regime = "UNKNOWN"
        for tf, cand in (("H4", h4c), ("H1", h1w)):
            if len(cand) >= MIN_BARS:
                r = classify_regime(cand, timeframe=tf)
                if r["data_status"] == "DATA_OK":
                    regime = r["regime"]
                    break
        actions[action] += 1
        by_dir[f"{action}:{side}"] += 1
        by_regime_action[regime][action] += 1
        reasons[(action, str(cyc.get("reason") or "")[:70])] += 1
        if action == "SEND" and cyc.get("send"):
            conf = (cyc.get("draft") or {}).get("confluence") or {}
            sends.append({
                "i": i, "asof": asof, "side": side, "regime": regime,
                "entry": float(cyc["entry"]), "sl": float(cyc["sl"]), "tp": float(cyc["tp1"]),
                "key": str(conf.get("setup_key") or f"{symbol}|{side}|{cyc['entry']:.6g}"),
                "ttl": timedelta(seconds=ttl_sec("H1")),
                "n_tags": len([t for t in (conf.get("tags") or []) if t]),
                "pivots": _pivots(h1c[-200:]),
            })

    bars_ctx = {"m15": m15_all, "simulate_exit_on_bar": simulate_exit_on_bar,
                "atr_h1_at": lambda j: atr_from_candles([c for c in h1_all if close_time(c, "1h") <= close_time(m15_all[j], "15m")][-48:]),
                "close_time": close_time, "parse_ts": parse_ts, "symbol": symbol}
    def _median(xs: List[float]) -> Optional[float]:
        xs = sorted(xs)
        if not xs:
            return None
        m = len(xs) // 2
        return round(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2, 3)

    min_tp1 = 1.2 if symbol in ("BTCUSDT", "ETHUSDT") else 3.0
    stop_pcts = [abs(x["entry"] - x["sl"]) / x["entry"] * 100 for x in sends]
    tp_pcts = [abs(x["tp"] - x["entry"]) / x["entry"] * 100 for x in sends]
    send_geometry = {
        "n": len(sends), "median_stop_pct": _median(stop_pcts), "median_tp1_pct": _median(tp_pcts),
        "median_rr": _median([t / s_ for t, s_ in zip(tp_pcts, stop_pcts) if s_ > 0]),
        "min_tp1_pct_rule": min_tp1,
        "share_tp1_below_rule": round(sum(1 for t in tp_pcts if t < min_tp1) / len(tp_pcts), 3) if tp_pcts else None,
        "unique_setup_keys": len({x["key"] for x in sends}),
    }
    model_a = simulate_immediate(sends, bars_ctx)
    model_b = simulate_zone_limit(sends, bars_ctx)
    span_days = (parse_ts(m15_all[-1]["ts"]) - eval_from).total_seconds() / 86400 if m15_all else 0.0
    variants = run_variants(sends, bars_ctx)
    freq = frequency_report(sends, n_dec, span_days)
    rejects = model_a["rejects"]
    trades = model_a["trades"]
    open_trade = model_a["open_at_end"]

    # ---- regime classifier validation (point-in-time labels vs forward behaviour) ----
    val: Dict[str, Dict[str, float]] = {}
    fwd_er_all: List[float] = []
    per: Dict[str, List[float]] = defaultdict(list)
    per_move: Dict[str, List[float]] = defaultdict(list)
    for j in range(max(48, MIN_BARS), len(h1_all) - FWD_H1):
        if close_time(h1_all[j], "1h") < eval_from:
            continue
        if until is not None and close_time(h1_all[j + FWD_H1], "1h") > until:
            break
        window = h1_all[j - 47:j + 1]
        r = classify_regime(window, timeframe="H1")
        if r["data_status"] != "DATA_OK":
            continue
        fw = h1_all[j:j + FWD_H1 + 1]
        path_len = sum(abs(float(fw[k]["close"]) - float(fw[k - 1]["close"])) for k in range(1, len(fw)))
        er = abs(float(fw[-1]["close"]) - float(fw[0]["close"])) / path_len if path_len > 0 else 0.0
        atr = atr_from_candles(window) or 0.0
        per[r["regime"]].append(er)
        fwd_er_all.append(er)
        if atr > 0:
            per_move[r["regime"]].append(abs(float(fw[-1]["close"]) - float(fw[0]["close"])) / atr)
    base_trend = sum(1 for x in fwd_er_all if x >= 0.35) / len(fwd_er_all) if fwd_er_all else None
    base_range = sum(1 for x in fwd_er_all if x <= 0.20) / len(fwd_er_all) if fwd_er_all else None
    for reg, ers in per.items():
        mv = per_move.get(reg) or [0.0]
        val[reg] = {
            "n": len(ers),
            "mean_fwd_er": round(sum(ers) / len(ers), 3),
            "share_fwd_trendlike": round(sum(1 for x in ers if x >= 0.35) / len(ers), 3),
            "share_fwd_rangelike": round(sum(1 for x in ers if x <= 0.20) / len(ers), 3),
            "mean_fwd_move_in_atr": round(sum(mv) / len(mv), 2),
        }

    def model_report(m: Dict[str, Any]) -> Dict[str, Any]:
        ts = m["trades"]
        return {
            "trades": _block(ts),
            "by_side": {sd: _block([t for t in ts if t["side"] == sd]) for sd in ("LONG", "SHORT")},
            "by_regime": {rg: _block([t for t in ts if t["regime"] == rg]) for rg in sorted({t["regime"] for t in ts})},
            "rejected_at_fill": dict(m["rejects"]),
            "scenario_fates": dict(m.get("fates", {})),
            "conservative_sl_tp_same_bar": sum(1 for t in ts if t.get("conservative")),
            "open_at_end": m["open_at_end"],
        }

    return {
        "symbol": symbol,
        "input_sha256": _sha256(path),
        "eval_from": eval_from.isoformat(),
        "decisions": n_dec,
        "lev_errors": dict(errors),
        "actions": dict(actions),
        "actions_by_direction": dict(by_dir),
        "actions_by_regime": {k: dict(v) for k, v in by_regime_action.items()},
        "top_reasons": [{"action": a_, "reason": r_, "n": n_} for (a_, r_), n_ in reasons.most_common(12)],
        "send_decisions": len(sends),
        "send_geometry": send_geometry,
        "model_a_next_open_immediate": model_report(model_a),
        "model_b_zone_limit_no_ltf_confirm": model_report(model_b),
        "variants_what_if": variants,
        "send_frequency": freq,
        "regime_validation": {"h1_window": 48, "forward_h1": FWD_H1,
                              "base_trendlike": None if base_trend is None else round(base_trend, 3),
                              "base_rangelike": None if base_range is None else round(base_range, 3),
                              "by_regime": val},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--stride", type=int, default=4, help="decide every N-th M15 close (4 = hourly)")
    ap.add_argument("--eval-from", default="", help="YYYY-MM-DD; default = start of the last loaded month")
    ap.add_argument("--out", default="")
    ap.add_argument("--summary", action="store_true", help="print a compact table instead of the full JSON")
    a = ap.parse_args()
    if a.stride < 1:
        raise SystemExit("--stride must be >= 1")
    eval_from = datetime.strptime(a.eval_from, "%Y-%m-%d").replace(tzinfo=timezone.utc) if a.eval_from else None
    report: Dict[str, Any] = {
        "version": VERSION, "git_sha": _git_sha(), "python": sys.version.split()[0],
        "params": {"stride_m15": a.stride, "commission_pct_per_side": COMMISSION_PCT,
                   "slippage_pct": SLIPPAGE_PCT, "fill": "next M15 open", "same_bar_sl_tp": "SL",
                   "fwd_h1": FWD_H1},
        "disclaimer": "Historical diagnostics on real candles; not a forecast, not live results, not order authorization.",
        "symbols": [],
    }
    for f in a.files:
        report["symbols"].append(replay_file(Path(f), stride=a.stride, eval_from=eval_from))
    report["pooled"] = {}
    for name in ("model_a_next_open_immediate", "model_b_zone_limit_no_ltf_confirm"):
        n = sum(x[name]["trades"]["n"] for x in report["symbols"])
        w = sum(x[name]["trades"]["wins"] for x in report["symbols"])
        report["pooled"][name] = {
            "trades": n, "wins": w, "wr_ci95_pct": wilson(w, n),
            "conclusion": (
                "INSUFFICIENT_SAMPLE: fewer than %d closed simulated trades - no conclusion about profitability"
                % MIN_TRADES_FOR_CONCLUSION if n < MIN_TRADES_FOR_CONCLUSION
                else "sample large enough for a first look only; one market period, no out-of-sample check"
            ),
        }
    pv: Dict[str, Any] = {}
    for vn, _d, _f, _r in VARIANTS:
        ts = [x["variants_what_if"][vn] for x in report["symbols"]]
        n = sum(v["trades"]["n"] for v in ts)
        w = sum(v["trades"]["wins"] for v in ts)
        sc = sum(v["unique_scenarios"] for v in ts)
        sr = round(sum(v["trades"]["sum_r"] for v in ts), 3)
        pv[vn] = {"unique_scenarios": sc, "trades": n, "wins": w, "wr_ci95_pct": wilson(w, n), "sum_r": sr,
                  "avg_r": round(sr / n, 3) if n else None, "fill_rate": round(n / sc, 3) if sc else None,
                  "conclusion": "INSUFFICIENT_SAMPLE" if n < MIN_TRADES_FOR_CONCLUSION else "first look only; one period, no out-of-sample"}
    report["pooled_variants_what_if"] = pv
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    print(summarize(report) if a.summary else text)
    return 0


def summarize(rep: Dict[str, Any]) -> str:
    L = [f"LEV_REPLAY {rep['version']} git={rep['git_sha'][:10]} params={json.dumps(rep['params'], ensure_ascii=False)}"]
    for x in rep["symbols"]:
        L.append(f"== {x['symbol']} eval_from={x['eval_from'][:10]} sha256={x['input_sha256'][:12]} decisions={x['decisions']} "
                 f"errors={x['lev_errors']} actions={x['actions']} sends={x['send_decisions']}")
        L.append("   by_dir=" + json.dumps(x["actions_by_direction"], ensure_ascii=False))
        L.append("   by_regime=" + json.dumps(x["actions_by_regime"], ensure_ascii=False))
        for r in x["top_reasons"][:5]:
            L.append(f"   reason {r['action']:8} n={r['n']:4} {r['reason']}")
        L.append("   send_geometry=" + json.dumps(x["send_geometry"], ensure_ascii=False))
        for name in ("model_a_next_open_immediate", "model_b_zone_limit_no_ltf_confirm"):
            m = x[name]
            t = m["trades"]
            L.append(f"   {name}: trades={t['n']} W={t['wins']} L={t['losses']} wr={t['wr_pct']} ci95={t['wr_ci95_pct']} "
                     f"sumR={t['sum_r']} avgR={t['avg_r']} same_bar_SL={m['conservative_sl_tp_same_bar']} open_end={m['open_at_end']}")
            L.append(f"      rejected_at_fill={m['rejected_at_fill']} fates={m['scenario_fates']}")
            L.append("      by_side=" + json.dumps({k: (v['n'], v['wr_pct'], v['sum_r']) for k, v in m['by_side'].items()}))
            L.append("      by_regime=" + json.dumps({k: (v['n'], v['wr_pct'], v['sum_r']) for k, v in m['by_regime'].items()}))
        for vn, v in x["variants_what_if"].items():
            t = v["trades"]
            L.append(f"   variant {vn:15} scen={v['unique_scenarios']:4} trades={t['n']:3} wr={t['wr_pct']} sumR={t['sum_r']} "
                     f"R/100sc={v['sum_r_per_100_scenarios']} rej={v['rejected_at_fill']}")
        L.append("   send_frequency=" + json.dumps(x["send_frequency"], ensure_ascii=False))
        rv = x["regime_validation"]
        L.append(f"   regime_validation base_trendlike={rv['base_trendlike']} base_rangelike={rv['base_rangelike']}")
        for k, v in sorted(rv["by_regime"].items()):
            L.append(f"      {k:11} n={v['n']:5} fwdER={v['mean_fwd_er']} trendlike={v['share_fwd_trendlike']} "
                     f"rangelike={v['share_fwd_rangelike']} move/ATR={v['mean_fwd_move_in_atr']}")
    L.append("POOLED " + json.dumps(rep["pooled"], ensure_ascii=False))
    for vn, v in rep.get("pooled_variants_what_if", {}).items():
        L.append(f"POOLED_VARIANT {vn:15} scenarios={v['unique_scenarios']} trades={v['trades']} fill={v['fill_rate']} wins={v['wins']} "
                 f"ci95={v['wr_ci95_pct']} sumR={v['sum_r']} avgR={v['avg_r']} -> {v['conclusion']}")
    L.append(rep["disclaimer"])
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())

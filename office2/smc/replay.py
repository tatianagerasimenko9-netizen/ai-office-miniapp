"""Time-frozen replay: Brain v2.1 і SMC на ОДНАКОВИХ закритих барах, без жодного майбутнього бару у вході рішення. Порівняння: READY-події, перетини, хибні READY, пропущені чисті рухи, R.
Результат — експлоративна діагностика, а не доказ прибутковості: вибірки малі, вихід — спрощений (TP1 / SL / горизонт на M15, SL першим при одному барі), витрати й затримка входу вказуються явно.
Запуск: у worker через OFFICE2_SMC_REPLAY (дані з біржі) або офлайн на масивах (тести)."""
from __future__ import annotations

import json
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from office2 import brain as B
from office2 import brain2 as B2
from office2 import sim as SIM
from office2.smc import engine as EN
from office2.smc.core import Arr

DDL = ["""CREATE TABLE IF NOT EXISTS office2_smc_replay (
    run_id TEXT NOT NULL, symbol TEXT NOT NULL, ts_bar BIGINT NOT NULL, direction TEXT NOT NULL, source TEXT NOT NULL, model TEXT NOT NULL,
    entry DOUBLE PRECISION, sl DOUBLE PRECISION, tp1 DOUBLE PRECISION, outcome TEXT, r_net DOUBLE PRECISION, payload_json TEXT, PRIMARY KEY (run_id, symbol, ts_bar, direction, source, model))""",
       """CREATE TABLE IF NOT EXISTS office2_smc_replay_summary (run_id TEXT PRIMARY KEY, created_ts DOUBLE PRECISION NOT NULL, summary_json TEXT NOT NULL)"""]
HORIZON_BARS = 96            # 24 год на M15
OPP_BARS, OPP_FAV_ATR, OPP_ADV_ATR = 48, 3.0, 1.5
WARMUP = 200
DEFAULT_FEE_RT_PCT = SIM.FEE_RT_DEFAULT
DEFAULT_SLIPPAGE_RT_BPS = 4.0
DEFAULT_ENTRY_DELAY_SEC = 30.0
DEFAULT_ENTRY_TTL_SEC = 6 * 3600.0


def _cut(a: Optional[Arr], width: int, now: float) -> Optional[Arr]:
    if a is None:
        return None
    n = int(np.searchsorted(a["t"] + width, now, side="right"))
    return {k: v[:n] for k, v in a.items()} if n > 0 else None


def ctx_at(arrs: Dict[str, Optional[Arr]], now: float) -> Optional[Dict[str, Any]]:
    """Контекст на момент now ЛИШЕ з барів, закритих до now (кожен TF обрізається окремо)."""
    m15, h4, d1, w1 = _cut(arrs.get("m15"), 900, now), _cut(arrs.get("h4"), 14400, now), _cut(arrs.get("d1"), 86400, now), _cut(arrs.get("w1"), 604800, now)
    if not (m15 and h4 and d1 and w1) or len(m15["t"]) < 120:
        return None
    return B.build_full_ctx(m15, h4, d1, w1, arrs.get("mn"))


def simulate(
    m15: Arr,
    i0: int,
    direction: str,
    entry: float,
    sl: float,
    tp1: float,
    r_tp1: float,
    risk_pct: float,
    horizon: int = HORIZON_BARS,
    *,
    fee_rt_pct: float = DEFAULT_FEE_RT_PCT,
    slippage_rt_bps: float = DEFAULT_SLIPPAGE_RT_BPS,
    entry_delay_sec: float = 0.0,
    entry_ttl_sec: float = DEFAULT_ENTRY_TTL_SEC,
) -> Dict[str, Any]:
    """Результат після рішення: TP1 / SL / OPEN або пропущений вхід.

    На M15 затримка має роздільність одного бару: додатна затримка бере open
    першого доступного бару, повні 15 хв додають наступний бар. До fill перевіряємо
    SL/TP, а витрати кола віднімаємо від R. Обидва рівні в одному барі → SL.
    """
    sg = 1.0 if direction == "LONG" else -1.0
    delay = max(0.0, float(entry_delay_sec))
    ttl = max(0.0, float(entry_ttl_sec))
    costs = max(0.0, float(fee_rt_pct)) + max(0.0, float(slippage_rt_bps)) / 100.0
    if delay > ttl:
        return {"outcome": "MISSED_ENTRY_TTL", "r_gross": None, "r_net": None, "mfe_r": None, "mae_r": None, "bars": 0,
                "complete": True, "entry_delay_sec": delay, "entry_delay_bars": None, "fill_entry": None, "cost_rt_pct": costs}
    delay_bars = int(delay // 900)
    fill_i = i0 + 1 + delay_bars
    if fill_i >= len(m15["t"]):
        return {"outcome": "NO_DATA", "r_gross": None, "r_net": None, "mfe_r": None, "mae_r": None, "bars": 0,
                "complete": False, "entry_delay_sec": delay, "entry_delay_bars": delay_bars, "fill_entry": None, "cost_rt_pct": costs}
    if delay > 0:
        pre_h, pre_l = m15["h"][i0 + 1:fill_i], m15["l"][i0 + 1:fill_i]
        pre_sl = bool(((pre_l <= sl) if sg > 0 else (pre_h >= sl)).any())
        pre_tp = bool(((pre_h >= tp1) if sg > 0 else (pre_l <= tp1)).any())
        if pre_sl or pre_tp:
            reason = "MISSED_SL_BEFORE_ENTRY" if pre_sl else "MISSED_TP_BEFORE_ENTRY"
            return {"outcome": reason, "r_gross": None, "r_net": None, "mfe_r": None, "mae_r": None, "bars": 0,
                    "complete": True, "entry_delay_sec": delay, "entry_delay_bars": delay_bars, "fill_entry": None, "cost_rt_pct": costs}
    fill_entry = float(m15["o"][fill_i]) if delay > 0 else float(entry)
    risk = abs(fill_entry - sl)
    h, l, c = m15["h"][fill_i:fill_i + horizon], m15["l"][fill_i:fill_i + horizon], m15["c"][fill_i:fill_i + horizon]
    if len(h) == 0 or risk <= 0:
        return {"outcome": "NO_DATA", "r_gross": None, "r_net": None, "mfe_r": None, "mae_r": None, "bars": 0,
                "complete": False, "entry_delay_sec": delay, "entry_delay_bars": delay_bars, "fill_entry": fill_entry, "cost_rt_pct": costs}
    hit_sl = (l <= sl) if sg > 0 else (h >= sl)
    hit_tp = (h >= tp1) if sg > 0 else (l <= tp1)
    isl = int(np.argmax(hit_sl)) if hit_sl.any() else -1
    itp = int(np.argmax(hit_tp)) if hit_tp.any() else -1
    if isl >= 0 and (itp < 0 or isl <= itp):
        k, out, rg = isl, "SL", -1.0
    elif itp >= 0:
        k, out = itp, "TP1"
        rg = float(r_tp1) if delay <= 0 else abs(float(tp1) - fill_entry) / risk
    else:
        k, out = len(h) - 1, "OPEN"
        rg = float(sg * (c[-1] - fill_entry) / risk)
    fav = float((h[:k + 1].max() - fill_entry) / risk) if sg > 0 else float((fill_entry - l[:k + 1].min()) / risk)
    adv = float((fill_entry - l[:k + 1].min()) / risk) if sg > 0 else float((h[:k + 1].max() - fill_entry) / risk)
    actual_risk_pct = risk / max(abs(fill_entry), 1e-9) * 100.0 if delay > 0 else float(risk_pct)
    return {"outcome": out, "r_gross": rg, "r_net": SIM.net_r(rg, actual_risk_pct, costs), "mfe_r": fav, "mae_r": adv, "bars": k + 1,
            "complete": len(h) >= horizon or out != "OPEN", "entry_delay_sec": delay, "entry_delay_bars": delay_bars, "fill_entry": fill_entry,
            "risk_pct_at_fill": actual_risk_pct, "fee_rt_pct": float(fee_rt_pct), "slippage_rt_bps": float(slippage_rt_bps), "cost_rt_pct": costs}


def _brain_ready(sym: str, ctx: Dict[str, Any], now: float, levels, mc, rel) -> List[Dict[str, Any]]:
    out = []
    for d in ("LONG", "SHORT"):
        th = B2.thesis(ctx, d, now, levels, 10.0, mc=mc, rel=rel, hooks=None)
        if th and th.get("state") == "READY":
            tg = th.get("targets") or []
            ev = th.get("event") or {}
            out.append({"source": "BRAIN", "model": th.get("kind", "SWEEP_SEQ"), "dir": d, "key": th.get("id"), "entry": float(th["entry"]), "sl": float(th["sl"]),
                        "tp1": float(tg[0]["p"]) if tg else None, "r_tp1": float(tg[0]["r"]) if tg else None, "risk_pct": float(th.get("risk_pct") or 0.0),
                        "late": ev.get("class") == "LATE_SWEEP", "ctx_class": (th.get("integral") or {}).get("classification"), "zone": th.get("entry_zone")})
    return out


def _smc_ready(sym: str, ctx: Dict[str, Any], now: float, levels) -> List[Dict[str, Any]]:
    r = EN.analyze(ctx, now, sym, real_levels=levels, with_events=False)
    out = []
    if r.get("error"):
        return out
    for d, mods in r["models"].items():
        for model, v in mods.items():
            if v and v["state"] == "READY":
                tg = v.get("targets") or []
                out.append({"source": "SMC", "model": model, "dir": d, "key": f"{d}|{model}|{v['sweep']['j'] if v.get('sweep') else 0}", "entry": float(v["entry"]), "sl": float(v["sl"]),
                            "tp1": float(tg[0]["p"]) if tg else None, "r_tp1": float(tg[0]["r"]) if tg else None, "risk_pct": float(v.get("risk_pct") or 0.0),
                            "late": False, "sweep_class": (v.get("sweep") or {}).get("class"), "ctx_class": ("COUNTER" if (v.get("bias") or {}).get("dir") == ("DOWN" if d == "LONG" else "UP") else "WITH_OR_NEUTRAL"), "zone": v.get("zone")})
    return out


def _ret1h(m15: Arr, now: float) -> Optional[float]:
    n = int(np.searchsorted(m15["t"] + 900, now, side="right")) - 1
    return float((m15["c"][n] / m15["c"][n - 4] - 1.0) * 100.0) if n >= 4 else None


def replay_arrays(sym: str, arrs: Dict[str, Optional[Arr]], t_from: float, t_to: float, mc: Optional[Dict[str, Any]] = None, rel: Optional[Dict[str, Any]] = None,
                  with_brain: bool = True, with_smc: bool = True, log=None, btc: Optional[Arr] = None, throttle_s: float = 0.0, outcome_end: Optional[float] = None,
                  fee_rt_pct: float = DEFAULT_FEE_RT_PCT, slippage_rt_bps: float = DEFAULT_SLIPPAGE_RT_BPS,
                  entry_delay_sec: float = DEFAULT_ENTRY_DELAY_SEC, entry_ttl_sec: float = DEFAULT_ENTRY_TTL_SEC) -> Dict[str, Any]:
    """Прохід по барах M15 (закриття у (t_from, t_to]) із поступовим відкриттям даних. Повертає події READY обох рушіїв і підсумок."""
    m15 = arrs["m15"]
    ends = m15["t"] + 900
    idx = np.flatnonzero((ends > t_from) & (ends <= t_to))
    events: List[Dict[str, Any]] = []
    seen: set = set()
    t0 = time.time()
    tm = {"brain_ms": [], "smc_ms": []}
    for i in idx:
        now = float(ends[i])
        ctx = ctx_at(arrs, now)
        if ctx is None:
            continue
        levels = B.all_levels(ctx, now)
        if btc is not None and mc is None and rel is None:
            b1 = _ret1h(btc, now) if sym != "BTCUSDT" else _ret1h(arrs["m15"], now)       # лише з барів, закритих до now
            c1 = _ret1h(arrs["m15"], now)
            mc_i, rel_i = {"btc_ret_1h": b1}, {"coin_ret_1h": c1, "rs_vs_btc_1h": (c1 - b1) if (b1 is not None and c1 is not None) else None}
        else:
            mc_i, rel_i = mc, rel
        found = []
        if with_brain:
            tb = time.perf_counter()
            try:
                found += _brain_ready(sym, ctx, now, levels, mc_i, rel_i)
            except Exception as exc:  # noqa: BLE001
                events.append({"source": "BRAIN", "error": f"{type(exc).__name__}: {str(exc)[:100]}", "ts_bar": int(now)})
            tm["brain_ms"].append((time.perf_counter() - tb) * 1000.0)
        if with_smc:
            ts_ = time.perf_counter()
            try:
                found += _smc_ready(sym, ctx, now, levels)
            except Exception as exc:  # noqa: BLE001
                events.append({"source": "SMC", "error": f"{type(exc).__name__}: {str(exc)[:100]}", "ts_bar": int(now)})
            tm["smc_ms"].append((time.perf_counter() - ts_) * 1000.0)
        if throttle_s:
            time.sleep(throttle_s)                    # не відбираємо CPU у живого циклу, коли replay йде у worker
        for f in found:
            kk = (f["source"], f["key"])
            if kk in seen:
                continue
            seen.add(kk)
            f.update(symbol=sym, ts_bar=int(now), i=int(i))
            if f.get("tp1") is not None and f["risk_pct"] > 0:
                f["sim"] = simulate(m15, int(i), f["dir"], f["entry"], f["sl"], f["tp1"], f["r_tp1"], f["risk_pct"],
                                    fee_rt_pct=fee_rt_pct, slippage_rt_bps=slippage_rt_bps,
                                    entry_delay_sec=entry_delay_sec, entry_ttl_sec=entry_ttl_sec)
            events.append(f)
    pct = lambda a, q: round(float(np.percentile(a, q)), 1) if a else None  # noqa: E731
    return {"symbol": sym, "events": events, "bars": int(len(idx)), "elapsed_s": round(time.time() - t0, 1), "opportunities": opportunities(m15, t_from, t_to),
            "execution_assumptions": {"fee_rt_pct": float(fee_rt_pct), "slippage_rt_bps": float(slippage_rt_bps),
                                      "entry_delay_sec": float(entry_delay_sec), "entry_ttl_sec": float(entry_ttl_sec), "bar_resolution_sec": 900},
            "timing": {k: {"n": len(v), "p50": pct(v, 50), "p95": pct(v, 95), "p99": pct(v, 99), "max": pct(v, 100)} for k, v in tm.items()}}


def opportunities(m15: Arr, t_from: float, t_to: float) -> List[Dict[str, Any]]:
    """«Чисті рухи» (лише для оцінки пропущеного, НЕ вхід у рішення): за наступні OPP_BARS барів ціна пройшла ≥ OPP_FAV_ATR ATR у бік при зворотному ходу ≤ OPP_ADV_ATR ATR."""
    from office2.smc import core as K

    a = K.atr_arr(m15, 14)
    ends = m15["t"] + 900
    out: List[Dict[str, Any]] = []
    last = {"LONG": -99, "SHORT": -99}
    for i in np.flatnonzero((ends > t_from) & (ends <= t_to)):
        ia = a[i]
        if not np.isfinite(ia) or ia <= 0 or i + OPP_BARS >= len(m15["t"]):
            continue
        c0 = m15["c"][i]
        hh = m15["h"][i + 1:i + 1 + OPP_BARS].max()
        ll = m15["l"][i + 1:i + 1 + OPP_BARS].min()
        for d, fav, adv in (("LONG", (hh - c0) / ia, (c0 - ll) / ia), ("SHORT", (c0 - ll) / ia, (hh - c0) / ia)):
            if fav >= OPP_FAV_ATR and adv <= OPP_ADV_ATR and i - last[d] > OPP_BARS // 2:
                out.append({"dir": d, "ts_bar": int(ends[i]), "i": int(i), "fav_atr": round(float(fav), 2), "adv_atr": round(float(adv), 2)})
                last[d] = int(i)
    return out


def bootstrap_ci(xs: List[float], n: int = 2000, seed: int = 7) -> Optional[List[float]]:
    if len(xs) < 10:
        return None
    rs = np.random.RandomState(seed)
    a = np.array(xs, dtype=float)
    m = [float(a[rs.randint(0, len(a), len(a))].mean()) for _ in range(n)]
    return [round(float(np.percentile(m, 2.5)), 3), round(float(np.percentile(m, 97.5)), 3)]


def _block(es: List[Dict[str, Any]]) -> Dict[str, Any]:
    sims = [e["sim"] for e in es if e.get("sim") and e["sim"]["r_net"] is not None]
    missed = [e["sim"] for e in es if e.get("sim") and str(e["sim"].get("outcome") or "").startswith("MISSED_")]
    rs = [x["r_net"] for x in sims]
    oc = {k: sum(1 for x in sims if x["outcome"] == k) for k in ("TP1", "SL", "OPEN")}
    res = oc["TP1"] + oc["SL"]
    sl = [x for x in sims if x["outcome"] == "SL"]
    return {"ready": len(es), "scored": len(sims), "missed_entry": len(missed), "missed_entry_reasons": {k: sum(1 for x in missed if x["outcome"] == k) for k in sorted({x["outcome"] for x in missed})},
            "outcomes": oc, "win_rate_resolved": round(oc["TP1"] / res, 3) if res else None, "mean_r_net": round(float(np.mean(rs)), 3) if rs else None,
            "r_net_ci95": bootstrap_ci(rs), "false_ready_rate": round(oc["SL"] / len(sims), 3) if sims else None,
            "fast_sl_share": round(sum(1 for x in sl if x["bars"] <= 4) / len(sl), 3) if sl else None, "avg_bars_to_outcome": round(float(np.mean([x["bars"] for x in sims if x["outcome"] != "OPEN"])), 1) if any(x["outcome"] != "OPEN" for x in sims) else None}


def summarize(runs: List[Dict[str, Any]], lead_bars: int = 16) -> Dict[str, Any]:
    """Підсумок по всіх символах: на рушій — кількість, TP1/SL/OPEN, середній R net (+bootstrap CI при n≥10), recall пропущених рухів, перетини, помилки, затримки обчислення, LATE_SWEEP."""
    ev = [e for r in runs for e in r["events"] if "error" not in e]
    errs = [e for r in runs for e in r["events"] if "error" in e]
    opp = [dict(o, symbol=r["symbol"]) for r in runs for o in r["opportunities"]]
    assumptions = [r.get("execution_assumptions") for r in runs if r.get("execution_assumptions")]
    out: Dict[str, Any] = {"symbols": [r["symbol"] for r in runs], "bars": sum(r["bars"] for r in runs), "errors": len(errs), "error_samples": [e["error"] for e in errs[:3]], "engines": {}, "opportunities": len(opp),
                           "execution_assumptions": assumptions[0] if assumptions and all(x == assumptions[0] for x in assumptions) else assumptions}
    near = lambda x, y, k=4: x["symbol"] == y["symbol"] and x["dir"] == y["dir"] and abs(x["ts_bar"] - y["ts_bar"]) <= k * 900  # noqa: E731
    for src in ("BRAIN", "SMC"):
        mine = [e for e in ev if e["source"] == src]
        blk = _block(mine)
        caught = sum(1 for o in opp if any(e["symbol"] == o["symbol"] and e["dir"] == o["dir"] and o["ts_bar"] - lead_bars * 900 <= e["ts_bar"] <= o["ts_bar"] + 8 * 900 for e in mine))
        blk.update(long=sum(1 for e in mine if e["dir"] == "LONG"), short=sum(1 for e in mine if e["dir"] == "SHORT"), opportunities_caught=caught, recall=round(caught / len(opp), 3) if opp else None,
                   by_dir={d: _block([e for e in mine if e["dir"] == d]) for d in ("LONG", "SHORT")}, by_model={m: _block([e for e in mine if e["model"] == m]) for m in sorted({e["model"] for e in mine})},
                   by_ctx={c: _block([e for e in mine if e.get("ctx_class") == c]) for c in sorted({str(e.get("ctx_class")) for e in mine})})
        tms = [r.get("timing", {}).get("brain_ms" if src == "BRAIN" else "smc_ms") for r in runs]
        tms = [t for t in tms if t and t["n"]]
        if tms:
            blk["compute_ms_per_bar"] = {"p50": round(float(np.median([t["p50"] for t in tms])), 1), "p95_max": max(t["p95"] for t in tms), "max": max(t["max"] for t in tms)}
        out["engines"][src] = blk
    b = [e for e in ev if e["source"] == "BRAIN"]
    sm = [e for e in ev if e["source"] == "SMC"]
    pairs = [(x, y) for x in b for y in sm if near(x, y)]
    both_b = {id(x) for x, _ in pairs}
    both_s = {id(y) for _, y in pairs}
    out["overlap"] = {"both": len(both_b), "only_brain": len(b) - len(both_b), "only_smc": len(sm) - len(both_s)}
    offs = [(y["ts_bar"] - x["ts_bar"]) // 900 for x, y in pairs]
    out["overlap"]["smc_minus_brain_bars"] = {"median": float(np.median(offs)), "min": int(min(offs)), "max": int(max(offs))} if offs else None
    out["overlap"]["intersection_outcomes"] = _block([x for x in b if id(x) in both_b])
    out["overlap"]["only_brain_outcomes"] = _block([x for x in b if id(x) not in both_b])
    out["overlap"]["only_smc_outcomes"] = _block([y for y in sm if id(y) not in both_s])
    late = [x for x in b if x.get("late")]
    fresh = [x for x in b if not x.get("late")]
    sup = [x for x in late if any(near(x, y) for y in sm)]
    out["late_sweep"] = {"brain_late": _block(late), "brain_fresh": _block(fresh), "late_with_smc_support": _block(sup), "late_without_smc_support": _block([x for x in late if x not in sup]),
                         "note": "LATE_SWEEP = рівень уже приймався (≥3 закриття за ним); READY не блокується, лише позначається. Решта «незалежної підстави» — збіг із SMC READY ±1 год"}
    out["caveats"] = ["експлоративно, не доказ прибутковості", "вихід спрощений: TP1/SL/горизонт 24 год на M15, SL першим при одному барі",
                      "затримка входу на M15 апроксимується open доступного бару; fee і round-trip slippage віднімаються від R", "малі вибірки: довірчі інтервали ширші за відмінності між рушіями",
                      "SMC — shadow, пороги Brain для SL/цілей збережено (brain.targets_for)", "у replay немає живих хуків Brain (CVD/OI/funding/M5) — докази, що не блокують, відсутні в обох рушіях однаково"]
    return out


def init_db(db: str) -> None:
    from office_bridge import _execute

    for d in DDL:
        _execute(db, d)


def store(db: str, run_id: str, runs: List[Dict[str, Any]], summary: Dict[str, Any]) -> int:
    from office_bridge import _execute

    n = 0
    for r in runs:
        for e in r["events"]:
            if "error" in e:
                continue
            sim = e.get("sim") or {}
            _execute(db, "INSERT INTO office2_smc_replay (run_id, symbol, ts_bar, direction, source, model, entry, sl, tp1, outcome, r_net, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                     (run_id, e["symbol"], e["ts_bar"], e["dir"], e["source"], e["model"], e["entry"], e["sl"], e.get("tp1"), sim.get("outcome"), sim.get("r_net"), json.dumps({k: v for k, v in e.items() if k != "sim"} | {"sim": sim}, default=float)))
            n += 1
    _execute(db, "INSERT INTO office2_smc_replay_summary (run_id, created_ts, summary_json) VALUES (?,?,?) ON CONFLICT (run_id) DO UPDATE SET summary_json=excluded.summary_json, created_ts=excluded.created_ts",
             (run_id, time.time(), json.dumps(summary, ensure_ascii=False, default=float)))
    return n


def load_feed_arrays(feed: Any, sym: str, end_ts: float, days: int) -> Dict[str, Optional[Arr]]:
    """Дані біржі для replay: M15 days×96+WARMUP барів, H4/D1/W1/MN з запасом; кожен запит — endTime = end_ts (без майбутнього)."""
    end = int(end_ts * 1000) - 1
    n15 = min(1500, days * 96 + WARMUP + 20)
    return {"m15": feed.klines(sym, "15m", end_ts, limit=n15, end_ms=end), "h4": feed.klines(sym, "4h", end_ts, limit=400, end_ms=end), "d1": feed.klines(sym, "1d", end_ts, limit=200, end_ms=end),
            "w1": feed.klines(sym, "1w", end_ts, limit=60, end_ms=end), "mn": feed.klines(sym, "1M", end_ts, limit=12, end_ms=end)}


def run_spec(db: str, feed: Any, spec: str, log=print) -> Optional[Dict[str, Any]]:
    """Завдання розділяються «;». Завдання: 'СИМВОЛИ@days=N@end=<epoch закриття останнього бару рішення>@id=<ім'я>'; СИМВОЛИ — через кому або UNIVERSE.
    Опції виконання: fee_rt_pct, slippage_rt_bps, entry_delay_sec, ttl_sec.
    Дані для результатів (24 год після кінця) беруться з біржі, але рішення приймаються лише на барах ≤ end (ctx_at обрізає кожен TF). За замовчуванням end — останній закритий бар мінус 24 год."""
    init_db(db)
    last = None
    for job in [j.strip() for j in spec.split(";") if j.strip()]:
        parts = [x.strip() for x in job.split("@")]
        syms = [x.strip().upper() for x in parts[0].split(",") if x.strip()]
        if syms == ["UNIVERSE"]:
            from office2.live import universe

            syms = list(universe())
        kv = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        days = max(1, min(int(kv.get("days", 5)), 9))
        now_bar = (int(time.time()) // 900) * 900
        end = float(kv.get("end", now_bar - 96 * 900))
        fetch_end = min(float(now_bar), end + 96 * 900)
        run_id = kv.get("id") or f"smc-replay-{int(end)}-{days}d"
        throttle = float(kv.get("throttle", 0.02))
        execution = {
            "fee_rt_pct": max(0.0, float(kv.get("fee_rt_pct", DEFAULT_FEE_RT_PCT))),
            "slippage_rt_bps": max(0.0, float(kv.get("slippage_rt_bps", DEFAULT_SLIPPAGE_RT_BPS))),
            "entry_delay_sec": max(0.0, float(kv.get("entry_delay_sec", DEFAULT_ENTRY_DELAY_SEC))),
            "entry_ttl_sec": max(0.0, float(kv.get("ttl_sec", DEFAULT_ENTRY_TTL_SEC))),
        }
        btc = None
        try:
            btc_arrs = load_feed_arrays(feed, "BTCUSDT", fetch_end, days)
            btc = btc_arrs.get("m15")
        except Exception as exc:  # noqa: BLE001
            log(f"[smc-replay] BTC-контекст недоступний: {type(exc).__name__}")
        runs = []
        inv_out: Dict[str, Any] = {}
        for sym in syms:
            try:
                arrs = load_feed_arrays(feed, sym, fetch_end, days)
                if not arrs.get("m15"):
                    log(f"[smc-replay] {sym}: немає даних")
                    continue
                r = replay_arrays(sym, arrs, end - days * 86400, end, btc=btc, throttle_s=throttle, **execution)
                runs.append(r)
                try:
                    from office2.smc import invariants as INV

                    k = int(np.searchsorted(arrs["m15"]["t"] + 900, end, side="right"))
                    iv = INV.run({kk: vv[max(0, k - 900):k] for kk, vv in arrs["m15"].items() if kk in ("t", "o", "h", "l", "c", "v")})
                    inv_out[sym] = {"bars": iv["bars"], "checks": iv["checks"], "violations": iv["violations"][:5], "n_violations": len(iv["violations"])}
                except Exception as exc:  # noqa: BLE001
                    inv_out[sym] = {"error": f"{type(exc).__name__}: {str(exc)[:80]}"}
                log(f"[smc-replay] {run_id} {sym}: барів {r['bars']}, подій {len(r['events'])}, {r['elapsed_s']} с")
                time.sleep(0.3)
            except Exception as exc:  # noqa: BLE001
                log(f"[smc-replay] {sym}: помилка {type(exc).__name__}: {str(exc)[:140]}")
        if not runs:
            continue
        summ = summarize(runs)
        summ["invariants_real_data"] = inv_out
        summ["window"] = {"decisions_until": end, "days": days, "outcome_data_until": fetch_end, "symbols": len(runs)}
        n = store(db, run_id, runs, summ)
        log(f"[smc-replay] {run_id}: збережено {n} подій; Brain {summ['engines']['BRAIN']['ready']}, SMC {summ['engines']['SMC']['ready']}, перетин {summ['overlap']['both']}")
        last = summ
    return last

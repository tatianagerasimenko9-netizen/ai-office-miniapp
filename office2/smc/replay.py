"""Time-frozen replay: Brain v2.1 і SMC на ОДНАКОВИХ закритих барах, без жодного майбутнього бару у вході рішення. Порівняння: READY-події, перетини, хибні READY, пропущені чисті рухи, R.
Результат — експлоративна діагностика, а не доказ прибутковості: вибірки малі, вихід — спрощений (TP1 / SL / горизонт на M15, SL першим при одному барі), комісія з office2.sim.
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


def simulate(m15: Arr, i0: int, direction: str, entry: float, sl: float, tp1: float, r_tp1: float, risk_pct: float, horizon: int = HORIZON_BARS) -> Dict[str, Any]:
    """Результат на M15 після бару i0 (вхід за ціною рішення): TP1 / SL / OPEN. Обидва в одному барі → SL (консервативно). R net = R − комісія/ризик%."""
    sg = 1.0 if direction == "LONG" else -1.0
    risk = abs(entry - sl)
    h, l, c = m15["h"][i0 + 1:i0 + 1 + horizon], m15["l"][i0 + 1:i0 + 1 + horizon], m15["c"][i0 + 1:i0 + 1 + horizon]
    if len(h) == 0 or risk <= 0:
        return {"outcome": "NO_DATA", "r_gross": None, "r_net": None, "mfe_r": None, "mae_r": None, "bars": 0}
    hit_sl = (l <= sl) if sg > 0 else (h >= sl)
    hit_tp = (h >= tp1) if sg > 0 else (l <= tp1)
    isl = int(np.argmax(hit_sl)) if hit_sl.any() else -1
    itp = int(np.argmax(hit_tp)) if hit_tp.any() else -1
    if isl >= 0 and (itp < 0 or isl <= itp):
        k, out, rg = isl, "SL", -1.0
    elif itp >= 0:
        k, out, rg = itp, "TP1", float(r_tp1)
    else:
        k, out = len(h) - 1, "OPEN"
        rg = float(sg * (c[-1] - entry) / risk)
    fav = float((h[:k + 1].max() - entry) / risk) if sg > 0 else float((entry - l[:k + 1].min()) / risk)
    adv = float((entry - l[:k + 1].min()) / risk) if sg > 0 else float((h[:k + 1].max() - entry) / risk)
    return {"outcome": out, "r_gross": rg, "r_net": SIM.net_r(rg, risk_pct), "mfe_r": fav, "mae_r": adv, "bars": k + 1, "complete": len(h) >= horizon or out != "OPEN"}


def _brain_ready(sym: str, ctx: Dict[str, Any], now: float, levels, mc, rel) -> List[Dict[str, Any]]:
    out = []
    for d in ("LONG", "SHORT"):
        th = B2.thesis(ctx, d, now, levels, 10.0, mc=mc, rel=rel, hooks=None)
        if th and th.get("state") == "READY":
            tg = th.get("targets") or []
            out.append({"source": "BRAIN", "model": th.get("kind", "SWEEP_SEQ"), "dir": d, "key": th.get("id"), "entry": float(th["entry"]), "sl": float(th["sl"]),
                        "tp1": float(tg[0]["p"]) if tg else None, "r_tp1": float(tg[0]["r"]) if tg else None, "risk_pct": float(th.get("risk_pct") or 0.0)})
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
                            "tp1": float(tg[0]["p"]) if tg else None, "r_tp1": float(tg[0]["r"]) if tg else None, "risk_pct": float(v.get("risk_pct") or 0.0)})
    return out


def replay_arrays(sym: str, arrs: Dict[str, Optional[Arr]], t_from: float, t_to: float, mc: Optional[Dict[str, Any]] = None, rel: Optional[Dict[str, Any]] = None,
                  with_brain: bool = True, with_smc: bool = True, log=None) -> Dict[str, Any]:
    """Прохід по барах M15 (закриття у (t_from, t_to]) із поступовим відкриттям даних. Повертає події READY обох рушіїв і підсумок."""
    m15 = arrs["m15"]
    ends = m15["t"] + 900
    idx = np.flatnonzero((ends > t_from) & (ends <= t_to))
    events: List[Dict[str, Any]] = []
    seen: set = set()
    t0 = time.time()
    for i in idx:
        now = float(ends[i])
        ctx = ctx_at(arrs, now)
        if ctx is None:
            continue
        levels = B.all_levels(ctx, now)
        found = []
        if with_brain:
            try:
                found += _brain_ready(sym, ctx, now, levels, mc, rel)
            except Exception as exc:  # noqa: BLE001
                events.append({"source": "BRAIN", "error": f"{type(exc).__name__}: {str(exc)[:100]}", "ts_bar": int(now)})
        if with_smc:
            try:
                found += _smc_ready(sym, ctx, now, levels)
            except Exception as exc:  # noqa: BLE001
                events.append({"source": "SMC", "error": f"{type(exc).__name__}: {str(exc)[:100]}", "ts_bar": int(now)})
        for f in found:
            kk = (f["source"], f["key"])
            if kk in seen:
                continue
            seen.add(kk)
            f.update(symbol=sym, ts_bar=int(now), i=int(i))
            if f.get("tp1") is not None and f["risk_pct"] > 0:
                f["sim"] = simulate(m15, int(i), f["dir"], f["entry"], f["sl"], f["tp1"], f["r_tp1"], f["risk_pct"])
            events.append(f)
    return {"symbol": sym, "events": events, "bars": int(len(idx)), "elapsed_s": round(time.time() - t0, 1), "opportunities": opportunities(m15, t_from, t_to)}


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


def summarize(runs: List[Dict[str, Any]], lead_bars: int = 16) -> Dict[str, Any]:
    """Підсумок по всіх символах: на рушій — кількість, TP1/SL/OPEN, середній R net (+bootstrap CI при n≥10), recall пропущених рухів, перетини."""
    ev = [e for r in runs for e in r["events"] if "error" not in e]
    errs = [e for r in runs for e in r["events"] if "error" in e]
    opp = [dict(o, symbol=r["symbol"]) for r in runs for o in r["opportunities"]]
    out: Dict[str, Any] = {"symbols": [r["symbol"] for r in runs], "bars": sum(r["bars"] for r in runs), "errors": len(errs), "engines": {}, "opportunities": len(opp)}
    for src in ("BRAIN", "SMC"):
        mine = [e for e in ev if e["source"] == src]
        sims = [e["sim"] for e in mine if e.get("sim") and e["sim"]["r_net"] is not None]
        rs = [s["r_net"] for s in sims]
        oc = {k: sum(1 for s in sims if s["outcome"] == k) for k in ("TP1", "SL", "OPEN")}
        res = oc["TP1"] + oc["SL"]
        caught = 0
        for o in opp:
            if any(e["symbol"] == o["symbol"] and e["dir"] == o["dir"] and o["ts_bar"] - lead_bars * 900 <= e["ts_bar"] <= o["ts_bar"] + 8 * 900 for e in mine):
                caught += 1
        out["engines"][src] = {"ready": len(mine), "long": sum(1 for e in mine if e["dir"] == "LONG"), "short": sum(1 for e in mine if e["dir"] == "SHORT"), "outcomes": oc,
                               "win_rate_resolved": round(oc["TP1"] / res, 3) if res else None, "mean_r_net": round(float(np.mean(rs)), 3) if rs else None, "r_net_ci95": bootstrap_ci(rs),
                               "false_ready_rate": round(oc["SL"] / len(sims), 3) if sims else None, "opportunities_caught": caught, "recall": round(caught / len(opp), 3) if opp else None,
                               "avg_bars_to_outcome": round(float(np.mean([s["bars"] for s in sims if s["outcome"] != "OPEN"])), 1) if any(s["outcome"] != "OPEN" for s in sims) else None}
    b = [e for e in ev if e["source"] == "BRAIN"]
    s = [e for e in ev if e["source"] == "SMC"]
    both = sum(1 for x in b if any(y["symbol"] == x["symbol"] and y["dir"] == x["dir"] and abs(y["ts_bar"] - x["ts_bar"]) <= 4 * 900 for y in s))
    out["overlap"] = {"both": both, "only_brain": len(b) - both, "only_smc": len(s) - sum(1 for y in s if any(x["symbol"] == y["symbol"] and x["dir"] == y["dir"] and abs(y["ts_bar"] - x["ts_bar"]) <= 4 * 900 for x in b))}
    out["caveats"] = ["експлоративно, не доказ прибутковості", "вихід спрощений: TP1/SL/горизонт 24 год на M15, SL першим при одному барі", "малі вибірки: довірчі інтервали ширші за відмінності між рушіями",
                      "SMC — shadow, пороги Brain для SL/цілей збережено (brain.targets_for)"]
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
    """spec: 'BTCUSDT,ETHUSDT,ONDOUSDT@days=5@end=1791400000' (end — epoch закриття останнього бару; за замовчуванням — останній закритий бар)."""
    parts = [x.strip() for x in spec.split("@")]
    syms = [s.strip().upper() for s in parts[0].split(",") if s.strip()]
    kv = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
    days = int(kv.get("days", 5))
    end = float(kv.get("end", (int(time.time()) // 900) * 900))
    run_id = kv.get("id") or f"smc-replay-{int(end)}-{days}d"
    init_db(db)
    runs = []
    for sym in syms:
        try:
            arrs = load_feed_arrays(feed, sym, end, days)
            if not arrs.get("m15"):
                log(f"[smc-replay] {sym}: немає даних")
                continue
            runs.append(replay_arrays(sym, arrs, end - days * 86400, end))
            log(f"[smc-replay] {sym}: барів {runs[-1]['bars']}, подій {len(runs[-1]['events'])}, {runs[-1]['elapsed_s']} с")
            time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001
            log(f"[smc-replay] {sym}: помилка {type(exc).__name__}: {str(exc)[:140]}")
    if not runs:
        return None
    summ = summarize(runs)
    n = store(db, run_id, runs, summ)
    log(f"[smc-replay] {run_id}: збережено {n} подій; Brain {summ['engines']['BRAIN']['ready']}, SMC {summ['engines']['SMC']['ready']}, перетин {summ['overlap']}")
    return summ

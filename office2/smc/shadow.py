"""SMC shadow: щоцикл рахує SMC-вердикти для всіх символів у ФОНІ (не блокує Brain/Telegram) і пише їх у office2_smc_shadow; знімок READY отримує display-only поле `smc`.
Нічого не змінює в рішеннях Brain v2.1 і не шле повідомлень. Вимкнення: OFFICE2_SMC=0."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from office2 import brain as B
from office2.smc import engine as EN
from office2.smc import overlay as OV

DDL = """CREATE TABLE IF NOT EXISTS office2_smc_shadow (
    ts_bar BIGINT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, model TEXT NOT NULL, version TEXT NOT NULL,
    state TEXT NOT NULL, stage INTEGER, brain_state TEXT, ms DOUBLE PRECISION, payload_json TEXT NOT NULL, created_ts DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ts_bar, symbol, direction, model, version))"""
STORE_STATES = ("READY", "NO_TRADE", "ARMED", "MISSED", "CANDIDATE")
_LOCK = threading.Lock()
_STATS: Dict[str, Any] = {"cycles": 0, "symbols": 0, "errors": 0, "last_ms": 0.0, "max_symbol_ms": 0.0, "last_error": None, "rows": 0}


def enabled() -> bool:
    return os.environ.get("OFFICE2_SMC", "1") not in ("0", "false", "off")


def stats() -> Dict[str, Any]:
    with _LOCK:
        return dict(_STATS)


def init_db(db: str) -> None:
    from office_bridge import _execute

    _execute(db, DDL)


def analyze_ctx(sym: str, ctx: Dict[str, Any], now: float, with_events: bool = True) -> Dict[str, Any]:
    levels = B.all_levels(ctx, now)
    return EN.analyze(ctx, now, sym, real_levels=levels, with_events=with_events)


def snapshot_for(sym: str, ctx: Dict[str, Any], now: float, direction: str) -> Optional[Dict[str, Any]]:
    """Display-only блок для знімка READY: що бачить SMC у цьому напрямі ЗАРАЗ (на момент рішення). Не впливає на READY. Помилка → None."""
    if not enabled():
        return None
    try:
        t0 = time.perf_counter()
        r = analyze_ctx(sym, ctx, now)
        if r.get("error"):
            return {"state": "UNVERIFIED", "reason": r["error"]}
        ms = r["models"].get(direction, {})
        best = EN._best([v for v in ms.values() if v])
        m15 = ctx["m15"]
        import numpy as np

        from office2 import features as F

        k = F.last_closed(m15, 900, now)
        m15c = {kk: vv[:k + 1] for kk, vv in m15.items() if hasattr(vv, "__len__") and kk in ("t", "o", "h", "l", "c")}
        ov = OV.build(best, m15c, r.get("events"))
        agree = bool(best and best["state"] == "READY")
        return {"version": EN.VERSION, "detector_version": r["detector_version"], "dir": direction, "agrees_ready": agree, "state": best["state"] if best else "NONE", "model": best["model"] if best else None,
                "reason": best.get("reason") if best else "SMC не бачить жодної моделі в цьому напрямі", "overlay": ov, "structure": r["structure"], "sync": r["sync"], "judas": r["judas"], "amd": r["amd"],
                "sessions": {"source_clock": r["sessions"]["source_clock"], "nym": r["sessions"]["nym"]}, "timing_ms": round((time.perf_counter() - t0) * 1000, 1), "role": "SHADOW (не впливає на READY)"}
    except Exception as exc:  # noqa: BLE001
        with _LOCK:
            _STATS["errors"] += 1
            _STATS["last_error"] = f"snapshot {sym}: {type(exc).__name__}: {str(exc)[:120]}"
        return None


def run_cycle(db: str, ctxs: Dict[str, Dict[str, Any]], now: float, brain_states: Optional[Dict[Any, str]] = None, log=print) -> Dict[str, Any]:
    """Прохід по символах циклу; пише рядки лише для суттєвих станів. Викликається з окремого потоку."""
    from office_bridge import _execute

    t0 = time.perf_counter()
    ts_bar = int(now)
    n_rows = 0
    mx = 0.0
    per_state: Dict[str, int] = {}
    for sym, ctx in ctxs.items():
        t1 = time.perf_counter()
        try:
            r = analyze_ctx(sym, ctx, now, with_events=False)
            if r.get("error"):
                continue
            for d, mods in r["models"].items():
                for model, v in mods.items():
                    if not v:
                        continue
                    per_state[v["state"]] = per_state.get(v["state"], 0) + 1
                    if v["state"] not in STORE_STATES and not (v["state"] == "WAIT" and v.get("stage", 0) >= 5):
                        continue
                    ms = (time.perf_counter() - t1) * 1000.0
                    payload = {k: v.get(k) for k in ("steps", "zone", "pois", "entry", "sl", "targets", "risk_pct", "risk_atr15", "reason", "need", "bias", "htf_context", "leg", "sweep", "obstacles_before_tp1", "chronology_ok")}
                    bs = (brain_states or {}).get((sym, d))
                    _execute(db, "INSERT INTO office2_smc_shadow (ts_bar, symbol, direction, model, version, state, stage, brain_state, ms, payload_json, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                                 "ON CONFLICT (ts_bar, symbol, direction, model, version) DO NOTHING",
                             (ts_bar, sym, d, model, EN.VERSION, v["state"], int(v.get("stage", 0)), bs, float(ms), json.dumps(payload, ensure_ascii=False, default=float), time.time()))
                    n_rows += 1
        except Exception as exc:  # noqa: BLE001
            with _LOCK:
                _STATS["errors"] += 1
                _STATS["last_error"] = f"{sym}: {type(exc).__name__}: {str(exc)[:120]}"
        mx = max(mx, (time.perf_counter() - t1) * 1000.0)
    tot = (time.perf_counter() - t0) * 1000.0
    with _LOCK:
        _STATS.update(cycles=_STATS["cycles"] + 1, symbols=len(ctxs), last_ms=round(tot, 1), max_symbol_ms=round(mx, 1), rows=_STATS["rows"] + n_rows)
    log(f"[o2smc] цикл {ts_bar}: символів {len(ctxs)}, рядків {n_rows}, стани {per_state}, {tot / 1000:.1f} с (макс. символ {mx:.0f} мс)")
    return {"rows": n_rows, "ms": tot, "states": per_state}

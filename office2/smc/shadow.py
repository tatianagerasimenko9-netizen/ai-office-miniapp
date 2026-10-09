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


def _m15_closed(ctx: Dict[str, Any], k: int) -> Dict[str, Any]:
    m = ctx["m15"]
    return {kk: m[kk][:k + 1] for kk in ("t", "o", "h", "l", "c")}


def run_cycle(db: str, ctxs: Dict[str, Dict[str, Any]], now: float, brain_states: Optional[Dict[Any, str]] = None, log=print) -> Dict[str, Any]:
    """Прохід по символах циклу. Пише: (а) рядки моделей у суттєвих станах з overlay, (б) по одному рядку BEST на символ і напрям на КОЖЕН бар — щоб потім пояснити розбіжність із Brain
    (що саме бачив SMC на момент READY Brain). Викликається з окремого потоку. Старші за 30 діб рядки видаляються."""
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
            m15c = _m15_closed(ctx, r["k"])
            for d, mods in r["models"].items():
                vs = [v for v in mods.values() if v]
                best = EN._best(vs)
                bs = (brain_states or {}).get((sym, d))
                if best is not None:
                    n_rows += _put(_execute, db, ts_bar, sym, d, "BEST", best, bs, (time.perf_counter() - t1) * 1000.0, None)
                for model, v in mods.items():
                    if not v:
                        continue
                    per_state[v["state"]] = per_state.get(v["state"], 0) + 1
                    if v["state"] not in STORE_STATES and not (v["state"] == "WAIT" and v.get("stage", 0) >= 5):
                        continue
                    ov = OV.build(v, m15c, None) if v["state"] in ("READY", "ARMED", "NO_TRADE", "CANDIDATE") else None
                    n_rows += _put(_execute, db, ts_bar, sym, d, model, v, bs, (time.perf_counter() - t1) * 1000.0, ov)
        except Exception as exc:  # noqa: BLE001
            with _LOCK:
                _STATS["errors"] += 1
                _STATS["last_error"] = f"{sym}: {type(exc).__name__}: {str(exc)[:120]}"
        mx = max(mx, (time.perf_counter() - t1) * 1000.0)
    try:
        _execute(db, "DELETE FROM office2_smc_shadow WHERE ts_bar < ?", (int(now - RETENTION_DAYS * 86400),))
    except Exception:  # noqa: BLE001
        pass
    tot = (time.perf_counter() - t0) * 1000.0
    with _LOCK:
        _STATS.update(cycles=_STATS["cycles"] + 1, symbols=len(ctxs), last_ms=round(tot, 1), max_symbol_ms=round(mx, 1), rows=_STATS["rows"] + n_rows)
    log(f"[o2smc] цикл {ts_bar}: символів {len(ctxs)}, рядків {n_rows}, стани {per_state}, {tot / 1000:.1f} с (макс. символ {mx:.0f} мс)")
    return {"rows": n_rows, "ms": tot, "states": per_state}


RETENTION_DAYS = 30


def _put(execute, db: str, ts_bar: int, sym: str, d: str, model: str, v: Dict[str, Any], brain_state: Optional[str], ms: float, overlay: Optional[Dict[str, Any]]) -> int:
    payload = {k: v.get(k) for k in ("steps", "zone", "pois", "entry", "sl", "targets", "risk_pct", "risk_atr15", "reason", "need", "bias", "htf_context", "leg", "sweep", "obstacles_before_tp1", "chronology_ok", "model", "aggressive_entry")}
    if overlay:
        payload["overlay"] = overlay
    execute(db, "INSERT INTO office2_smc_shadow (ts_bar, symbol, direction, model, version, state, stage, brain_state, ms, payload_json, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (ts_bar, symbol, direction, model, version) DO NOTHING",
            (ts_bar, sym, d, model, EN.VERSION, v["state"], int(v.get("stage", 0)), brain_state, float(ms), json.dumps(payload, ensure_ascii=False, default=float), time.time()))
    return 1


def feed(db: str, days: float = 3.0, limit: int = 30, now: Optional[float] = None) -> Dict[str, Any]:
    """Розбіжності Brain ↔ SMC за останні дні: SMC READY без Brain, Brain READY без SMC, збіги. Кожен елемент пояснює, що саме бачили обидва на тому барі; повний overlay — через row_detail."""
    from office_bridge import _fetchall

    now = float(now if now is not None else time.time())
    cut = int(now - days * 86400)
    out: List[Dict[str, Any]] = []
    try:
        smc = _fetchall(db, "SELECT ts_bar, symbol, direction, model, state, stage, brain_state FROM office2_smc_shadow WHERE ts_bar >= ? AND model != 'BEST' AND state IN ('READY','ARMED') ORDER BY ts_bar DESC", (cut,))
        best = _fetchall(db, "SELECT ts_bar, symbol, direction, state, stage, payload_json FROM office2_smc_shadow WHERE ts_bar >= ? AND model = 'BEST'", (cut,))
        brain = _fetchall(db, "SELECT scenario_id, symbol, direction, created_ts FROM office2_live_signal WHERE created_ts >= ? ORDER BY created_ts DESC", (cut,))
    except Exception:  # noqa: BLE001
        return {"items": [], "note": "shadow ще порожній"}
    bmap = {(r[1], r[2], r[0]): r for r in best}
    seen_b = set()
    for sid, sym, d, ct in brain:
        key = (sym, d, int(ct) // 900)
        if key in seen_b:
            continue
        seen_b.add(key)
        tb = int(ct) // 900 * 900
        same = [r for r in smc if r[1] == sym and r[2] == d and abs(r[0] - tb) <= 3600]
        if same:
            r = same[0]
            out.append({"id": f"{r[0]}|{sym}|{d}|{r[3]}", "ts": r[0], "symbol": sym, "dir": d, "relation": "BOTH", "smc_state": r[4], "model": r[3], "brain_scenario": sid,
                        "why": f"Brain READY і SMC {r[4]} ({r[3]}) у межах години: обидва бачать один напрям"})
        else:
            bb = bmap.get((sym, d, tb)) or next((bmap[(sym, d, x)] for x in (tb - 900, tb + 900, tb - 1800) if (sym, d, x) in bmap), None)
            why = "SMC не мав даних на цей бар (shadow ще не працював)"
            if bb:
                pl = json.loads(bb[5] or "{}")
                why = f"Brain READY, а SMC на тому барі: {bb[3]} (етап {bb[4]}) — {pl.get('reason') or '—'}"
            out.append({"id": f"{tb}|{sym}|{d}|BEST", "ts": tb, "symbol": sym, "dir": d, "relation": "BRAIN_ONLY", "smc_state": bb[3] if bb else None, "model": None, "brain_scenario": sid, "why": why})
    for r in smc:
        if not any(o["ts"] == r[0] and o["symbol"] == r[1] and o["dir"] == r[2] and o["relation"] == "BOTH" for o in out) and not any(o["symbol"] == r[1] and o["dir"] == r[2] and abs(o["ts"] - r[0]) <= 3600 and o["relation"] == "BOTH" for o in out):
            out.append({"id": f"{r[0]}|{r[1]}|{r[2]}|{r[3]}", "ts": r[0], "symbol": r[1], "dir": r[2], "relation": "SMC_ONLY", "smc_state": r[4], "model": r[3],
                        "why": f"SMC {r[4]} ({r[3]}); Brain на цей момент: {r[6] or 'сценарію немає'}"})
    out.sort(key=lambda x: -x["ts"])
    return {"items": out[:limit], "days": days, "note": "SHADOW: розбіжність ≠ помилка. Результат SMC-сигналів окремо не оцінювався"}


def row_detail(db: str, rid: str) -> Optional[Dict[str, Any]]:
    from office_bridge import _fetchone

    try:
        ts, sym, d, model = rid.split("|")
        row = _fetchone(db, "SELECT state, stage, brain_state, payload_json FROM office2_smc_shadow WHERE ts_bar=? AND symbol=? AND direction=? AND model=? ORDER BY created_ts DESC LIMIT 1", (int(ts), sym, d, model))
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    pl = json.loads(row[3] or "{}")
    return {"id": rid, "ts": int(ts), "symbol": sym, "dir": d, "model": model, "state": row[0], "stage": row[1], "brain_state": row[2], "payload": pl, "overlay": pl.get("overlay"),
            "role": "SHADOW (не впливає на READY)"}


def shadow_stats(db: str, days: float = 14.0, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Підсумок shadow для Журналу: скільки вердиктів, READY за SMC, збіг із READY Brain (±1 год, той самий напрямок). Нічого не вигадує: порожня таблиця → None."""
    from office_bridge import _fetchall

    if not enabled():
        return None
    now = float(now if now is not None else time.time())
    cut = int(now - days * 86400)
    try:
        rows = _fetchall(db, "SELECT symbol, direction, model, state, ts_bar, ms FROM office2_smc_shadow WHERE ts_bar >= ? AND model != 'BEST'", (cut,))
        brain = _fetchall(db, "SELECT symbol, direction, created_ts FROM office2_live_signal WHERE created_ts >= ?", (cut,))
    except Exception:  # noqa: BLE001
        return None
    if not rows and not brain:
        return None
    states: Dict[str, int] = {}
    for r in rows:
        states[r[3]] = states.get(r[3], 0) + 1
    smc_ready = [r for r in rows if r[3] == "READY"]
    smc_near = [r for r in rows if r[3] in ("READY", "ARMED")]
    seen, b_conf = set(), 0
    for sym, d, ct in brain:
        key = (sym, d, int(ct) // 900)
        if key in seen:
            continue
        seen.add(key)
        if any(r[0] == sym and r[1] == d and float(ct) - 3600 <= r[4] <= float(ct) + 900 for r in smc_near):
            b_conf += 1
    n_brain = len(seen)
    s_both = sum(1 for r in smc_ready if any(sym == r[0] and d == r[1] and abs(float(ct) - r[4]) <= 3600 for sym, d, ct in brain))
    ms = [float(r[5]) for r in rows if r[5] is not None]
    try:
        recent = feed(db, days=3.0, limit=8, now=now).get("items", [])
    except Exception:  # noqa: BLE001
        recent = []
    return {"days": days, "recent": recent, "rows": len(rows), "states": states, "smc_ready": len(smc_ready), "by_model": {m: sum(1 for r in smc_ready if r[2] == m) for m in ("REVERSAL", "CONTINUATION")},
            "brain_ready": n_brain, "brain_ready_confirmed_by_smc": b_conf, "smc_ready_also_brain": s_both, "smc_ready_only": len(smc_ready) - s_both,
            "avg_ms": round(sum(ms) / len(ms), 1) if ms else None, "max_ms": round(max(ms), 1) if ms else None, "runtime": stats(),
            "note": "SHADOW: SMC не впливає на READY. Збіг ≠ правильність: результат SMC-сигналів окремо не оцінювався (потрібен replay/live-вибірка)"}

"""WATCH_ONLY для DYNAMIC-монет: той самий Brain v2.1 рахує тези, але нічого не йде в LIVE READY / Telegram / office2_live_scenario / outbox.

Що зберігається (office2_dynamic_candidate): кожна теза з її станом (WATCH/WAIT/READY/NO_TRADE/MISSED), рівні входу/SL/TP1/TP2 для «умовного READY»,
причина відхилення, і paper-наслідок за реальними Binance-свічками (SL/TP1/TP2/EXPIRED) з комісіями+slippage. Це спостереження для накопичення статистики,
а не торговий сигнал і не особиста угода. Перехід у LIVE — лише окремим рішенням власниці (OFFICE2_DYNAMIC_UNIVERSE=live).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional

TTL_SEC = 48 * 3600
DDL = ("""CREATE TABLE IF NOT EXISTS office2_dynamic_candidate (
    cand_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, kind TEXT, state TEXT NOT NULL,
    first_ts BIGINT NOT NULL, updated_ts BIGINT NOT NULL, ready_ts BIGINT, entry DOUBLE PRECISION, sl DOUBLE PRECISION,
    tp1 DOUBLE PRECISION, tp2 DOUBLE PRECISION, stop_pct DOUBLE PRECISION, reason TEXT, outcome TEXT, outcome_ts BIGINT,
    r_gross DOUBLE PRECISION, r_net DOUBLE PRECISION, thesis_json TEXT, meta_json TEXT)""",)
_READY_TABLE = {"done": False}


def mode() -> str:
    """off | watch | live. ЛИШЕ явне 'live' повертає динамічні монети в основний цикл (LIVE READY); будь-яке інше «увімкнено» = watch."""
    v = os.getenv("OFFICE2_DYNAMIC_UNIVERSE", "").strip().lower()
    if v == "live":
        return "live"
    if v in ("1", "true", "yes", "on", "watch", "watch_only"):
        return "watch"
    return "off"


def _ensure(db: str) -> None:
    if _READY_TABLE["done"]:
        return
    from office_bridge import _execute

    for d in DDL:
        _execute(db, d)
    _READY_TABLE["done"] = True


def _f(x) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def record(db: str, sym: str, th: Dict[str, Any], now: float, meta: Optional[Dict[str, Any]] = None) -> str:
    """Upsert однієї тези. Повертає нормалізований стан. READY фіксується один раз (ready_ts/рівні не переписуються)."""
    from office_bridge import _execute, _fetchall

    _ensure(db)
    cid = str(th["id"])
    state = str(th.get("state") or "WATCH")
    row = _fetchall(db, "SELECT state, ready_ts FROM office2_dynamic_candidate WHERE cand_id = ?", (cid,))
    tg = th.get("targets") or []
    entry, sl = _f(th.get("entry")), _f(th.get("sl"))
    tp1 = _f(tg[0]["p"]) if len(tg) > 0 else None
    tp2 = _f(tg[1]["p"]) if len(tg) > 1 else None
    stop_pct = _f((th.get("sizing") or {}).get("stop_pct"))
    js = json.dumps(th, ensure_ascii=False, default=str)[:20000]
    mj = json.dumps(meta or {}, ensure_ascii=False, default=str)[:2000]
    if not row:
        _execute(db, """INSERT INTO office2_dynamic_candidate(cand_id, symbol, direction, kind, state, first_ts, updated_ts, ready_ts, entry, sl, tp1, tp2, stop_pct, reason, thesis_json, meta_json)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (cand_id) DO NOTHING""",
                 (cid, sym, th.get("dir"), th.get("kind"), state, int(now), int(now), int(now) if state == "READY" else None, entry, sl, tp1, tp2, stop_pct,
                  str(th.get("reason", ""))[:400], js, mj))
        return state
    prev_state, ready_ts = row[0][0], row[0][1]
    if ready_ts is not None:      # умовний READY уже зафіксований: рівні й час не чіпаємо, лише оновлюємо спостереження за станом
        _execute(db, "UPDATE office2_dynamic_candidate SET updated_ts = ? WHERE cand_id = ?", (int(now), cid))
        return str(prev_state)
    if state == "READY":
        _execute(db, "UPDATE office2_dynamic_candidate SET state=?, updated_ts=?, ready_ts=?, entry=?, sl=?, tp1=?, tp2=?, stop_pct=?, reason=?, thesis_json=? WHERE cand_id=?",
                 (state, int(now), int(now), entry, sl, tp1, tp2, stop_pct, str(th.get("reason", ""))[:400], js, cid))
    else:
        _execute(db, "UPDATE office2_dynamic_candidate SET state=?, updated_ts=?, reason=?, thesis_json=? WHERE cand_id=?",
                 (state, int(now), str(th.get("reason", ""))[:400], js, cid))
    return state


def observe(db: str, sym: str, ctx: Dict[str, Any], mc: Dict[str, Any], rel: Dict[str, Any], now: float, meta: Optional[Dict[str, Any]] = None,
            flow_fetch=None, m5_fetch=None) -> Dict[str, int]:
    """Brain v2.1 для однієї DYNAMIC-монети БЕЗ побічних ефектів на LIVE: ні save_scenario, ні emit_ready, ні outbox."""
    from office2 import brain as B
    from office2 import brain2 as B2
    from office2 import engine as EN

    res = {"watch": 0, "wait": 0, "ready": 0, "other": 0}
    levels = B.all_levels(ctx, now)
    for d in ("LONG", "SHORT"):
        th = B2.thesis(ctx, d, now, levels, EN.RISK_USD, mc=mc, rel=rel, hooks={"flow": flow_fetch, "m5": m5_fetch})
        if not th:
            continue
        th = dict(th, id=EN.scoped_id(sym, th["id"]), symbol=sym)
        st = record(db, sym, th, now, meta)
        res[{"WATCH": "watch", "WAIT": "wait", "READY": "ready"}.get(st, "other")] += 1
    return res


def paper_outcome(m: Dict[str, Any], ready_ts: float, direction: str, entry: float, sl: float, tp1: float, tp2: Optional[float], stop_pct: Optional[float],
                  now: float) -> Optional[Dict[str, Any]]:
    """Чесний paper-наслідок за закритими M15-барами ПІСЛЯ бару READY (t > ready_ts). Усередині бару, де є і SL, і ціль, — SL (консервативно).
    Модель A: уся позиція закривається на TP1. R мінус витрати (0.15%/стоп). Нема даних → None (не вигадуємо)."""
    from office2.learning import costs as C

    sg = 1.0 if direction == "LONG" else -1.0
    risk = sg * (entry - sl)
    if risk <= 0 or not tp1:
        return None
    r1 = abs(tp1 - entry) / risk
    t, h, l = m["t"], m["h"], m["l"]
    hit1: Optional[float] = None
    for i in range(len(t)):
        if float(t[i]) <= ready_ts or float(t[i]) + 900 > now:
            continue          # лише бари після READY і вже закриті
        hi, lo = float(h[i]), float(l[i])
        sl_hit = lo <= sl if sg > 0 else hi >= sl
        tp1_hit = hi >= tp1 if sg > 0 else lo <= tp1
        tp2_hit = bool(tp2) and (hi >= tp2 if sg > 0 else lo <= tp2)
        if hit1 is None:
            if sl_hit:
                return _fin("SL", -1.0, stop_pct, float(t[i]), C)
            if tp1_hit:
                hit1 = float(t[i])
                return _fin("TP2" if tp2_hit else "TP1", r1, stop_pct, hit1, C)
    if now - ready_ts >= TTL_SEC:
        return _fin("EXPIRED", 0.0, stop_pct, ready_ts + TTL_SEC, C)
    return None


def _fin(code: str, r_gross: float, stop_pct: Optional[float], ts: float, C) -> Dict[str, Any]:
    cr = C.cost_r(stop_pct)
    return {"outcome": code, "outcome_ts": int(ts), "r_gross": r_gross, "r_net": (r_gross - cr) if cr is not None else None}


def resolve(db: str, feed: Any, now: float, limit: int = 8) -> int:
    from office_bridge import _execute, _fetchall

    _ensure(db)
    rows = _fetchall(db, "SELECT cand_id, symbol, direction, ready_ts, entry, sl, tp1, tp2, stop_pct FROM office2_dynamic_candidate "
                         "WHERE ready_ts IS NOT NULL AND outcome IS NULL ORDER BY ready_ts LIMIT ?", (limit,))
    n = 0
    for cid, sym, d, rts, entry, sl, tp1, tp2, stop_pct in rows:
        try:
            m = feed.klines(sym, "15m", now, limit=240, start_ms=int(rts * 1000))
        except Exception:  # noqa: BLE001
            continue
        if not m or not len(m.get("t", [])):
            continue
        o = paper_outcome(m, float(rts), d, float(entry), float(sl), float(tp1), _f(tp2), _f(stop_pct), now)
        if o:
            _execute(db, "UPDATE office2_dynamic_candidate SET outcome=?, outcome_ts=?, r_gross=?, r_net=? WHERE cand_id=?",
                     (o["outcome"], o["outcome_ts"], o["r_gross"], o["r_net"], cid))
            n += 1
    return n


def summary(db: str, limit: int = 40) -> Dict[str, Any]:
    from office2 import dynamic_universe as DYN
    from office_bridge import _fetchall

    out: Dict[str, Any] = {"mode": mode(), "meaning": "WATCH_ONLY: спостереження, не торговий сигнал; у Telegram не йде", "universe": DYN.snapshot(), "stats": {}, "items": []}
    try:
        _ensure(db)
        rows = _fetchall(db, "SELECT symbol, direction, kind, state, first_ts, updated_ts, ready_ts, entry, sl, tp1, tp2, reason, outcome, outcome_ts, r_net FROM office2_dynamic_candidate "
                             "ORDER BY updated_ts DESC LIMIT ?", (limit,))
        cols = ("symbol", "direction", "kind", "state", "first_ts", "updated_ts", "ready_ts", "entry", "sl", "tp1", "tp2", "reason", "outcome", "outcome_ts", "r_net")
        out["items"] = [dict(zip(cols, r)) for r in rows]
        agg = _fetchall(db, "SELECT COUNT(*), SUM(CASE WHEN ready_ts IS NOT NULL THEN 1 ELSE 0 END), SUM(CASE WHEN outcome IS NOT NULL THEN 1 ELSE 0 END), "
                            "SUM(CASE WHEN outcome IN ('TP1','TP2') THEN 1 ELSE 0 END), SUM(CASE WHEN outcome='SL' THEN 1 ELSE 0 END), SUM(COALESCE(r_net,0)) "
                            "FROM office2_dynamic_candidate")[0]
        tot, rdy, done, wins, losses, rsum = (agg[0] or 0, agg[1] or 0, agg[2] or 0, agg[3] or 0, agg[4] or 0, agg[5] or 0.0)
        out["stats"] = {"candidates": tot, "would_be_ready": rdy, "resolved": done, "tp": wins, "sl": losses, "open": rdy - done, "sum_r_net": round(float(rsum), 3),
                        "model_pnl_usd": round(float(rsum) * 10.0, 2), "note": "модель (не реальні гроші): ризик $10, комісія+slippage 0.15% кола; n<30 — лише спостереження"}
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return out

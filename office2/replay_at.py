"""Реплей рішення Brain на момент часу БЕЗ lookahead: HTF і M15 береться з klines з endTime = момент рішення (лише бари, закриті до нього), далі той самий конвеєр
brain2.thesis (карта TF, докази ДО рішення, цілісна теза). Нічого не відправляє й не пише в сценарії/lifecycle; результат — у office2_replay_result і в лог.
Вхід: OFFICE2_REPLAY_AT="ETHUSDT@1791361800,SEIUSDT@1791363600" (symbol@epoch_sec_закриття_бару)."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import numpy as np

from office2 import brain as B
from office2 import brain2 as B2
from office2 import features as F

DDL = """CREATE TABLE IF NOT EXISTS office2_replay_result (
    symbol TEXT NOT NULL, ts BIGINT NOT NULL, direction TEXT NOT NULL, version TEXT NOT NULL, result_json TEXT NOT NULL, created_ts DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (symbol, ts, direction, version))"""


def ctx_at(feed: Any, sym: str, ts: float) -> Optional[Dict[str, Any]]:
    """Контекст на момент ts: кожен TF — останні N барів, закритих ≤ ts."""
    from office2.live import TF_LIMIT

    end = int(ts * 1000) - 1
    bars: Dict[str, Any] = {}
    for tf in ("15m", "4h", "1d", "1w", "1M"):
        bars[tf] = feed.klines(sym, tf, ts, limit=TF_LIMIT.get(tf, 500), end_ms=end)
    m15, h4, d1, w1 = bars["15m"], bars["4h"], bars["1d"], bars["1w"]
    if not (m15 and h4 and d1 and w1) or len(m15["t"]) < 60:
        return None
    return B.build_full_ctx(m15, h4, d1, w1, bars["1M"])


def market_at(feed: Any, sym: str, ctx: Dict[str, Any], ts: float) -> Dict[str, Any]:
    """Мінімальний ринковий контекст на момент: BTC за 1г і відносна сила монети (лише з того, що було відоме)."""
    def ret1h(m15: Dict[str, Any]) -> Optional[float]:
        k = F.last_closed(m15, 900, ts)
        return float((m15["c"][k] / m15["c"][k - 4] - 1.0) * 100.0) if k >= 4 else None

    btc = ctx if sym == "BTCUSDT" else ctx_btc(feed, ts)
    b = ret1h(btc["m15"]) if btc else None
    c = ret1h(ctx["m15"])
    rel = {"coin_ret_1h": c, "rs_vs_btc_1h": (c - b) if (b is not None and c is not None) else None}
    return {"btc_ret_1h": b}, rel


def ctx_btc(feed: Any, ts: float) -> Optional[Dict[str, Any]]:
    m15 = feed.klines("BTCUSDT", "15m", ts, limit=120, end_ms=int(ts * 1000) - 1)
    return {"m15": m15} if m15 else None


def decide_at(feed: Any, sym: str, ts: float, hooks: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = ctx_at(feed, sym, ts)
    if ctx is None:
        return {"symbol": sym, "ts": ts, "error": "немає даних"}
    mc, rel = market_at(feed, sym, ctx, ts)
    levels = B.all_levels(ctx, ts)
    out: Dict[str, Any] = {"symbol": sym, "ts": ts, "version": B2.VERSION, "price": float(ctx["m15"]["c"][F.last_closed(ctx["m15"], 900, ts)]), "directions": {}}
    for d in ("LONG", "SHORT"):
        th = B2.thesis(ctx, d, ts, levels, 10.0, mc=mc, rel=rel, hooks=hooks)
        if th is None:
            out["directions"][d] = {"state": "NONE", "reason": "подій немає"}
            continue
        r = {"state": th["state"], "reason": th.get("reason"), "kind": th.get("kind"), "sequence": th.get("sequence")}
        for k in ("entry", "entry_zone", "sl", "targets", "quality", "integral", "map", "event", "level", "invalidation"):
            if th.get(k) is not None:
                r[k] = th[k]
        if th.get("integral"):
            r["integral"] = {k: v for k, v in th["integral"].items() if k != "inputs"}
        out["directions"][d] = r
    return out


def run_jobs(db: str, feed: Any, spec: str, log: Any = print) -> int:
    from office_bridge import _execute

    _execute(db, DDL)
    n = 0
    for part in [x.strip() for x in spec.split(",") if x.strip()]:
        try:
            sym, ts_s = part.split("@")
            ts = float(ts_s)
        except ValueError:
            log(f"[replay] некоректний елемент {part!r}")
            continue
        try:
            res = decide_at(feed, sym.strip().upper(), ts)
        except Exception as exc:  # noqa: BLE001
            res = {"symbol": sym, "ts": ts, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
        for d, r in (res.get("directions") or {"ERR": res}).items():
            _execute(db, "INSERT INTO office2_replay_result(symbol, ts, direction, version, result_json, created_ts) VALUES (?,?,?,?,?,?) ON CONFLICT (symbol, ts, direction, version) DO UPDATE SET result_json=excluded.result_json, created_ts=excluded.created_ts",
                     (sym.strip().upper(), int(ts), d, B2.VERSION, json.dumps(r, ensure_ascii=False, default=lambda o: (float(o) if isinstance(o, (np.floating, np.integer)) else str(o))), time.time()))
        n += 1
        log(f"[replay] {sym}@{int(ts)}: " + "; ".join(f"{d}={r.get('state')}" for d, r in (res.get('directions') or {}).items()))
    return n

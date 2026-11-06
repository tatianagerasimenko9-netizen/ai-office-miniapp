"""Живий цикл Market Brain (РЕЖИМ СПОСТЕРЕЖЕННЯ): збирає ознаки BTC з реальних даних, веде пам'ять станів, пише журнал. У Telegram НІЧОГО не шле.

Журнал (office_events): MARKET_BRAIN_SNAP — стислий знімок ознак раз на SNAP_SEC (для власного дослідження на живих даних без look-ahead);
MARKET_BRAIN_TRANSITION — кожен перехід стану з причиною, рівнями й знімком; MARKET_BRAIN_REASSESS — що новий стан означає для активних READY
(у спостереженні — лише запис, «було б скасовано» нічого не скасовує). Пам'ять відновлюється з останнього переходу після перезапуску.
Джерела: свічки Binance (office_market_data.fetch_candles), OI/співвідношення з кроком 5 хв і funding — прямі запити fapi через ті самі пейсинг/паузи.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

import office_brain_features as bf
import office_market_brain as mb

SNAP_SEC = 300.0
BASKET = ("ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC", "TRX")


def _candles(sym: str, tf: str, n: int) -> List[Dict[str, Any]]:
    from office_market_data import fetch_candles

    r = fetch_candles(sym, tf, n)
    return r if isinstance(r, list) else []


def _http(url: str, params: Dict[str, Any]) -> Any:
    from office_market_data import _http_get_json

    return _http_get_json(url, params)


def gather(now: float, *, candles: Callable[[str, str, int], List[Dict[str, Any]]] = _candles,
           http: Callable[[str, Dict[str, Any]], Any] = _http, symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """Ознаки на момент now: лише закриті свічки; OI/співвідношення — точки з часом ≤ now (запізнення 5 хв, як у дослідженні)."""
    import office_time_structure as ts

    c5, c15, d1 = candles(symbol, "5m", 70), candles(symbol, "15m", 110), candles(symbol, "1d", 120)
    closed_days = bf.upto(d1, now, 86400.0)
    price = float(c5[-1]["close"]) if c5 else None
    snap = ts.snapshot(now, price, closed_days) if closed_days and price else {}
    oi_hist, ls, fu = [], None, None
    try:
        oh = http("https://fapi.binance.com/futures/data/openInterestHist", {"symbol": symbol, "period": "5m", "limit": 14})
        oi_hist = [{"ts": float(x["timestamp"]) / 1000.0 + 300.0, "oi": float(x["sumOpenInterest"])} for x in (oh or [])]
    except Exception:  # noqa: BLE001
        oi_hist = []
    try:
        lr = http("https://fapi.binance.com/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": "5m", "limit": 2})
        rows = [x for x in (lr or []) if float(x["timestamp"]) / 1000.0 + 300.0 <= now]
        ls = float(rows[-1]["longShortRatio"]) if rows else None
    except Exception:  # noqa: BLE001
        ls = None
    try:
        pi = http("https://fapi.binance.com/fapi/v1/premiumIndex", {"symbol": symbol})
        fu = float(pi["lastFundingRate"]) * 100.0
    except Exception:  # noqa: BLE001
        fu = None
    bn, bt = {}, {}
    sl = int(now // 300) * 300 - 300
    for s in BASKET:
        try:
            cs = candles(s + "USDT", "5m", 16)
        except Exception:  # noqa: BLE001
            continue
        by = {int(bf._t(c) or 0): float(c["close"]) for c in cs}
        if by.get(sl) and by.get(sl - 3600):
            bn[s], bt[s] = by[sl], by[sl - 3600]
    eth15 = candles("ETHUSDT", "15m", 10)
    return bf.compute(now, c1=[], c5=c5, c15=c15, daily=d1, week=(snap.get("week") if snap else None), month=(snap.get("month") if snap else None),
                      oi_hist=oi_hist, funding_pct=fu, ls_ratio=ls, basket_now=bn, basket_then=bt, eth_c15=eth15)


# ------------------------------------------------------------------ пам'ять у журналі
def load_memory(db: str) -> Dict[str, Any]:
    import office_signal_track as trk

    mem = mb.new_memory()
    ev = trk._events(db, "MARKET_BRAIN_TRANSITION")
    if ev:
        p = ev[-1]["p"]
        to = p.get("to") or {}
        mem.update(state=to.get("state", mb.NEUTRAL), side=to.get("side"), since=p.get("t"), confirm=p.get("confirm_level"), invalid=p.get("invalid_level"),
                   keys=p.get("keys") or [], n_side=len(p.get("keys") or []))
    return mem


def tick(db: str, mem: Dict[str, Any], now: float, last_snap: float, *, features: Optional[Dict[str, Any]] = None,
         plans: Optional[List[Dict[str, Any]]] = None, **kw: Any) -> Dict[str, Any]:
    """Один цикл: ознаки → крок пам'яті → запис у журнал. Повертає {mem, tr, snap_at, text, reassess}. Нічого не відправляє."""
    from office_bridge import log_event

    f = features if features is not None else gather(now, **kw)
    new, tr = mb.step(mem, f, now)
    out: Dict[str, Any] = {"mem": new, "tr": tr, "snap_at": last_snap, "text": None, "reassess": None}
    if f.get("ok") and now - last_snap >= SNAP_SEC:
        log_event(db, "MARKET_BRAIN_SNAP", {"t": now, "state": [new["state"], new["side"]], **{k: f.get(k) for k in (
            "price", "price_30m", "price_60m", "oi_30m", "oi_60m", "funding_pct", "ls_ratio", "breadth", "eth_60m", "atr15_pct", "sweep_up", "sweep_down",
            "swing_low", "swing_high")}, "n_long": len(mb.evidence(f)["LONG"]), "n_short": len(mb.evidence(f)["SHORT"])})
        out["snap_at"] = now
    if tr:
        log_event(db, "MARKET_BRAIN_TRANSITION", {k: tr[k] for k in tr})
        out["text"] = mb.message(tr, None)
        if plans:
            prev = mb.name(tr["from"]["state"], tr["from"]["side"])
            r = mb.reassess(new, plans)
            out["reassess"] = {"result": r, "text": mb.reassess_message(new, prev, plans, r)}
            log_event(db, "MARKET_BRAIN_REASSESS", {"t": now, "state": [new["state"], new["side"]], "result": r, "n_plans": len(plans), "shadow": True})
    return out

"""Практичний тренажер (як перемотка історії в TradingView): історія заморожується на моменті T, Brain v2.1 дивиться ЛИШЕ на свічки до T і дає рішення/план,
майбутнє відкривається окремим викликом і оцінюється тими самими правилами paper (вхід лімітом, SL першим). Нічого не пишеться в БД, ордерів немає.

Заборона підглядання: `decide` ніколи не запитує свічки пізніше T (endTime = T), у відповіді немає жодного бару ≥ T; `reveal` перераховує рішення
наново (детерміновано) і лише потім читає майбутнє — клієнт не передає свій план і не може підмінити результат.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import numpy as np

BAR = 900
MIN_BACK_SEC = 3600            # T не пізніше ніж за годину до «зараз»: наступні свічки вже існують
MAX_BACK_SEC = 14 * 86400
FUTURE_SEC = 24 * 3600
SHOW_BARS = 120


def _hist_feed(getter: Optional[Any] = None):
    from office2.live import Feed

    class HistFeed(Feed):
        """Feed, що завжди читає історію з endTime = T (час бере з аргументу now)."""

        def klines(self, sym, tf, now, limit=None, start_ms=None, end_ms=None):  # type: ignore[override]
            return super().klines(sym, tf, now, limit=limit, start_ms=start_ms, end_ms=end_ms if end_ms is not None else int(now * 1000))

    return HistFeed(getter=getter) if getter else HistFeed()


def align(t: float) -> float:
    return float(int(t // BAR) * BAR)


def pick_time(back_h: Optional[float], now: Optional[float] = None, seed: Optional[int] = None) -> float:
    """T = закриття 15m-бару за back_h годин тому; без back_h — випадкова мить у межах 1–7 діб."""
    n = time.time() if now is None else now
    if back_h is None:
        rng = np.random.default_rng(seed)
        back = float(rng.integers(6, 7 * 24)) * 3600.0
    else:
        back = float(back_h) * 3600.0
    return align(n - max(MIN_BACK_SEC, min(MAX_BACK_SEC, back)))


def _plan(th: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from office2 import radar_watch as RW

    if th.get("state") == "READY":
        p = RW.plan_of(th)
        return dict(p, source="READY") if p["plan_ok"] else None
    if th.get("state") == "WAIT" and th.get("preview"):
        p = RW.plan_of(th)
        return dict(p, source="WATCH-орієнтир") if p["plan_ok"] else None
    return None


def decide(sym: str, T: float, feed: Optional[Any] = None) -> Dict[str, Any]:
    """Рішення Brain на моменті T за свічками, закритими до T. Повертає свічки до T і стан для LONG/SHORT. Майбутнє не запитується."""
    from office2 import brain as B
    from office2 import brain2 as B2
    from office2 import engine as EN
    from office2.live import build_ctx

    feed = feed or _hist_feed()
    ctx = build_ctx(feed, sym, T)
    if not ctx:
        return {"ok": False, "reason": "немає історії свічок на цей момент (нова монета або недоступний фід)", "symbol": sym, "t": T}
    m15 = ctx["m15"] if "m15" in ctx else None
    levels = B.all_levels(ctx, T)
    dec = []
    for d in ("LONG", "SHORT"):
        th = B2.thesis(ctx, d, T, levels, EN.RISK_USD)
        if not th:
            dec.append({"dir": d, "state": "NO_EVENT", "reason": "немає події (sweep/origin) для цього напряму", "plan": None})
            continue
        dec.append({"dir": d, "state": th.get("state"), "reason": th.get("reason"), "plan": _plan(th), "level": th.get("level"), "zone": th.get("entry_zone"), "kind": th.get("kind")})
    arr = m15 if m15 is not None else feed.klines(sym, "15m", T)
    keep = [i for i in range(len(arr["t"])) if float(arr["t"][i]) + BAR <= T][-SHOW_BARS:]
    candles = [{"time": int(arr["t"][i]), "open": float(arr["o"][i]), "high": float(arr["h"][i]), "low": float(arr["l"][i]), "close": float(arr["c"][i])} for i in keep]
    return {"ok": True, "symbol": sym, "t": T, "decisions": dec, "candles": candles, "price_at_t": candles[-1]["close"] if candles else None,
            "note": "Майбутні свічки приховані. Brain бачив лише бари, закриті до цього моменту."}


def reveal(sym: str, T: float, feed: Optional[Any] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Відкриває майбутнє після T (до 24 год) і оцінює плани рішення (вхід лімітом, SL першим, витрати 0.15 %). Рішення перераховується наново."""
    import office_signal_track as TR
    from office2 import radar_watch as RW

    n = time.time() if now is None else now
    if T > n - MIN_BACK_SEC:
        return {"ok": False, "reason": "момент занадто свіжий: майбутнє ще не відбулось"}
    feed = feed or _hist_feed()
    base = decide(sym, T, feed)
    if not base.get("ok"):
        return base
    end = min(n, T + FUTURE_SEC)
    arr = feed.klines(sym, "15m", end, limit=int((end - T) // BAR) + 2, start_ms=int(T * 1000), end_ms=int(end * 1000))
    fut = []
    if arr is not None:
        fut = [{"time": int(arr["t"][i]), "open": float(arr["o"][i]), "high": float(arr["h"][i]), "low": float(arr["l"][i]), "close": float(arr["c"][i])} for i in range(len(arr["t"])) if float(arr["t"][i]) >= T]
    cl = [{"ts": c["time"], "high": c["high"], "low": c["low"]} for c in fut]
    results = []
    for d in base["decisions"]:
        p = d.get("plan")
        if not p:
            results.append({"dir": d["dir"], "outcome": "NO_PLAN", "text": "плану не було: " + str(d.get("reason") or "")[:140]})
            continue
        card = {"direction": d["dir"], "entry": p["entry"], "sl": p["sl"], "tp1": p["tp1"], "tp2": p.get("tp2"), "tp3": p.get("tp3"), "created_ts": T, "sent_ts": T, "expires_ts": T + RW.TTL_SEC, "risk_pct": p.get("risk_pct")}
        ev = RW.evaluate_card(card, cl, end)
        results.append({"dir": d["dir"], "outcome": ev["paper_status"], "reached": ev["reached"], "entry_ts": ev["entry_ts"], "r_net": ev["r_net"], "plan": p, "source": p.get("source")})
    move = None
    if base["price_at_t"] and fut:
        move = {"after_h": round((fut[-1]["time"] + BAR - T) / 3600.0, 2), "pct": round((fut[-1]["close"] - base["price_at_t"]) / base["price_at_t"] * 100.0, 2),
                "max_up_pct": round((max(c["high"] for c in fut) - base["price_at_t"]) / base["price_at_t"] * 100.0, 2), "max_down_pct": round((min(c["low"] for c in fut) - base["price_at_t"]) / base["price_at_t"] * 100.0, 2)}
    return {"ok": True, "symbol": sym, "t": T, "decisions": base["decisions"], "past": base["candles"], "future": fut, "results": results, "move": move,
            "note": "Оцінка — paper-модель: вхід лімітом після T, SL першим у спірній свічці, витрати 0.15 %; не гроші й не ордер."}

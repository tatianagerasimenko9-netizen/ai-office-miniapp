"""Ринковий контекст із реальних даних Binance: фандинг, відкритий інтерес (OI), співвідношення покупців/продавців.

Це ПОЯСНЕННЯ до сценарію, а не вхід і не гейт: правила записані нижче, пороги інформаційні й не калібровані на
історії (тому нічого не блокують і не змінюють рішення Лева). Немає даних — пише «не перевірено», а не «нейтрально».
Що ще НЕ підключено — прямо в NOT_CONNECTED (стакан/спред, карта ліквідацій, новини/календар).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

FUNDING_HOT_PCT = 0.05        # фандинг за 8 год, % — «натовп переповнений» (інформаційний поріг)
OI_MOVE_PCT = 2.0             # зміна OI за ~3 год, % — «значна»
PRICE_MOVE_PCT = 0.3          # зміна ціни за ~3 год, % — «є рух»
LS_CROWD_HI = 2.0             # співвідношення лонг/шорт-акаунтів
LS_CROWD_LO = 0.6
CACHE_SEC = 120
# Свіжість обов'язкова: показник старший за ліміт НЕ використовується (пишемо «дані застарілі»). Ліміти — з природи джерела:
# фандинг і поточна ціна оновлюються постійно (10 хв), а OI-історія й співвідношення покупців/продавців — погодинні точки (2 год).
MAX_AGE_SEC = {"фандинг": 600.0, "відкритий інтерес": 7200.0, "співвідношення покупців і продавців": 7200.0}
NOT_CONNECTED = ["стакан і спред", "карта ліквідацій", "новини й календар подій"]
_CACHE: Dict[str, tuple] = {}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _raw(symbol: str) -> Dict[str, Any]:
    from office_market_data import fetch_candles, fetch_funding_rate, fetch_long_short_ratio, fetch_open_interest

    now = time.time()
    hit = _CACHE.get(symbol)
    if hit and now - hit[0] < CACHE_SEC:
        return hit[1]
    out = {"funding": fetch_funding_rate(symbol), "oi": fetch_open_interest(symbol), "ls": fetch_long_short_ratio(symbol),
           "h1": fetch_candles(symbol, "1h", 6)}
    _CACHE[symbol] = (now, out)
    if len(_CACHE) > 300:
        _CACHE.clear()
    return out


def analyse(direction: str, *, funding_pct: Optional[float], oi_hist: List[Dict[str, Any]], price_change_pct: Optional[float],
            ls_ratio: Optional[float]) -> Dict[str, Any]:
    """Чиста функція: (напрям сценарію + числа) → пояснення. Кожне речення прив'язане до конкретного правила й числа."""
    long_ = str(direction or "").upper() != "SHORT"
    notes: List[Dict[str, str]] = []
    unchecked: List[str] = []
    # 1. Фандинг
    if funding_pct is None:
        unchecked.append("фандинг")
    else:
        f = f"{funding_pct:+.3f}%".replace(".", ",")
        if funding_pct >= FUNDING_HOT_PCT:
            notes.append({"tone": "bad" if long_ else "good", "text": f"Фандинг високий ({f}): багато хто вже в лонгах. " +
                          ("Купівля ризикованіша — відкат може бути різким." if long_ else "Це працює на продаж: натовп у лонгах вразливий.")})
        elif funding_pct <= -FUNDING_HOT_PCT:
            notes.append({"tone": "good" if long_ else "bad", "text": f"Фандинг від'ємний ({f}): багато хто вже в шортах. " +
                          ("Це працює на купівлю: шорти можуть закриватися." if long_ else "Продаж ризикованіший — можливе різке закриття шортів.")})
        else:
            notes.append({"tone": "n", "text": f"Фандинг помірний ({f}) — перекосу натовпу немає."})
    # 2. Відкритий інтерес + ціна (~3 год)
    oi_chg = None
    if len(oi_hist) >= 2 and _f(oi_hist[0].get("oi")) and _f(oi_hist[-1].get("oi")):
        oi_chg = (float(oi_hist[-1]["oi"]) - float(oi_hist[0]["oi"])) / float(oi_hist[0]["oi"]) * 100.0
    if oi_chg is None or price_change_pct is None:
        unchecked.append("відкритий інтерес")
    else:
        up, dn = price_change_pct >= PRICE_MOVE_PCT, price_change_pct <= -PRICE_MOVE_PCT
        o = f"{oi_chg:+.1f}%".replace(".", ",")
        if up and oi_chg >= OI_MOVE_PCT:
            notes.append({"tone": "good" if long_ else "bad", "text": f"Ціна росте, відкритий інтерес зріс ({o}): рух підтримують нові позиції."})
        elif up and oi_chg <= -OI_MOVE_PCT:
            notes.append({"tone": "bad" if long_ else "good", "text": f"Ціна росте, але відкритий інтерес впав ({o}): це закриття шортів, ріст може швидко вичерпатись."})
        elif dn and oi_chg >= OI_MOVE_PCT:
            notes.append({"tone": "bad" if long_ else "good", "text": f"Ціна падає, відкритий інтерес зріс ({o}): падіння підтримують нові шорти."})
        elif dn and oi_chg <= -OI_MOVE_PCT:
            notes.append({"tone": "good" if long_ else "bad", "text": f"Ціна падає, відкритий інтерес впав ({o}): це закриття лонгів, падіння може вичерпатись."})
        else:
            notes.append({"tone": "n", "text": f"Відкритий інтерес майже не змінився ({o}) — нових великих позицій немає."})
    # 3. Співвідношення покупців і продавців
    if ls_ratio is None:
        unchecked.append("співвідношення покупців і продавців")
    else:
        r = f"{ls_ratio:.2f}".replace(".", ",")
        if ls_ratio >= LS_CROWD_HI:
            notes.append({"tone": "bad" if long_ else "good", "text": f"Покупців значно більше, ніж продавців ({r}): натовп у купівлі."})
        elif ls_ratio <= LS_CROWD_LO:
            notes.append({"tone": "good" if long_ else "bad", "text": f"Продавців значно більше, ніж покупців ({r}): натовп у продажі."})
    nc = list(NOT_CONNECTED)
    try:
        from office_calendar import block_enabled

        if block_enabled():   # календар підключено (OFFICE_CALENDAR_BLOCK=1) — більше не «не бачить»
            nc = [x for x in nc if "новини" not in x]
    except Exception:  # noqa: BLE001
        pass
    return {"notes": notes, "unchecked": unchecked, "not_connected": nc,
            "rule_note": "Це пояснення, а не сигнал: ці показники не блокують і не змінюють рішення Лева."}


def context_for(symbol: str, direction: str) -> Dict[str, Any]:
    """Реальні дані → пояснення. Будь-який збій джерела → відповідний пункт «не перевірено» (нічого не вигадуємо)."""
    sym = str(symbol or "").upper()
    try:
        raw = _raw(sym)
    except Exception:  # noqa: BLE001
        raw = {}
    fr = raw.get("funding") or {}
    oi = raw.get("oi") or {}
    ls = raw.get("ls") or {}
    h1 = raw.get("h1") if isinstance(raw.get("h1"), list) else []
    chg = None
    if len(h1) >= 4 and _f(h1[-4].get("close")) and _f(h1[-1].get("close")):
        chg = (float(h1[-1]["close"]) - float(h1[-4]["close"])) / float(h1[-4]["close"]) * 100.0
    now = time.time()
    fund_ts = (float(fr["time_ms"]) / 1000.0) if isinstance(fr, dict) and _f(fr.get("time_ms")) else None
    oi_hist = oi.get("history") if isinstance(oi, dict) and isinstance(oi.get("history"), list) else []
    ls_hist = ls.get("history") if isinstance(ls, dict) and isinstance(ls.get("history"), list) else []
    fresh = [_freshness("фандинг", fund_ts, now, present=isinstance(fr, dict) and _f(fr.get("funding_rate_pct")) is not None),
             _freshness("відкритий інтерес", _hist_ts(oi_hist), now, present=len(oi_hist) >= 2),
             _freshness("співвідношення покупців і продавців", _hist_ts(ls_hist), now, present=isinstance(ls, dict) and _f(ls.get("current_ratio")) is not None)]
    ok = {f["name"]: f["fresh"] for f in fresh}
    res = analyse(direction,
                  funding_pct=_f(fr.get("funding_rate_pct")) if (isinstance(fr, dict) and ok["фандинг"]) else None,
                  oi_hist=oi_hist if ok["відкритий інтерес"] else [],
                  price_change_pct=chg,
                  ls_ratio=_f(ls.get("current_ratio")) if (isinstance(ls, dict) and ok["співвідношення покупців і продавців"]) else None)
    why = {f["name"]: ("дані застарілі" if f["age_sec"] is not None else "у даних немає часу") for f in fresh if f["present"] and not f["fresh"]}
    res["unchecked"] = [(f"{u} — {why[u]}" if u in why else u) for u in res["unchecked"]]
    res["freshness"] = fresh
    return res


def _hist_ts(hist: List[Dict[str, Any]]) -> Optional[float]:
    """Час найновішої точки історії (секунди) або None."""
    from datetime import datetime

    for item in reversed(hist or []):
        try:
            return datetime.fromisoformat(str(item.get("timestamp") or "").replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            continue
    return None


def _freshness(name: str, ts: Optional[float], now: float, present: bool) -> Dict[str, Any]:
    """{'name','present','as_of','age_sec','fresh'}; немає мітки часу = невідомо = НЕ свіже (не довіряємо)."""
    age = (now - ts) if ts else None
    return {"name": name, "present": bool(present), "as_of": ts, "age_sec": round(age, 1) if age is not None else None,
            "fresh": bool(present and age is not None and 0 <= age <= MAX_AGE_SEC[name] + 1.0)}

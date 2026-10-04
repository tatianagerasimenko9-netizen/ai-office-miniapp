"""Execution Planner v1: перевірки перед входом за поточною ціною. Не ордер.

Кожна перевірка має стан OK / FAIL / UNAVAILABLE. UNAVAILABLE не вважається
пройденою: без перевіреного джерела (спред, новини) вхід «не перевірено».
Пороги RR/TP1 беруться з чинних правил (MIN_RR, MAJORS/ALTS_TP1_PCT), нових
ризикових порогів модуль не вводить; LATE_SHARE — лише поріг відображення
«вхід запізнілий», рішень Лева не змінює.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

LATE_SHARE = 0.5  # ціна пройшла ≥50% шляху від зони до TP1 → вхід запізнілий


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and x > 0 else None


def _chk(key: str, title: str, state: str, detail: str) -> Dict[str, str]:
    return {"key": key, "title": title, "state": state, "detail": detail}


def execution_checks(
    *,
    symbol: str,
    direction: str,
    zone_lo: Any,
    zone_hi: Any,
    sl: Any,
    tp1: Any,
    price: Any,
    price_fresh: bool,
    has_open_position: Optional[bool],
    min_rr: float,
    min_tp1_pct: float,
    news: Optional[tuple] = None,
    tp2: Any = None,
) -> Dict[str, Any]:
    side = str(direction or "").upper()
    lo, hi, s, t, px = _f(zone_lo), _f(zone_hi), _f(sl), _f(tp1), _f(price)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    checks: List[Dict[str, str]] = []
    geometry_ok = side in ("LONG", "SHORT") and None not in (lo, hi, s, t)
    if not price_fresh or px is None:
        checks.append(_chk("data", "Актуальна ціна", "UNAVAILABLE", "немає свіжої ціни — перевірки за ціною не виконані"))
    else:
        checks.append(_chk("data", "Актуальна ціна", "OK", "ціна свіжа"))
    if not geometry_ok:
        checks.append(_chk("plan", "План", "FAIL", "немає повної геометрії зона/SL/TP1"))
    elif px is not None and price_fresh:
        long_ = side == "LONG"
        # Вхід за фактичною ціною, якщо вона в зоні; інакше — найгірша межа зони.
        in_zone = lo <= px <= hi
        fill = px if in_zone else (hi if long_ else lo)
        beyond_sl = px <= s if long_ else px >= s
        checks.append(_chk("invalidation", "Сценарій чинний", "FAIL" if beyond_sl else "OK",
                           "ціна вже за стопом/інвалідацією" if beyond_sl else "ціна не за інвалідацією"))
        path = (t - hi) if long_ else (lo - t)
        done = (px - hi) if long_ else (lo - px)
        late = path > 0 and done >= LATE_SHARE * path
        checks.append(_chk("late", "Не запізно", "FAIL" if late else "OK",
                           f"ціна пройшла {done / path * 100:.0f}% шляху до TP1 — не наздоганяємо" if late
                           else ("ціна в зоні входу" if in_zone else "ціна ще не в зоні")))
        risk = abs(fill - s)
        reward = abs(t - fill)
        # RR — за ТИМ САМИМ правилом, що й гейт READY (office_alert_gate.rr_gate: комісії, зважений RR при записаному TP2), а не «до TP1 без комісій»
        from office_alert_gate import rr_gate

        g = rr_gate(fill, s, t, _f(tp2))
        if g.get("rr_net") is None:
            checks.append(_chk("rr", "RR за правилом гейта від фактичної ціни", "UNAVAILABLE", "не вдалося порахувати"))
        else:
            tail = f"; зважений {g['rr_weighted']:.2f}" if g.get("rule") == "weighted" and _f(tp2) is not None else ""
            checks.append(_chk("rr", "RR за правилом гейта від фактичної ціни", "OK" if g["ok"] else "FAIL",
                               f"RR після комісій до TP1 {g['rr_net']:.2f}{tail} (від {'ціни' if in_zone else 'межі зони'}); потрібно: " +
                               ("зважений ≥ 1,5 і до TP1 ≥ 1,0" if g.get("rule") == "weighted" and _f(tp2) is not None else f"≥ {min_rr:g}")))
        pct = reward / fill * 100 if fill else 0.0
        checks.append(_chk("space", f"Простір до TP1 ≥ {min_tp1_pct:g}%", "OK" if pct + 1e-9 >= min_tp1_pct else "FAIL",
                           f"до TP1 {pct:.2f}%"))
    if has_open_position is None:
        checks.append(_chk("duplicate", "Не дублює позицію", "UNAVAILABLE", "стан позицій невідомий"))
    else:
        checks.append(_chk("duplicate", "Не дублює позицію", "FAIL" if has_open_position else "OK",
                           "вже є підтверджена /position у цьому напрямку" if has_open_position else "відкритої /position немає"))
    checks.append(_chk("spread", "Спред і ліквідність", "UNAVAILABLE", "стакан/спред не підключені"))
    if news is None:
        checks.append(_chk("news", "Немає новини перед входом", "UNAVAILABLE", "перевіреного календаря подій немає"))
    else:   # стан із календаря (той самий, що показує статус джерела), а не вічне «невідомо»
        checks.append(_chk("news", "Немає новини перед входом", str(news[0]), str(news[1])))
    fails = [c for c in checks if c["state"] == "FAIL"]
    unknown = [c for c in checks if c["state"] == "UNAVAILABLE"]
    if fails:
        verdict, text = "BLOCKED", "Вхід зараз не розглядати: " + "; ".join(c["detail"] for c in fails)
    elif unknown:
        verdict, text = "NOT_VERIFIED", "Частину перевірок не виконано — рішення лише за трейдером"
    else:
        verdict, text = "CHECKED", "Усі перевірки пройдено — це не наказ відкривати угоду"
    return {"symbol": str(symbol or "").upper(), "verdict": verdict, "text": text, "checks": checks,
            "order_authorized": False}

"""Повідомлення Лева людською мовою: висновок → що робити → чого чекаємо → коли напише знову.

Чиста функція від «вигляду» ситуації (без БД, без мережі). Жодного внутрішнього жаргону (WATCHING, Risk Officer,
SFP, TTL, ID сценарію): їх місце — у «Деталях» Mini App. Не вигадує цифр: немає рівня чи умови — прямо каже,
що плану ще немає. Зелений статус і план угоди — лише коли Лев сформував повний перевірений план.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from office_price_format import format_px

TF_UA = {"M1": "1-хвилинному", "M5": "5-хвилинному", "M15": "15-хвилинному", "H1": "годинному", "H4": "4-годинному", "D1": "денному"}
TF_CANDLE_UA = {"M5": "5-хвилинна свічка", "M15": "15-хвилинна свічка", "H1": "годинна свічка", "H4": "4-годинна свічка", "D1": "денна свічка"}
COIN_UA = {"BTC": "Біткоїн", "ETH": "Ефір"}
HEAD = {
    "WAIT": ("🟡", "ЧЕКАЄМО"),
    "IN_ZONE": ("🟡", "ЦІНА В ЗОНІ, ПІДТВЕРДЖЕННЯ ЩЕ НЕМАЄ"),
    "CONFIRMED": ("🟢", "УМОВИ ПІДТВЕРДЖЕНО"),
    "CANCELLED": ("🔴", "ПЛАН СКАСОВАНО"),
    "EXPIRED": ("⚪", "ЧАС ОЧІКУВАННЯ ЗАКІНЧИВСЯ"),
    "STALE": ("⚠️", "ДАНІ ЗАСТАРІЛИ"),
    "REJECTED": ("🔴", "УМОВИ Є, АЛЕ ВХОДУ НЕМАЄ"),
    "NO_TRADE": ("⚪", "ВХОДУ НЕМАЄ"),
}


def ticker(symbol: str) -> str:
    s = str(symbol or "").upper()
    return s[:-4] if s.endswith("USDT") and len(s) > 4 else s


def _px(v: Any, symbol: str) -> str:
    try:
        if v is None:
            return "—"
        out = format_px(float(v), symbol)
    except Exception:  # noqa: BLE001
        return "—"
    return f"{out} $" if str(symbol).upper().endswith("USDT") else out


def _side_words(direction: str) -> Dict[str, str]:
    if str(direction or "").upper() == "SHORT":
        return {"gen": "продажу", "do": "продавати", "dont": "не продавати", "up": "вниз", "cross": "вище", "cross_word": "вище"}
    return {"gen": "купівлі", "do": "купувати", "dont": "не купувати", "up": "вгору", "cross": "нижче", "cross_word": "нижче"}


def _price_vs_zone(v: Dict[str, Any]) -> str:
    """Одне речення про ціну щодо зони — лише з чисел; без 'кандидатів' і внутрішніх назв."""
    try:
        px, lo, hi = float(v["price"]), float(v["zone_lo"]), float(v["zone_hi"])
    except Exception:  # noqa: BLE001
        return ""
    w = _side_words(v.get("direction"))
    long_ = str(v.get("direction") or "").upper() != "SHORT"
    if lo <= px <= hi:
        return f"Ціна вже в зоні, але підтвердження ще немає — {w['do']} рано."
    above = px > hi
    if long_ and above:
        return "Ціна вже вища за зону — наздоганяти не потрібно."
    if (not long_) and (not above):
        return "Ціна вже нижча за зону — наздоганяти не потрібно."
    return f"Ціна ще {'нижче' if not above else 'вище'} зони — {w['do']} рано."


def _wait_line(v: Dict[str, Any]) -> str:
    sym = v.get("symbol", "")
    w = _side_words(v.get("direction"))
    tf = TF_UA.get(str(v.get("wait_tf") or "M15").upper(), "15-хвилинному")
    return (f"повернення ціни в зону {_px(v.get('zone_lo'), sym).replace(' $', '')}–{_px(v.get('zone_hi'), sym)} "
            f"і підтвердження розвороту {w['up']} на {tf} графіку.")


def _cancel_line(v: Dict[str, Any]) -> str:
    sym = v.get("symbol", "")
    inv = v.get("invalidation")
    if inv is None:
        return "рівень скасування не визначено — план ще не готовий."
    w = _side_words(v.get("direction"))
    candle = TF_CANDLE_UA.get(str(v.get("scenario_tf") or "H1").upper(), "годинна свічка")
    return f"якщо {candle} закриється {w['cross']} {_px(inv, sym)}."


def _next_line(v: Dict[str, Any]) -> str:
    if v.get("tracking"):
        return "Лев стежить за ціною й сам напише, коли умови підтвердяться або план скасується. Від тебе дій не потрібно."
    return "Автоматичного сповіщення поки немає. Щоб оновити висновок, запитай знову: /lev " + ticker(v.get("symbol", ""))


def _until(v: Dict[str, Any]) -> str:
    exp = v.get("expires_at")
    if not exp:
        return ""
    try:
        dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=3)))
        return f" Слідкуємо до {dt:%H:%M} (Київ)."
    except Exception:  # noqa: BLE001
        return ""


def render(v: Dict[str, Any]) -> str:
    """Основне повідомлення. v: symbol, state, direction, price, zone_lo/hi, invalidation, wait_tf, scenario_tf,
    plan{entry,sl,tp1,tp2}, tracking, expires_at, reason."""
    st = str(v.get("state") or "NO_TRADE").upper()
    sym = v.get("symbol", "")
    icon, title = HEAD.get(st, HEAD["NO_TRADE"])
    w = _side_words(v.get("direction"))
    L: List[str] = [f"{icon} {ticker(sym)} · {title}"]
    if st == "STALE":
        L += ["ЩО ЗАРАЗ: нічого не робимо. Свіжих даних немає, висновку не роблю.",
              "Не покладайся на це повідомлення: перевір ціну на Binance. Коли дані повернуться, Лев напише сам." if v.get("tracking")
              else "Не покладайся на це повідомлення: перевір ціну на Binance і запитай пізніше."]
        return "\n".join(L)
    if st == "WAIT":
        L.append(f"ЩО ЗАРАЗ: {w['dont']}. {_price_vs_zone(v)}".strip())
        L.append("ЩО ЧЕКАЄМО: " + _wait_line(v))
        L.append("КОЛИ ПЛАН СКАСУЄТЬСЯ: " + _cancel_line(v))
        L.append("КОЛИ ПОВІДОМИШ: " + _next_line(v) + _until(v))
    elif st == "IN_ZONE":
        L.append(f"ЩО ЗАРАЗ: {w['dont']} — підтвердження ще немає.")
        tf = TF_UA.get(str(v.get("wait_tf") or "M15").upper(), "15-хвилинному")
        L.append(f"ЩО ЧЕКАЄМО: підтвердження розвороту {w['up']} на {tf} графіку.")
        L.append("КОЛИ ПЛАН СКАСУЄТЬСЯ: " + _cancel_line(v))
        L.append("КОЛИ ПОВІДОМИШ: Лев напише, коли підтвердження з'явиться або план скасується." + _until(v))
    elif st == "CONFIRMED":
        p = v.get("plan") or {}
        L.append("ЩО ЗАРАЗ: умови виконано. Рішення про вхід — за тобою; ордер Офіс не ставить.")
        parts = [f"вхід {_px(p.get('entry'), sym)}", f"стоп {_px(p.get('sl'), sym)}", f"ціль 1 {_px(p.get('tp1'), sym)}"]
        if p.get("tp2") is not None:
            parts.append(f"ціль 2 {_px(p.get('tp2'), sym)}")
        L.append("ПЛАН УГОДИ: " + " · ".join(parts))
        L.append("КОЛИ ПЛАН СКАСУЄТЬСЯ: " + _cancel_line(v))
        L.append("КОЛИ ПОВІДОМИШ: Лев напише, якщо план втратить чинність.")
    elif st == "CANCELLED":
        L.append(f"Ціна закрилася {w['cross']} рівня скасування ({_px(v.get('invalidation'), sym)}). Попередній план {w['gen']} більше не діє.")
        L.append("ЩО ЗАРАЗ: нічого не робимо. Якщо ти вже в угоді — перевір свій стоп.")
        L.append("КОЛИ ПОВІДОМИШ: коли з'явиться новий план.")
    elif st == "EXPIRED":
        touched = " Ціна заходила в зону, але підтвердження не з'явилося." if v.get("touched_zone") else " Підтвердження не з'явилося."
        L.append(f"Час очікування минув.{touched} План {w['gen']} більше не діє.")
        L.append("ЩО ЗАРАЗ: нічого не робимо.")
        L.append("КОЛИ ПОВІДОМИШ: коли з'явиться новий план.")
    elif st == "REJECTED":
        L.append("ЩО ЗАРАЗ: не входити. " + str(v.get("reason") or "План не проходить наші перевірки."))
        L.append("КОЛИ ПОВІДОМИШ: коли з'явиться новий план.")
    else:  # NO_TRADE
        L.append("ЩО ЗАРАЗ: нічого не робимо. " + str(v.get("reason") or "Підтвердженого напрямку зараз немає."))
        L.append("ПЛАН УГОДИ: поки немає.")
        L.append("КОЛИ ПОВІДОМИШ: " + _next_line(v))
    L.append("Це аналіз, не ордер: рішення й ордер на біржі — лише твої.")
    return "\n".join(L)

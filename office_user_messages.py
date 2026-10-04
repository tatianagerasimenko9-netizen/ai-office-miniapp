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
    out = out.replace(".", ",")
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
        L += ["ЗАРАЗ: нічого не робимо. Свіжих даних немає, висновку не роблю.",
              "Не покладайся на це повідомлення: перевір ціну на Binance. Коли дані повернуться, Лев напише сам." if v.get("tracking")
              else "Не покладайся на це повідомлення: перевір ціну на Binance і запитай пізніше."]
        return "\n".join(L)
    if st == "WAIT":
        L.append(f"ЗАРАЗ: {w['dont']}. {_price_vs_zone(v)}".strip())
        L.append("ЧОГО ЧЕКАЄМО: " + _wait_line(v))
        L.append("КОЛИ СКАСОВУЄМО: " + _cancel_line(v))
        L.append("ДАЛІ: " + _next_line(v) + (_until(v) if v.get("tracking") else ""))
    elif st == "IN_ZONE":
        L.append(f"ЗАРАЗ: {w['dont']} — підтвердження ще немає.")
        tf = TF_UA.get(str(v.get("wait_tf") or "M15").upper(), "15-хвилинному")
        L.append(f"ЧОГО ЧЕКАЄМО: підтвердження розвороту {w['up']} на {tf} графіку.")
        L.append("КОЛИ СКАСОВУЄМО: " + _cancel_line(v))
        L.append(("ДАЛІ: Лев напише, коли підтвердження з'явиться або план скасується." + _until(v)) if v.get("tracking") else "ДАЛІ: заглядай сюди або запитай /lev " + ticker(sym))
    elif st == "CONFIRMED":
        p = v.get("plan") or {}
        L.append("ЗАРАЗ: умови виконано. Рішення про вхід — за тобою; ордер Офіс не ставить.")
        parts = [f"вхід {_px(p.get('entry'), sym)}", f"стоп {_px(p.get('sl'), sym)}", f"ціль 1 {_px(p.get('tp1'), sym)}"]
        if p.get("tp2") is not None:
            parts.append(f"ціль 2 {_px(p.get('tp2'), sym)}")
        L.append("ПЛАН УГОДИ: " + " · ".join(parts))
        L.append("КОЛИ СКАСОВУЄМО: " + _cancel_line(v))
        L.append("ДАЛІ: Лев напише, якщо план втратить чинність." if v.get("tracking") else "ДАЛІ: слідкуй за рівнем скасування — автоматичного повідомлення поки немає.")
    elif st == "CANCELLED":
        L.append(f"Ціна закрилася {w['cross']} рівня скасування ({_px(v.get('invalidation'), sym)}). Попередній план {w['gen']} більше не діє.")
        L.append("ЗАРАЗ: нічого не робимо. Якщо ти вже в угоді — перевір свій стоп.")
        L.append("ДАЛІ: новий план з'явиться, коли Лев знайде нову можливість.")
    elif st == "EXPIRED":
        touched = " Ціна заходила в зону, але підтвердження не з'явилося." if v.get("touched_zone") else " Підтвердження не з'явилося."
        L.append(f"Час очікування минув.{touched} План {w['gen']} більше не діє.")
        L.append("ЗАРАЗ: нічого не робимо.")
        L.append("ДАЛІ: новий план з'явиться, коли Лев знайде нову можливість.")
    elif st == "REJECTED":
        L.append("ЗАРАЗ: не входити. " + str(v.get("reason") or "План не проходить наші перевірки."))
        L.append("ДАЛІ: новий план з'явиться, коли Лев знайде нову можливість.")
    else:  # NO_TRADE
        L.append("ЗАРАЗ: нічого не робимо. " + str(v.get("reason") or "Підтвердженого напрямку зараз немає."))
        L.append("ПЛАН УГОДИ: поки немає.")
        L.append("ДАЛІ: " + _next_line(v))
    L.append("Це аналіз, не ордер: рішення й ордер на біржі — лише твої.")
    return "\n".join(L)


# ------------------------------------------------------------------ картки підтвердження/скасування (worker)
PLAIN_CONFIRM = {
    "double_bottom": "подвійне дно", "double_top": "подвійна вершина", "triple_bottom": "потрійне дно", "triple_top": "потрійна вершина", "level_false_break": "хибний пробій рівня", "level_hold": "закріплення за рівнем", "level_retest": "ретест рівня", "pin_bar": "пін-бар біля зони", "inside_bar_break": "пробій після inside bar", "engulfing_ctx": "поглинання біля зони", "exhaustion": "виснаження руху", "sweep_pool": "зняття ліквідності", "displacement": "сильний імпульс", "fvg_retest": "ретест FVG", "ob_retest": "ретест order block", "breaker_retest": "ретест breaker", "ote": "зона OTE", "spring_test": "тест spring", "upthrust_test": "тест upthrust", "head_shoulders": "голова і плечі", "inverse_head_shoulders": "перевернута голова і плечі", "ascending_triangle": "висхідний трикутник", "descending_triangle": "низхідний трикутник", "symmetrical_triangle": "симетричний трикутник", "rectangle": "прямокутник", "rising_wedge": "висхідний клин", "falling_wedge": "спадний клин", "flag": "прапор", "pennant": "вимпел",
    "sfp": "хибний пробій рівня з поверненням", "engulf": "поглинання попередньої свічки", "bos": "пробій структури",
    "choch": "зміна напрямку руху", "spring": "хибний прокол вниз і повернення", "upthrust": "хибний прокол вгору і повернення",
}


# Фігури, чиї формальні критерії (Булковскі) у коді ще НЕ перевірені: користувачу — «схоже на …», а не «підтверджено». Прибрати, коли Pattern Engine 2.0 дасть статус CONFIRMED.
UNVERIFIED_PATTERNS = ("double_top", "double_bottom", "triple_top", "triple_bottom", "head_shoulders", "inverse_head_shoulders", "ascending_triangle", "descending_triangle",
                       "symmetrical_triangle", "rectangle", "rising_wedge", "falling_wedge", "flag", "pennant")
for _k in UNVERIFIED_PATTERNS:
    if _k in PLAIN_CONFIRM and not PLAIN_CONFIRM[_k].startswith("схоже на "):
        PLAIN_CONFIRM[_k] = "схоже на " + PLAIN_CONFIRM[_k]


def plain_confirms(names: List[str]) -> str:
    out = [PLAIN_CONFIRM.get(str(n).lower(), "") for n in names or []]
    return ", ".join(x for x in out if x)


def _plan_line(symbol: str, entry: Any, sl: Any, tp1: Any, tp2: Optional[Dict[str, Any]], tp3: Optional[Dict[str, Any]]) -> str:
    def t(x: Optional[Dict[str, Any]]) -> str:
        return f"{_px(x['price'], symbol)} ({x['why']})" if x else "немає обґрунтованої"

    return f"ВХІД {_px(entry, symbol)} · СТОП {_px(sl, symbol)} · TP1 {_px(tp1, symbol)} · TP2 {t(tp2)} · TP3 {t(tp3)}"


def _dir_head(direction: str) -> tuple:
    long_ = str(direction or "").upper() != "SHORT"
    return ("🟢", "LONG") if long_ else ("🔴", "SHORT")


def _pct_txt(price: Any, entry: Any, sign: str) -> str:
    """«(−1,0%)» — скільки це в % від входу: стоп — збиток (−), цілі — прибуток (+), для LONG і SHORT однаково."""
    try:
        p, e = float(price), float(entry)
        if e <= 0:
            return ""
        v = abs(p - e) / e * 100.0
        txt = (f"{v:.2f}" if v < 10 else f"{v:.1f}").replace(".", ",")
        return f" ({sign}{txt}%)"
    except (TypeError, ValueError):
        return ""


def ready_signal(*, symbol: str, direction: str, entry: Any, sl: Any, tp1: Any, tp2: Any = None, tp3: Any = None, max_entry: Any = None,
                 size_usdt: Any = None, risk_usd: Any = None, valid_until: str = "", setup: str = "", why: Any = None, market: Any = "", tp3_why: str = "") -> str:
    """Готовий сигнал для Telegram — коротко: висновок, сетап (з реально збережених підстав), ринок і рух монети проти BTC, тиждень, рівні.
    «Чому» з цифрами — у Mini App (з того самого збереженого знімка). Рядки ринку є, лише коли їх реально пораховано. Немає запису про
    підтвердження — чесно «підтвердження не збережене», назву не вигадуємо."""
    def _n(v: Any) -> str:
        return _px(v, symbol).replace(" $", "")

    def price_of(x: Any) -> Any:
        return x.get("price") if isinstance(x, dict) else x

    dot, word = _dir_head(direction)
    long_ = word == "LONG"
    L = [f"{dot} {word} · {ticker(symbol)} · ГОТОВО"]
    if setup is not None and (setup or why is not None):
        name = str(setup or "").split(" · ", 1)[-1] if setup else ""
        L.append(f"Сетап: {name}" if name else "Сетап: підтвердження для цього сигналу не збережене")
    if isinstance(market, (list, tuple)):
        L += [str(x) for x in market if str(x).strip()]
    elif market:
        L.append(f"Ринок: {market}")
    ent = _n(entry)
    if max_entry is not None:
        a, b = (entry, max_entry) if long_ else (max_entry, entry)
        ent = f"{_n(a)}–{_n(b)}"
    L.append(f"Вхід {ent}")
    L.append(f"SL {_n(sl)}" + _pct_txt(sl, entry, "−"))
    tps = []
    for i, v in ((1, tp1), (2, tp2), (3, tp3)):
        if price_of(v) is None:
            continue
        t_ = f"TP{i} {_n(price_of(v))}" + _pct_txt(price_of(v), entry, "+")
        if i == 3 and tp3_why:   # далека ціль завжди з підписом, звідки вона: не просто число
            t_ = t_[:-1] + f", {tp3_why})" if t_.endswith(")") else t_ + f" ({tp3_why})"
        tps.append(t_)
    L.append(" · ".join(tps))
    if size_usdt:
        L.append(f"Позиція {int(round(float(size_usdt))):,} USDT".replace(",", " ") + (f" · ризик {float(risk_usd):.0f} $" if risk_usd else ""))
    if valid_until:
        L.append(f"⏳ до {valid_until} (Київ)")
    return "\n".join(L)


def scenario_event(*, symbol: str, direction: str, level: str, price: Any = None) -> str:
    """Коротка подія сценарію за ринковою ціною (TP1/TP2/TP3/СТОП): без пояснень про стан угоди, лише факт і рівень."""
    lv = str(level or "").upper()
    px_ = f"Ціна досягла {_px(price, symbol)}." if price is not None else "Ціна досягла рівня плану."
    if lv == "SL":
        return f"❌ {ticker(symbol)} · СТОП\n{px_}\nСценарій завершено по SL."
    return f"🎯 {ticker(symbol)} · {lv}\n{px_}"


def confirm_card(*, symbol: str, direction: str, entry: Any, sl: Any, tp1: Any, tp2: Optional[Dict[str, Any]] = None,
                 tp3: Optional[Dict[str, Any]] = None, cancel: Any = None, why: str = "", bad: Optional[str] = None,
                 valid_until: str = "", max_entry: Any = None, size_usdt: Any = None, risk_usd: Any = None) -> str:
    """Сумісність зі старими викликами: `why`/`cancel`/`bad` в Telegram не потрапляють (пояснення — в Mini App)."""
    return ready_signal(symbol=symbol, direction=direction, entry=entry, sl=sl, tp1=tp1, tp2=tp2, tp3=tp3, max_entry=max_entry,
                        size_usdt=size_usdt, risk_usd=risk_usd, valid_until=valid_until)


def cancel_card(*, symbol: str, direction: str, reason: str, level: Any = None) -> str:
    w = _side_words(direction)
    low = str(reason or "").lower()
    if "таймаут" in low:
        head, body = "⚪ {} · ЧАС ОЧІКУВАННЯ ЗАКІНЧИВСЯ", f"Підтвердження не з'явилося вчасно. План {w['gen']} більше не діє."
    else:
        lv = f" ({_px(level, symbol)})" if level is not None else ""
        head, body = "🔴 {} · ПЛАН СКАСОВАНО", f"Ціна пішла {w['cross']} рівня скасування{lv} ще до входу. План {w['gen']} більше не діє."
    return "\n".join([head.format(ticker(symbol)), body, "ЗАРАЗ: нічого не робимо. Якщо ти вже в угоді — перевір свій стоп.",
                      "Це аналіз, не ордер: рішення й ордер на біржі — лише твої."])


def render_human(h: Dict[str, Any]) -> str:
    """Той самий стан, що й на сторінці сценарію в Mini App (`office_scenario_state.build`), у вигляді повідомлення."""
    if h.get("state") == "READY" and h.get("levels"):   # той самий торговий формат, що й сигнал: лише цифри
        lv = h["levels"]
        sz = h.get("size") or {}
        return ready_signal(symbol=str(h.get("symbol") or h.get("ticker") or ""), direction="SHORT" if str(h.get("icon")) == "🔴" else "LONG",
                            entry=lv.get("entry"), sl=lv.get("sl"), tp1=lv.get("tp1"), tp2=lv.get("tp2"), tp3=lv.get("tp3"), max_entry=lv.get("max_entry"),
                            size_usdt=sz.get("usdt"), risk_usd=sz.get("risk_usd"), valid_until=str((h.get("plan") or {}).get("valid_until") or ""))
    L = [f"{h.get('icon', '')} {h.get('ticker', '')} · {str(h.get('state_ua') or '').upper()}", f"ЗАРАЗ: {h.get('headline', '')}"]
    if h.get("price"):
        L.append(f"Ціна: {h['price']}")
    if h.get("wait"):
        L.append(f"ЧОГО ЧЕКАЄМО: {h['wait']}")
    if h.get("cancel"):
        L.append(f"КОЛИ СКАСОВУЄМО: {h['cancel']}")
    p = h.get("plan")
    if p:
        L.append(f"ВХІД {p['entry']} · СТОП {p['stop']} · TP1 {p['tp1']} · TP2 {p['tp2']} · TP3 {p['tp3']}")
        if p.get("potential"):
            L.append(p["potential"])
        if p.get("valid_until"):
            L.append(f"ДІЄ ДО: {p['valid_until']} (Київ) — верхня межа; раніше знімається, якщо ідея зламана.")
    elif h.get("prelim"):
        L.append("ПОПЕРЕДНЬО, НЕ ДЛЯ ВХОДУ: " + "; ".join(h["prelim"]))
    if h.get("next"):
        L.append(f"ДАЛІ: {h['next']}")
    L.append("Це аналіз, не ордер: рішення й ордер на біржі — лише твої.")
    return "\n".join(L)

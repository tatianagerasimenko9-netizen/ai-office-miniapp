"""Новини для користувача — ТІЛЬКИ українською. Англійську назву події не показуємо ніколи.

Назва події з календаря (англійська) → українська назва + коротке просте пояснення + що це означає для входу.
Невідома назва НЕ показується як є: замість неї — загальна українська фраза. Час — за Києвом.
Лише відображення: правило блоку (30 хв до / 15 хв після) і саме джерело календаря не змінюються (office_calendar)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")

COUNTRY_UA = {"USD": "США", "EUR": "єврозони", "GBP": "Великої Британії", "JPY": "Японії", "CNY": "Китаю", "CAD": "Канади",
              "AUD": "Австралії", "CHF": "Швейцарії", "NZD": "Нової Зеландії"}
WEEKDAY_UA = ["понеділок", "вівторок", "середа", "четвер", "пʼятниця", "субота", "неділя"]

# (шаблон назви, українська назва, категорія). Порядок важливий: специфічні — першими.
_RULES: List[Tuple[str, str, str]] = [
    (r"average hourly earnings", "Зміна середньої погодинної зарплати у {c}", "wages"),
    (r"adp .*employment", "Звіт про приватну зайнятість у {c}", "jobs"),
    (r"non-?farm (employment|payrolls)|nfp", "Приріст робочих місць у {c} (поза сільським господарством)", "jobs"),
    (r"unemployment rate", "Рівень безробіття у {c}", "jobs"),
    (r"(unemployment|jobless) claims", "Заявки на допомогу з безробіття у {c}", "claims"),
    (r"jolts|job openings", "Кількість вакансій у {c}", "jobs"),
    (r"core pce", "Базовий індекс цін особистих витрат у {c} (улюблена інфляція ФРС)", "inflation"),
    (r"pce price", "Індекс цін особистих витрат у {c} (улюблена інфляція ФРС)", "inflation"),
    (r"core cpi y/y", "Базова інфляція у {c} (за рік)", "inflation"),
    (r"core cpi", "Базова інфляція у {c} (за місяць)", "inflation"),
    (r"cpi y/y", "Інфляція у {c} (споживчі ціни, за рік)", "inflation"),
    (r"cpi", "Інфляція у {c} (споживчі ціни, за місяць)", "inflation"),
    (r"core ppi", "Базові ціни виробників у {c}", "inflation"),
    (r"ppi", "Ціни виробників у {c}", "inflation"),
    (r"federal funds rate|interest rate decision|rate statement|official bank rate", "Рішення щодо відсоткової ставки ({c})", "rate"),
    (r"fomc.*press conference", "Прес-конференція голови ФРС", "fed_speech"),
    (r"fomc.*minutes|meeting minutes", "Протокол засідання ФРС", "fed"),
    (r"fomc.*statement|monetary policy statement", "Заява ФРС за підсумками засідання", "rate"),
    (r"fomc.*projections|economic projections", "Економічні прогнози ФРС", "fed"),
    (r"fed chair .*speaks|powell speaks", "Виступ голови ФРС", "fed_speech"),
    (r"fomc .*speaks|fed .*speaks", "Виступ представника ФРС", "fed_speech"),
    (r"president .*speaks|trump speaks|biden speaks", "Виступ президента {c}", "fed_speech"),
    (r"speaks|testifies|press conference", "Виступ посадовця ({c})", "fed_speech"),
    (r"gdp", "Зростання економіки {c} (ВВП)", "gdp"),
    (r"core retail sales", "Базові роздрібні продажі у {c}", "retail"),
    (r"retail sales", "Роздрібні продажі у {c}", "retail"),
    (r"ism .*services|services pmi", "Ділова активність у сфері послуг {c}", "activity"),
    (r"ism .*manufacturing|manufacturing pmi|manufacturing index|philly fed|empire state", "Ділова активність у промисловості {c}", "activity"),
    (r"pmi", "Індекс ділової активності {c}", "activity"),
    (r"consumer (confidence|sentiment)|uom consumer", "Споживчі настрої у {c}", "sentiment"),
    (r"durable goods", "Замовлення на товари тривалого користування у {c}", "retail"),
    (r"(existing|new|pending) home sales|housing starts|building permits", "Ринок житла у {c}", "housing"),
    (r"crude oil inventories", "Запаси нафти у {c}", "other"),
    (r"treasury|bond auction|note auction", "Аукціон облігацій казначейства {c}", "other"),
    (r"trade balance", "Торговельний баланс {c}", "other"),
]
_CAT_EXPLAIN = {
    "wages": "Важлива статистика, під час виходу якої {t} може різко рухатися.",
    "jobs": "Головна статистика ринку праці. Від неї залежать очікування щодо ставки ФРС, тому {t} часто різко рухається в момент виходу.",
    "claims": "Щотижневий показник ринку праці. Сильне відхилення від прогнозу може різко зрушити {t}.",
    "inflation": "Показує, як швидко ростуть ціни. Від цього залежить ставка ФРС, тому {t} може різко рухатися.",
    "rate": "Рішення про ставку — одна з головних подій для всіх ринків. {t} може різко рухатися в обидва боки.",
    "fed": "Документ ФРС про майбутню політику. Ринок шукає в ньому підказки щодо ставки, {t} може різко рухатися.",
    "fed_speech": "Слова посадовця можуть змінити очікування щодо ставки, тому {t} може різко рухатися.",
    "gdp": "Показує, чи росте економіка. Несподіваний результат може різко зрушити {t}.",
    "retail": "Показує, наскільки люди витрачають гроші. Відхилення від прогнозу може різко зрушити {t}.",
    "activity": "Показує стан бізнесу. Несподіваний результат може різко зрушити {t}.",
    "sentiment": "Показує настрої споживачів. Відхилення від прогнозу може різко зрушити {t}.",
    "housing": "Показує стан ринку житла. Несподіваний результат може на хвилину розхитати {t}.",
    "other": "Важлива статистика, під час виходу якої {t} може різко рухатися.",
}
_GENERIC_TITLE = "Важлива економічна новина {c}"
_LATIN = re.compile(r"[A-Za-z]")


def country_ua(code: Any) -> str:
    return COUNTRY_UA.get(str(code or "").upper(), "")


def classify(title: Any, country: Any = "USD") -> Tuple[str, str]:
    """(українська назва, категорія). Англійського тексту в назві немає ніколи."""
    t = str(title or "").lower()
    c = country_ua(country) or "США"
    for pat, ua, cat in _RULES:
        if re.search(pat, t):
            return ua.format(c=c), cat
    return _GENERIC_TITLE.format(c=c), "other"


def title_ua(title: Any, country: Any = "USD") -> str:
    ua, _ = classify(title, country)
    return _LATIN.sub("", ua) if _LATIN.search(ua) else ua


def kyiv_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(KYIV)


def when_ua(ts: float, now: Optional[float] = None) -> str:
    """Час за Києвом: сьогодні — «15:30»; інший день — «пʼятниця, 02.10 о 15:30»."""
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    e, n = kyiv_dt(ts), kyiv_dt(now)
    if e.date() == n.date():
        return e.strftime("%H:%M")
    return f"{WEEKDAY_UA[e.weekday()]}, {e.strftime('%d.%m')} о {e.strftime('%H:%M')}"


def _hm(ts: float) -> str:
    return kyiv_dt(ts).strftime("%H:%M")


def describe(event: Dict[str, Any], *, ticker: str = "BTC", before_min: int = 30, after_min: int = 15, now: Optional[float] = None) -> Dict[str, Any]:
    """Опис події для користувача — лише українською. window — «15:00–15:45» (Київ)."""
    ts = float(event["ts"])
    ua, cat = classify(event.get("title"), event.get("country"))
    ua = _LATIN.sub("", ua) if _LATIN.search(ua) else ua
    tk = re.sub(r"USDT?$", "", str(ticker or "BTC").upper()) or "BTC"
    start, end = ts - before_min * 60, ts + after_min * 60
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    blocked = start <= now <= end
    explain = _CAT_EXPLAIN.get(cat, _CAT_EXPLAIN["other"]).format(t=tk)
    pause = f"Нові входи з {_hm(start)} до {_hm(end)} не відкриваємо."
    scen = (f"Зараз діє пауза: новий вхід за цим сценарієм почекає до {_hm(end)}." if blocked
            else f"Якщо ціна дійде до зони входу в цей час, вхід почекає до {_hm(end)}.")
    return {"title_ua": ua, "when": when_ua(ts, now), "window": f"{_hm(start)}–{_hm(end)}", "blocked": blocked,
            "headline": f"{ua} — {when_ua(ts, now)}", "text": f"{explain} {pause} {scen}"}


def news_view(*, ticker: str = "BTC", now: Optional[float] = None) -> Dict[str, Any]:
    """Для Mini App. Лише українські рядки; англійської назви в відповіді немає."""
    import office_calendar as cal

    now = datetime.now(timezone.utc).timestamp() if now is None else now
    data = cal.load(now)
    if data["status"] != "DATA_OK":
        return {"status": "DATA_UNAVAILABLE", "blocked": False, "item": None,
                "note": "Календар новин недоступний — пауза перед новинами зараз не діє."}
    before = cal._env_int("OFFICE_CALENDAR_BEFORE_MIN", 30)
    after = cal._env_int("OFFICE_CALENDAR_AFTER_MIN", 15)
    ev = cal.block_for(now, data["events"]) if cal.block_enabled() else None
    ev = ev or cal.next_event(now, data["events"])
    if not ev:
        return {"status": "DATA_OK", "blocked": False, "item": None, "note": "Важливих новин найближчим часом немає."}
    item = describe(ev, ticker=ticker, before_min=before, after_min=after, now=now)
    return {"status": "DATA_OK", "blocked": item["blocked"], "item": item, "note": ""}

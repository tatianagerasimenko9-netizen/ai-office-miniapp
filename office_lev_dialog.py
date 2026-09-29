"""Діалог із Левом: відповіді лише з фактичного циклу Лева на свіжих свічках і з журналу БД.

Без LLM і без шаблонних вигадок: кожне число походить з lev_cycle / бази; немає даних — так і сказано.
Лев може відповісти «NO TRADE». Не ордер, не виконання, у БД нічого не пише (record=False).
Один і той самий модуль обслуговує Telegram (/lev …) і Mini App (/api/v2/lev).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from office_price_format import format_px

STALE_FACTOR = 2.5          # M15: свічка старша за 2.5 інтервалу — дані застарілі
M15_SEC = 900
CACHE_SEC = 25
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
BUDGET_PER_MIN = 20         # захист публічного endpoint від навантаження на Binance
_BUDGET: List[float] = []
_STOP = {"LEV", "USDT", "BTC_", "H1", "H4", "D1", "M15", "M5", "NO", "TRADE", "SL", "TP", "TP1", "TP2", "RR"}
INTENTS = (
    ("changes", ("змін", "оновл", "що нов", "історі", "було", "стало", "порівн")),
    ("invalid", ("інвалід", "скасу", "скасув", "відмін")),
    ("confirm", ("підтверд", "чекаєш", "чекаєте", "умов", "що потрібно", "тригер")),
    ("why", ("чому", "причин", "поясни", "обґрунт")),
    ("plan", ("план", "рівн", "вхід", "зона", "стоп", "тейк", "sl", "tp")),
)


def explicit_symbol(text: str) -> Optional[str]:
    """Символ, названий у тексті: XXXUSDT (будь-який регістр) або тикер ВЕЛИКИМИ (BTC, SOL). Немає — None."""
    raw = str(text or "")
    m = re.search(r"\b([A-Za-z0-9]{2,12}USDT)\b", raw, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    for tok in re.findall(r"\b([A-Z]{2,10})\b", raw):
        if tok not in _STOP:
            return tok + "USDT"
    return None


def extract_symbol(text: str, default: str = "BTCUSDT") -> str:
    return explicit_symbol(text) or default


def detect_intent(text: str) -> str:
    low = str(text or "").lower()
    for name, keys in INTENTS:
        if any(k in low for k in keys):
            return name
    return "full"


def _age_min(ts: Any, now: float) -> Optional[float]:
    try:
        return round((now - datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()) / 60, 1)
    except Exception:  # noqa: BLE001
        return None


def compute(db_path: str, symbol: str, *, now: Optional[float] = None, use_cache: bool = True) -> Dict[str, Any]:
    """Свіжий цикл Лева для символу. Помилка/немає даних → NO TRADE з причиною (ніколи не вигадуємо)."""
    t = time.time() if now is None else now
    sym = extract_symbol(symbol, default="BTCUSDT")
    hit = _CACHE.get(sym)
    if use_cache and hit and t - hit[0] < CACHE_SEC:
        return {**hit[1], "cached": True}
    from office_legacy_guard import lev_cycle_for_symbol

    _BUDGET[:] = [x for x in _BUDGET if t - x < 60]
    if len(_BUDGET) >= BUDGET_PER_MIN:
        cyc = {"action": "SKIP", "send": False, "reason": "забагато запитів за хвилину — спробуй за мить"}
        return {"symbol": sym, "cycle": cyc, "data_age_min": None, "data_stale": True, "computed_at": t, "cached": False}
    _BUDGET.append(t)
    try:
        cyc = lev_cycle_for_symbol(db_path, sym, None, record=False)
    except Exception as exc:  # noqa: BLE001
        cyc = {"action": "SKIP", "send": False, "reason": f"аналіз недоступний: {type(exc).__name__}"}
    age = _age_min(cyc.get("data_as_of"), t)
    stale = age is None or age * 60 > M15_SEC * STALE_FACTOR
    out = {"symbol": sym, "cycle": cyc, "data_age_min": age, "data_stale": stale, "computed_at": t, "cached": False}
    _CACHE[sym] = (t, out)
    if len(_CACHE) > 200:
        _CACHE.clear()
    return out


def verdict(res: Dict[str, Any]) -> Tuple[str, str]:
    """(код, короткий висновок). Застарілі/відсутні дані → завжди NO_TRADE."""
    cyc = res["cycle"]
    if res.get("data_stale"):
        return "NO_TRADE", "NO TRADE — свіжих даних немає, висновку не роблю"
    act = str(cyc.get("action") or "").upper()
    if cyc.get("send") and act == "SEND":
        return "PLAN", "ПЛАН — сценарій підтверджено Левом (рішення й ордер — лише твої)"
    if act == "WAIT":
        return "WAIT", "ЧЕКАЄМО — підтвердження ще немає, входу немає"
    return "NO_TRADE", "NO TRADE — входу немає"


_REASON_RX = (
    (re.compile(r"ATR day_used ([\d.]+)%"), lambda m: f"Ціна вже пройшла близько {float(m.group(1)):.0f}% звичайного денного руху — входити пізно."),
    (re.compile(r"немає збігів|менше 2 збігів"), lambda m: "Немає достатньо підстав для входу."),
    (re.compile(r"пробій ренджу|подія, не вхід"), lambda m: "Ціна вийшла з діапазону — це рух, а не вхід."),
    (re.compile(r"суперечн"), lambda m: "Індикатори суперечать напрямку."),
    (re.compile(r"пул рівних|рівних лоїв|рівних хаїв"), lambda m: "Стоп ставав би там, де зазвичай збирають стопи."),
    (re.compile(r"застар|STALE|DATA_"), lambda m: "Дані ненадійні."),
)


def plain_reason(reason: Any) -> str:
    """Причина людською мовою; повний технічний текст лишається в «Деталях» Mini App."""
    txt = str(reason or "")
    for rx, fn in _REASON_RX:
        m = rx.search(txt)
        if m:
            return fn(m)
    return "Підтвердженого напряму зараз немає."


def _fp(v: Any, sym: str) -> str:
    try:
        return format_px(float(v), sym) if v is not None else "—"
    except Exception:  # noqa: BLE001
        return "—"


def _view(res: Dict[str, Any], code: str, *, tracking: bool, watch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cyc = res["cycle"]
    sym = res["symbol"]
    draft = cyc.get("draft") or {}
    conf = draft.get("confluence") or {}
    side = str(cyc.get("direction") or draft.get("direction") or "").upper()
    lo, hi = draft.get("zone_lo"), draft.get("zone_hi")
    price = draft.get("price") or conf.get("price")
    state = {"PLAN": "CONFIRMED", "WAIT": "WAIT"}.get(code, "NO_TRADE")
    if res.get("data_stale"):
        state = "STALE"
    has_zone = lo is not None and hi is not None and side in ("LONG", "SHORT")
    if state == "WAIT" and not (has_zone and draft.get("invalidation") is not None):
        state = "NO_TRADE"  # без зони чи рівня скасування «чекаємо» — порожня обіцянка
    v = {"symbol": sym, "state": state, "direction": side, "price": price, "zone_lo": lo, "zone_hi": hi,
         "invalidation": draft.get("invalidation"), "wait_tf": conf.get("wait_tf") or "M15", "scenario_tf": "H1",
         "plan": {"entry": cyc.get("entry"), "sl": cyc.get("sl"), "tp1": cyc.get("tp1"), "tp2": cyc.get("tp2") or draft.get("tp2")},
         "tracking": tracking, "expires_at": (watch or {}).get("expires_at"), "reason": plain_reason(cyc.get("reason"))}
    if state == "CONFIRMED":
        from office_lev_watch import check_plan

        bad = check_plan(sym, side, v["plan"], lo, hi)
        if bad:
            v.update(state="REJECTED", reason=bad)
    return v


def changes_text(db_path: str, sym: str) -> str:
    from office_lev_watch import recent_notes
    from office_user_messages import ticker

    notes = recent_notes(db_path, symbol=sym, limit=5)
    if not notes:
        return (f"⚪ {ticker(sym)} · ЗМІН ПОКИ НЕ БУЛО\nЛев ще не оголошував і не змінював план по цій монеті. "
                "Коли з'явиться — тут буде видно, що саме змінилось.")
    lines = [f"🕘 {ticker(sym)} · ЩО ЗМІНЮВАЛОСЬ"]
    for n in notes:
        head = str(n.get("text") or "").split("\n", 1)[0]
        lines.append(f"{str(n.get('ts'))[5:16].replace('T', ' ')} UTC — {head}")
    return "\n".join(lines)


def _card_row(db_path: str, symbol: str) -> Optional[Dict[str, Any]]:
    """Найновіший ВІДПРАВЛЕНИЙ сценарій Лева по монеті (ACTIVE/CONFIRMED/HIT_ENTRY), якщо є."""
    from office_bridge import _fetchall

    try:
        rows = _fetchall(db_path, "SELECT signal_id, symbol, direction, entry_low, entry_high, sl, tp1, tp2, rr, status, ts_created, ts_updated, outcome, analysis_note "
                                  "FROM office_signals WHERE symbol = ? AND status IN ('ACTIVE','CONFIRMED','HIT_ENTRY') ORDER BY ts_updated DESC LIMIT 1", (symbol,))
    except Exception:  # noqa: BLE001
        return None
    if not rows:
        return None
    keys = ("signal_id", "symbol", "direction", "entry_low", "entry_high", "sl", "tp1", "tp2", "rr", "status", "ts_created", "ts_updated", "outcome", "analysis_note")
    return dict(zip(keys, rows[0]))


def _answer_from_card(db_path: str, sym: str, intent: str) -> Optional[Dict[str, Any]]:
    """Якщо по монеті вже є відправлений сценарій — відповідаємо тим самим станом, що й Mini App (одне джерело правди)."""
    row = _card_row(db_path, sym) if db_path else None
    if not row:
        return None
    try:
        import office_mini_v2 as MV
        from office_thesis_journal import latest_thesis
        from office_user_messages import render_human, ticker

        sid = str(row["signal_id"])
        h = MV._human_view(row, latest_thesis(db_path, sid), MV.scenario_events(sid))
        if intent == "invalid":
            body = f"{h['icon']} {ticker(sym)} · ЩО СКАСУЄ ПЛАН\n{h.get('cancel') or 'Рівень скасування система не визначила.'}"
        elif intent == "changes":
            hist = h.get("history") or []
            body = (f"🕘 {ticker(sym)} · ЩО ЗМІНЮВАЛОСЬ\n" + "\n".join(f"{str(x['ts'])[5:16].replace('T', ' ')} UTC — {x['text']}" for x in hist)) if hist \
                else f"⚪ {ticker(sym)} · ЗМІН ПОКИ НЕ БУЛО"
        else:
            body = render_human(h)
        return {"ok": True, "symbol": sym, "verdict": {"READY": "PLAN", "WAIT": "WAIT", "IN_ZONE": "WAIT"}.get(h["state"], "NO_TRADE"), "intent": intent,
                "text": body, "state": h["state"], "data_age_min": None, "data_stale": h["state"] == "NO_DATA", "tracking": False,
                "order_authorized": False, "source": "scenario"}
    except Exception as exc:  # noqa: BLE001
        print(f"[lev-dialog] card answer failed {sym}: {type(exc).__name__}: {exc}")
        return None


def answer(db_path: str, text: str, *, symbol: Optional[str] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Відповідь Лева людською мовою. {ok, symbol, verdict, intent, text, data_age_min, data_stale, tracking}."""
    from office_lev_watch import notify_enabled, register
    from office_user_messages import render, ticker, _cancel_line, _px

    sym = explicit_symbol(text) or symbol or "BTCUSDT"
    intent = detect_intent(text)
    card_ans = _answer_from_card(db_path, sym, intent)
    if card_ans is not None:
        return card_ans
    res = compute(db_path, sym, now=now)
    sym = res["symbol"]
    code, _head = verdict(res)
    v = _view(res, code, tracking=False)
    watch = None
    can_watch = v["state"] in ("WAIT", "CONFIRMED") and not res.get("data_stale")
    if can_watch and db_path:
        try:
            watch = register(db_path, symbol=sym, direction=v["direction"], zone_lo=v["zone_lo"], zone_hi=v["zone_hi"],
                             invalidation=v["invalidation"], wait_tf=v["wait_tf"], state=v["state"],
                             plan=v["plan"] if v["state"] == "CONFIRMED" else None)
        except Exception as exc:  # noqa: BLE001
            print(f"[lev-watch] register failed {sym}: {type(exc).__name__}: {exc}")
    tracking = bool(watch) and notify_enabled()   # обіцянку «напишу сам» — лише коли умова збережена і сповіщення справді ввімкнені
    v = _view(res, code, tracking=tracking, watch=watch)
    if intent == "changes":
        body = changes_text(db_path, sym)
    elif intent == "invalid":
        if v["state"] in ("WAIT", "CONFIRMED") and v.get("invalidation") is not None:
            body = f"🔴 {ticker(sym)} · ЩО СКАСУЄ ПЛАН\nПлан скасується {_cancel_line(v)}"
        else:
            body = f"⚪ {ticker(sym)} · ПЛАНУ ЗАРАЗ НЕМАЄ\nСкасовувати нічого: підтвердженого сценарію по цій монеті зараз немає."
    else:
        body = render(v)
    return {"ok": True, "symbol": sym, "verdict": code, "intent": intent, "text": body, "state": v["state"],
            "data_age_min": res.get("data_age_min"), "data_stale": bool(res.get("data_stale")), "tracking": tracking,
            "order_authorized": False}


CONTEXT_SEC = 30 * 60
LAST: Dict[str, Any] = {"symbol": None, "at": 0.0}   # контекст діалогу: «а інвалідація?» без монети → та, про яку щойно говорили
_CMD = re.compile(r"^\s*(?:[/!]lev\b|лев\b|lev\b)[\s,:;\-—]*(.*)$", re.IGNORECASE | re.DOTALL)
ASK_SYMBOL = "Про яку монету? Напиши, наприклад: /lev BTC або «Лев, аналіз SOL»."


def parse_command(text: str) -> Optional[str]:
    """Питання до Лева: '/lev BTC', '!lev що змінилось', 'Лев, аналіз SOL'. Не звернення → None; порожнє питання → ''."""
    m = _CMD.match(str(text or ""))
    return None if not m else m.group(1).strip()


def context_symbol(now: Optional[float] = None) -> Optional[str]:
    t = time.time() if now is None else now
    return LAST.get("symbol") if LAST.get("symbol") and t - float(LAST.get("at") or 0) <= CONTEXT_SEC else None


def parse_followup(text: str, now: Optional[float] = None) -> Optional[str]:
    """Уточнення без звернення до Лева («а інвалідація?») — лише в межах 30 хв після його відповіді
    і лише коли це схоже на питання про план. Інакше None: звичайна розмова з командою не перехоплюється."""
    raw = str(text or "").strip()
    if not raw or raw[0] in "/!" or len(raw) > 140 or context_symbol(now) is None:
        return None
    return raw if detect_intent(raw) != "full" else None


def ask(db_path: str, question: str, *, now: Optional[float] = None) -> Dict[str, Any]:
    """Діалог у Telegram. Монету визначаємо з питання або з попередньої відповіді (≤30 хв); не можемо — перепитуємо.
    Рівні іншої монети ніколи не підставляємо."""
    q = str(question or "").strip()
    sym = explicit_symbol(q) or context_symbol(now)
    if not sym:
        return {"ok": False, "needs_symbol": True, "text": ASK_SYMBOL, "order_authorized": False}
    res = answer(db_path, q or "аналіз", symbol=sym, now=now)
    LAST["symbol"], LAST["at"] = res["symbol"], (time.time() if now is None else now)
    return res

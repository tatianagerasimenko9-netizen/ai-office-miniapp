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


def _fp(v: Any, sym: str) -> str:
    try:
        return format_px(float(v), sym) if v is not None else "—"
    except Exception:  # noqa: BLE001
        return "—"


def _db_scenario_line(db_path: str, sym: str, direction: str) -> str:
    try:
        from office_bridge import _fetchall

        rows = _fetchall(db_path, "SELECT signal_id, direction, status, ts_updated FROM office_signals WHERE symbol = ? "
                         "ORDER BY ts_updated DESC LIMIT 3", (sym,))
    except Exception:  # noqa: BLE001
        return "Сценарії в базі: недоступно"
    if not rows:
        return "Сценаріїв у базі по символу немає"
    return "У базі: " + "; ".join(f"{r[1]} {r[2]} (оновл. {str(r[3])[:16]})" for r in rows)


def _risk_line(db_path: str, sym: str) -> str:
    try:
        from office_bridge import _fetchone

        row = _fetchone(db_path, "SELECT ts_utc, payload_json FROM office_events WHERE event_type = 'RISK_SHADOW_REVIEW' "
                        "AND payload_json LIKE ? ORDER BY id DESC LIMIT 1", (f'%"{sym}"%',))
    except Exception:  # noqa: BLE001
        return "Risk Officer (shadow): недоступно"
    if not row:
        return "Risk Officer (shadow): для цього символу ще не було перевірок"
    try:
        p = json.loads(row[1])
    except Exception:  # noqa: BLE001
        return "Risk Officer (shadow): запис нечитабельний"
    return f"Risk Officer (shadow, {str(row[0])[:16]}): {'заблокував би' if p.get('would_veto') else 'не блокував би'} — лише інформація"


def changes_lines(db_path: str, sym: str, limit: int = 6) -> List[str]:
    try:
        from office_bridge import _fetchall

        rows = _fetchall(db_path, "SELECT ts_utc, payload_json FROM office_events WHERE event_type = 'THESIS_VERSION' "
                         "AND payload_json LIKE ? ORDER BY id DESC LIMIT ?", (f'%"symbol": "{sym}"%', limit))
    except Exception:  # noqa: BLE001
        return ["Журнал змін недоступний"]
    out = []
    for ts, pj in rows or []:
        try:
            p = json.loads(pj)
        except Exception:  # noqa: BLE001
            continue
        out.append(f"{str(ts)[5:16]} · {p.get('direction')} · {p.get('state')} · режим {p.get('regime')} · Лев: {p.get('lev_action')}")
    return out or ["Версій тези для цього символу ще немає — змін не бачу"]


def answer(db_path: str, text: str, *, symbol: Optional[str] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Відповідь Лева на запит. Повертає {ok, symbol, verdict, intent, text, data_age_min, data_stale}."""
    sym = explicit_symbol(text) or symbol or "BTCUSDT"
    intent = detect_intent(text)
    res = compute(db_path, sym, now=now)
    sym = res["symbol"]
    cyc = res["cycle"]
    code, head = verdict(res)
    draft = cyc.get("draft") or {}
    conf = draft.get("confluence") or {}
    side = str(cyc.get("direction") or draft.get("direction") or "").upper()
    lo, hi = draft.get("zone_lo"), draft.get("zone_hi")
    age = res.get("data_age_min")
    price = draft.get("price") or conf.get("price")
    lines: List[str] = []
    fresh = "немає" if age is None else f"{age:g} хв тому"
    lines.append(f"🦁 Лев · {sym} · H1 · ціна {_fp(price, sym)} · остання свічка M15 (відкриття): {fresh}")
    if res.get("data_stale"):
        lines.append("⚠️ Дані застарілі або недоступні — не покладайся на цей екран, перевір Binance.")
    if intent in ("full", "why", "plan", "confirm", "invalid"):
        lines.append(f"Висновок: {head}")
    reason = str(cyc.get("reason") or "").strip()
    if intent in ("full", "why") and reason:
        lines.append(f"Причина: {reason}")
    has_zone = lo is not None and hi is not None and side in ("LONG", "SHORT")
    if intent in ("full", "plan"):
        if has_zone:
            tag = "План" if code == "PLAN" else "Кандидат-зона (це спостереження, не вхід)"
            lines.append(f"{tag}: {side} · зона {_fp(lo, sym)}–{_fp(hi, sym)}")
            if code == "PLAN":
                lines.append(f"SL {_fp(cyc.get('sl'), sym)} · TP1 {_fp(cyc.get('tp1'), sym)}")
        else:
            lines.append("Зони входу зараз немає.")
    if intent in ("full", "confirm") and has_zone and conf.get("confirm_wait"):
        lines.append(f"Що чекаю: {conf.get('confirm_wait')}")
    if intent in ("full", "invalid"):
        inv = draft.get("invalidation")
        lines.append(f"Скасується: закриття за {_fp(inv, sym)}" if inv is not None else "Інвалідація не визначена — сценарій не вважаю готовим.")
    if intent in ("full", "plan", "confirm") and conf.get("now_line"):
        lines.append(str(conf.get("now_line")))
    if intent == "full":
        alt = draft.get("alternative") or {}
        if alt.get("eligible"):
            lines.append(f"Альтернатива: {alt.get('direction')} {_fp(alt.get('zone_lo'), sym)}–{_fp(alt.get('zone_hi'), sym)}")
        lines.append(_db_scenario_line(db_path, sym, side))
        lines.append(_risk_line(db_path, sym))
    if intent == "changes":
        lines.append("Як змінювався сценарій (журнал тез):")
        lines.extend("· " + x for x in changes_lines(db_path, sym))
        lines.append(f"Зараз: {head}")
    lines.append("Не ордер. Рішення й ордер на біржі — лише твої.")
    return {"ok": True, "symbol": sym, "verdict": code, "intent": intent, "text": "\n".join(lines),
            "data_age_min": age, "data_stale": bool(res.get("data_stale")), "order_authorized": False}


LAST: Dict[str, Optional[str]] = {"symbol": None}   # контекст діалогу: «а інвалідація?» без символу → попередній символ
_CMD = re.compile(r"^\s*(?:[/!]lev\b|лев\b|lev\b)[\s,:;\-—]*(.*)$", re.IGNORECASE | re.DOTALL)


def parse_command(text: str) -> Optional[str]:
    """Питання до Лева: '/lev BTC', '!lev що змінилось', 'Лев, аналіз SOL'. Не звернення → None; порожнє питання → ''."""
    m = _CMD.match(str(text or ""))
    return None if not m else m.group(1).strip()


def ask(db_path: str, question: str, *, now: Optional[float] = None) -> Dict[str, Any]:
    res = answer(db_path, question or "аналіз", symbol=LAST.get("symbol"), now=now)
    LAST["symbol"] = res["symbol"]
    return res

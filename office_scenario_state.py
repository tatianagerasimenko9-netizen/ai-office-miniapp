"""Єдиний людський стан сценарію: одне джерело правди для Mini App (і тих самих слів у Telegram).

Вхід — рядок сценарію з БД, остання теза Лева, свіжість ціни, цілі за рівнями. Вихід — стан і готові
українські фрази. «План готовий» лише за ВСІХ умов: свіжа ціна · Лев підтвердив умову (статус CONFIRMED) ·
відома ціна підтвердження (вхід) · стоп · ціль 1 · рівень скасування · план проходить перевірки (як SEND).
Немає чогось — «План не готовий» із переліком, чого бракує. Статус ACTIVE (картку відправлено) НЕ означає готовий план.
Ордерів немає; порогів не змінює.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from office_price_format import format_px

STATES = {
    "WAIT": ("🟡", "Чекаємо", "w"),
    "IN_ZONE": ("🟡", "Ціна в зоні, підтвердження ще немає", "w"),
    "NOT_READY": ("🟠", "План не готовий", "w"),
    "OBSERVE": ("⚪", "Лише спостерігаємо", "n"),
    "READY": ("🟢", "План готовий", "g"),
    "CANCELLED": ("🔴", "План скасовано", "r"),
    "EXPIRED": ("⚪", "Час очікування минув", "n"),
    "DONE": ("⚪", "Сценарій завершено", "n"),
    "NO_DATA": ("⚠️", "Даних немає", "w"),
}
TF_UA = {"M5": "5-хвилинному", "M15": "15-хвилинному", "H1": "годинному"}
EVENT_UA = {
    "SIGNAL_ENTRY": "Лев склав план", "THESIS_VERSION": "Лев оновив план", "ZONE_REACHED": "Ціна досягла зони",
    "HIT_ENTRY": "Ціна досягла зони", "CONFIRMED": "Підтвердження отримано", "SCENARIO_CONFIRMED": "Підтвердження отримано",
    "CANCELLED": "План скасовано", "INVALIDATED": "План скасовано", "SCENARIO_EXPIRED": "Час очікування минув",
    "EXPIRED": "Час очікування минув",
}


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def px(v: Any, symbol: str) -> str:
    """Ціна для людини: українська кома, знак долара для USDT-пар."""
    try:
        out = format_px(float(v), symbol) if v is not None else ""
    except Exception:  # noqa: BLE001
        out = ""
    if not out:
        return "—"
    out = out.replace(".", ",")
    return f"{out} $" if str(symbol).upper().endswith("USDT") else out


def notify_verified() -> bool:
    """Ставимо 1 лише коли автоповідомлення реально спрацювало на живій події й доставлено."""
    return os.getenv("OFFICE_NOTIFY_VERIFIED", "").strip().lower() in ("1", "true", "yes", "on")


def _cancel_level(row: Dict[str, Any], thesis: Optional[Dict[str, Any]]) -> Optional[float]:
    note = str(row.get("analysis_note") or row.get("note") or "")
    m = re.search(r"cancel=([0-9.eE+-]+)", note)
    if m:
        return _f(m.group(1))
    inv = str((thesis or {}).get("invalidation") or "")
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)", inv)
    if m:
        return _f(m.group(1))
    return None


def _confirm_tf(thesis: Optional[Dict[str, Any]], row: Optional[Dict[str, Any]] = None) -> Optional[str]:
    m0 = re.search(r"\bconfirm=(M5|M15|H1)\b", str((row or {}).get("analysis_note") or ""))
    if m0:
        return m0.group(1)
    c = (thesis or {}).get("confirmation")
    text = " ".join(str(x) for x in c) if isinstance(c, list) else str(c or "")
    m = re.search(r"\b(M5|M15|H1)\b", text)
    return m.group(1) if m else None


def _confirmed_px(row: Dict[str, Any]) -> Optional[float]:
    m = re.search(r"confirmed_px=([0-9.eE+-]+)", str(row.get("analysis_note") or ""))
    return _f(m.group(1)) if m else None


def _tf_from_row(row: Dict[str, Any]) -> str:
    m = re.search(r"(?:tf|timeframe)=([A-Za-z0-9]+)", str(row.get("analysis_note") or ""))
    return (m.group(1) if m else "H1").upper()


def _too_old(row: Dict[str, Any], now: Optional[datetime]) -> bool:
    """Картка Лева живе TTL її таймфрейму (H1 — 12 год, M15 — 3 год); підтверджений план не застарює за часом."""
    if row.get("_has_position"):
        return False   # угода вже відкрита вручну — закінчення часу дії сигналу не припиняє її супровід
    if str(row.get("status") or "").upper() == "CONFIRMED":
        # підтверджений план діє обмежений час (див. office_scenario_lifecycle.plan_valid_sec), далі знімається
        try:
            from office_scenario_lifecycle import _ts, plan_valid_sec

            m = re.search(r"(?:tf|timeframe)=([A-Za-z0-9]+)", str(row.get("analysis_note") or ""))
            t0 = _ts(row.get("ts_updated"))
            return bool(t0 and (now or datetime.now(timezone.utc)).timestamp() > t0 + plan_valid_sec(m.group(1) if m else "H1"))
        except Exception:  # noqa: BLE001
            return False
    try:
        from office_confluence import ttl_sec

        m = re.search(r"(?:tf|timeframe)=([A-Za-z0-9]+)", str(row.get("analysis_note") or ""))
        tf = (m.group(1) if m else "H1").upper()
        born = datetime.fromisoformat(str(row.get("ts_created")).replace("Z", "+00:00"))
        if born.tzinfo is None:
            born = born.replace(tzinfo=timezone.utc)
        return ((now or datetime.now(timezone.utc)) - born).total_seconds() >= ttl_sec(tf)
    except Exception:  # noqa: BLE001
        return False


def history(events: List[Dict[str, Any]], limit: int = 8) -> List[Dict[str, str]]:
    """Події людською мовою, без кодів і без однакових підряд."""
    out: List[Dict[str, str]] = []
    for e in events or []:
        txt = EVENT_UA.get(str(e.get("type") or "").upper())
        if not txt or (out and out[-1]["text"] == txt):
            continue
        out.append({"ts": str(e.get("ts") or ""), "text": txt})
    return out[-limit:]


def build(row: Dict[str, Any], *, thesis: Optional[Dict[str, Any]], price: Dict[str, Any], targets: Optional[Dict[str, Any]] = None,
          events: Optional[List[Dict[str, Any]]] = None, plan_check=None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Людський вигляд сценарію. price: {price, fresh, as_of}. plan_check(symbol, side, plan, lo, hi) → None|причина."""
    sym = str(row.get("symbol") or "").upper()
    side = str(row.get("direction") or "").upper()
    status = str(row.get("status") or "").upper()
    lo, hi = _f(row.get("entry_low")), _f(row.get("entry_high"))
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    tp1, sl = _f(row.get("tp1")), _f(row.get("sl"))
    cancel = _cancel_level(row, thesis)
    ctf = _confirm_tf(thesis, row)
    up = "вгору" if side != "SHORT" else "вниз"
    cross = "нижче" if side != "SHORT" else "вище"
    dont = "не купувати" if side != "SHORT" else "не продавати"
    act = "Купівля" if side != "SHORT" else "Продаж"
    p = _f(price.get("price"))
    fresh = bool(price.get("fresh")) and p is not None
    missing: List[str] = []
    zone_txt = f"{px(lo, sym).replace(' $', '')}–{px(hi, sym)}" if lo is not None and hi is not None and lo != hi else (px(lo, sym) if lo is not None else "")
    v: Dict[str, Any] = {"symbol": sym, "ticker": sym[:-4] if sym.endswith("USDT") else sym, "action_ua": act, "zone": zone_txt,
                         "price": px(p, sym) if fresh else None, "price_as_of": price.get("as_of"), "price_fresh": fresh,
                         "cancel_level": px(cancel, sym) if cancel is not None else None, "updated_at": row.get("ts_updated") or row.get("ts_created"),
                         "history": history(events or [])}
    observe = str(row.get("signal_id") or "").startswith("watch-") or (sl is None and tp1 is None and cancel is None)
    if status in ("CANCELLED", "INVALIDATED"):
        state = "CANCELLED"
    elif status == "EXPIRED":
        state = "EXPIRED"
    elif status in ("HIT_SL", "HIT_TP1", "HIT_TP2", "CLOSED"):
        state = "DONE"
    elif _too_old(row, now):
        state = "EXPIRED"          # строк дії сценарію минув, навіть якщо статус у базі ще не оновлено
    elif not fresh:
        state = "NO_DATA"
    elif observe:
        state = "OBSERVE"
    else:
        if cancel is None:
            missing.append("не визначено рівень скасування")
        if ctf is None:
            missing.append("точну умову підтвердження ще не записано")
        confirmed = status == "CONFIRMED"
        inside = lo is not None and hi is not None and lo <= p <= hi
        if confirmed:
            entry = _confirmed_px(row)
            plan = {"entry": entry, "sl": sl, "tp1": tp1}
            if entry is None:
                missing.append("не збережено ціну входу в момент підтвердження")
            if sl is None:
                missing.append("немає стопа")
            if tp1 is None:
                missing.append("немає цілі 1")
            if not missing and plan_check:
                bad = plan_check(sym, side, plan, lo, hi)
                if bad:
                    missing.append(bad)
            state = "READY" if not missing else "NOT_READY"
            if state == "READY":
                tg = targets or {}
                v["plan"] = {"entry": px(entry, sym), "stop": px(sl, sym), "tp1": px(tp1, sym),
                             "tp2": px(tg["tp2"]["price"], sym) + f" ({tg['tp2']['why']})" if tg.get("tp2") else "немає обґрунтованої",
                             "tp3": (px(tg["tp3"]["price"], sym) + f" ({tg['tp3']['why']})") if tg.get("tp3") else "немає обґрунтованої"}
                from office_alert_gate import fee_round_trip_pct

                fee = fee_round_trip_pct()
                to_tp1 = abs(tp1 - entry) / entry * 100.0
                to_sl = abs(entry - sl) / entry * 100.0
                v["levels"] = {"entry": entry, "sl": sl, "tp1": tp1, "tp2": (tg.get("tp2") or {}).get("price"), "tp3": (tg.get("tp3") or {}).get("price"), "cancel": cancel}
                try:
                    from office_scenario_lifecycle import kyiv_hhmm, plan_valid_sec, _ts as _lts

                    t_conf = _lts(row.get("ts_updated"))
                    if t_conf:
                        v["plan"]["valid_until"] = kyiv_hhmm(t_conf + plan_valid_sec(_tf_from_row(row)))
                except Exception:  # noqa: BLE001
                    pass
                v["plan"]["potential"] = f"до цілі 1 ≈ {to_tp1:.2f}% (≈ {max(to_tp1 - fee, 0):.2f}% після комісій), до стопа ≈ {to_sl:.2f}%".replace(".", ",")
        elif missing:
            state = "NOT_READY"
        elif inside:
            state = "IN_ZONE"
        else:
            state = "WAIT"
    icon, title, tone = STATES[state]
    v.update(state=state, state_ua=title, icon=icon, tone=tone, missing=missing)
    tf_txt = TF_UA.get(ctf or "M15", "15-хвилинному")
    if state == "WAIT":
        if p is not None and hi is not None and ((side != "SHORT" and p > hi) or (side == "SHORT" and lo is not None and p < lo)):
            why = "Ціна вже " + ("вища" if side != "SHORT" else "нижча") + " за зону — наздоганяти не потрібно."
        else:
            why = "Підтвердження ще немає."
        v["headline"] = f"Зараз {dont}. {why}"
    elif state == "IN_ZONE":
        v["headline"] = f"Зараз {dont}: ціна в зоні, але розвороту {up} ще немає."
    elif state == "NOT_READY":
        v["headline"] = "Зараз не входити. План ще не готовий: " + "; ".join(m.rstrip(".") for m in missing) + "."
    elif state == "OBSERVE":
        v["headline"] = "Плану ще немає: Лев лише стежить за рівнем. Входити не можна."
    elif state == "READY":
        v["headline"] = "Умови виконано. Рішення про вхід — твоє, ордер Офіс не ставить."
    elif state == "CANCELLED":
        v["headline"] = "План скасовано — не входити."
    elif state == "EXPIRED":
        v["headline"] = "Час очікування минув — план більше не діє."
    elif state == "DONE":
        v["headline"] = "Сценарій завершено (це модель, не твоя угода)."
    else:
        v["headline"] = "Свіжої ціни немає — висновку не роблю. Перевір ціну на Binance."
    if state in ("WAIT", "IN_ZONE", "NOT_READY") and zone_txt:
        v["wait"] = (f"Повернення ціни в зону {zone_txt}. Далі Лев дивиться на {tf_txt} графіку, чи є розворот {up}. "
                     "Поки його немає — входити не можна.")
        if ctf is None:
            v["wait"] += " Точну умову підтвердження система поки не записала."
    if state in ("WAIT", "IN_ZONE", "NOT_READY", "READY") and cancel is not None:
        v["cancel"] = f"Якщо годинна свічка закриється {cross} {px(cancel, sym)}."
    elif state in ("WAIT", "IN_ZONE", "NOT_READY"):
        v["cancel"] = "Рівень скасування система не визначила — його потрібно уточнити, а не вважати попередній стоп готовим правилом."
    if state in ("WAIT", "IN_ZONE"):
        v["next"] = ("Лев перевіряє умову в наступних циклах і напише, коли ціна дійде до зони, з'явиться підтвердження або план скасується."
                     if notify_verified() else
                     "Лев перевіряє умову в наступних циклах. Автоматичне повідомлення ще не підтверджено на живій події — заглядай сюди.")
    elif state == "READY":
        v["next"] = "Лев напише, якщо план втратить чинність." if notify_verified() else "Слідкуй за рівнем скасування. Автоматичне повідомлення ще не підтверджено на живій події."
    elif state in ("CANCELLED", "EXPIRED", "DONE"):
        v["next"] = "Новий план з'явиться, коли Лев знайде нову можливість."
    if state != "READY" and state not in ("CANCELLED", "EXPIRED", "DONE", "NO_DATA"):
        prelim = []
        if tp1 is not None:
            prelim.append(f"Ціль 1: {px(tp1, sym)}")
        if targets and targets.get("tp2"):
            prelim.append(f"Ціль 2: {px(targets['tp2']['price'], sym)} ({targets['tp2']['why']})")
        else:
            prelim.append("Ціль 2: немає обґрунтованої")
        v["prelim"] = prelim
        v["prelim_note"] = "Попередньо. Не для входу. Стоп, ризик і потенціал покажемо після підтвердження й конкретної ціни входу."
    return v


def list_label(row: Dict[str, Any]) -> Dict[str, str]:
    """Підпис у списку — без ціни, тож НІКОЛИ не «План готовий» (це вирішує лише сторінка сценарію зі свіжою ціною)."""
    status = str(row.get("status") or "").upper()
    if status in ("CANCELLED", "INVALIDATED"):
        key = "CANCELLED"
    elif status == "EXPIRED":
        key = "EXPIRED"
    elif status in ("HIT_SL", "HIT_TP1", "HIT_TP2", "CLOSED"):
        key = "DONE"
    elif str(row.get("signal_id") or "").startswith("watch-") or (row.get("sl") is None and row.get("tp1") is None):
        key = "OBSERVE"
    elif status == "CONFIRMED":
        return {"state": "CHECK", "icon": "🟠", "text": "Підтверджено — відкрий, щоб перевірити план", "tone": "w"}
    else:
        key = "WAIT"
    icon, text, tone = STATES[key]
    return {"state": key, "icon": icon, "text": text, "tone": tone}

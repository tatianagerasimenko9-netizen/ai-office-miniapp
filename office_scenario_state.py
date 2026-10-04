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
    "EXPIRED": "Час очікування минув", "SIGNAL_PLAN": "План готовий і надіслано в Telegram", "MILESTONE_TP1": "Ціна досягла TP1 сценарію", "MILESTONE_TP2": "Ціна досягла TP2 сценарію",
    "MILESTONE_TP3": "Ціна досягла TP3 сценарію", "MILESTONE_SL": "Ціна досягла стоп-рівня сценарію",
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
            from office_scenario_lifecycle import _ts, valid_until_ts

            t0 = _ts(row.get("ts_updated"))
            return bool(t0 and (now or datetime.now(timezone.utc)).timestamp() > valid_until_ts(t0, _tf_from_row(row)))
        except Exception:  # noqa: BLE001
            return False
    try:
        from office_scenario_ttl import deadline

        tf = _tf_from_row(row)
        born = datetime.fromisoformat(str(row.get("ts_created")).replace("Z", "+00:00"))
        if born.tzinfo is None:
            born = born.replace(tzinfo=timezone.utc)
        return (now or datetime.now(timezone.utc)).timestamp() >= deadline(born.timestamp(), tf)
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
          events: Optional[List[Dict[str, Any]]] = None, plan_check=None, now: Optional[datetime] = None,
          plan: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    # Канонічний знімок: готовий план, ДОСТАВЛЕНИЙ у Telegram (SIGNAL_PLAN). Він і є запис підтвердження; ціни/цілі/строк беремо з нього.
    frozen = plan if (plan and status == "CONFIRMED") else None
    if frozen:
        ctf = ctf or "M15"
        tp1 = _f(frozen.get("tp1")) if _f(frozen.get("tp1")) is not None else tp1
        sl = _f(frozen.get("sl")) if _f(frozen.get("sl")) is not None else sl
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
    elif (frozen and _f(frozen.get("valid_until_ts")) and (now or datetime.now(timezone.utc)).timestamp() > float(frozen["valid_until_ts"])) or (not frozen and _too_old(row, now)):
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
            entry = _f(frozen.get("entry")) if frozen and _f(frozen.get("entry")) is not None else _confirmed_px(row)
            _tp2 = _f(frozen.get("tp2")) if frozen else _f(row.get("tp2"))   # лише ЗАПИСАНИЙ TP2 (той самий, що в гейті й Telegram)
            plan = {"entry": entry, "sl": sl, "tp1": tp1, "tp2": _tp2}
            if entry is None:
                missing.append("не збережено ціну входу в момент підтвердження")
            if sl is None:
                missing.append("немає стопа")
            if tp1 is None:
                missing.append("немає цілі 1")
            if not missing and plan_check and not frozen:   # для доставленого READY гейт уже пройдено в момент сигналу; «зараз» рахуємо окремо (v["now"])
                bad = plan_check(sym, side, plan, lo, hi)
                if bad:
                    missing.append(bad)
            if not missing and not frozen:   # ціна вже за межею входу (RR після комісій < мінімуму) — сигнал неактуальний
                from office_alert_gate import max_entry_price

                _me = max_entry_price(side, sl, tp1, _tp2)
                if _me is not None and p is not None and ((side != "SHORT" and p > _me) or (side == "SHORT" and p < _me)):
                    missing.append(f"Ціна вже за межею входу ({px(_me, sym)}): потенціал до цілі замалий — сигнал неактуальний.")
            state = "READY" if not missing else "NOT_READY"
            if state == "READY":
                tg = targets or {}
                if frozen:   # TP2/TP3 — рівно ті, що в Telegram; без перерахунку зі структури
                    tg = {"tp2": {"price": _f(frozen.get("tp2")), "why": ""} if _f(frozen.get("tp2")) is not None else None,
                          "tp3": {"price": _f(frozen.get("tp3")), "why": ""} if _f(frozen.get("tp3")) is not None else None}
                v["plan"] = {"entry": px(entry, sym), "stop": px(sl, sym), "tp1": px(tp1, sym),
                             "tp2": (px(tg["tp2"]["price"], sym) + (f" ({tg['tp2']['why']})" if tg["tp2"].get("why") else "")) if tg.get("tp2") else "немає обґрунтованої",
                             "tp3": (px(tg["tp3"]["price"], sym) + (f" ({tg['tp3']['why']})" if tg["tp3"].get("why") else "")) if tg.get("tp3") else "немає обґрунтованої"}
                from office_alert_gate import fee_round_trip_pct

                fee = fee_round_trip_pct()
                to_tp1 = abs(tp1 - entry) / entry * 100.0
                to_sl = abs(entry - sl) / entry * 100.0
                try:
                    from office_alert_gate import max_entry_price
                    from office_position_size import plan_position_size

                    _me2 = max_entry_price(side, sl, tp1, _tp2)
                    _sz = plan_position_size(entry=entry, sl=sl, score=12, min_score=10, direction=side)
                    v["plan"]["max_entry"] = px(_me2, sym) if _me2 is not None else None
                    v["size"] = ({"usdt": _sz.get("size_usdt"), "risk_usd": float(_sz.get("depo") or 0) * float(_sz.get("risk_pct") or 0)}
                                 if _sz.get("ok") and _sz.get("size_usdt") else None)
                except Exception:  # noqa: BLE001
                    _me2 = None
                    v["size"] = None
                v["levels"] = {"max_entry": _me2, "entry": entry, "sl": sl, "tp1": tp1, "tp2": (tg.get("tp2") or {}).get("price"), "tp3": (tg.get("tp3") or {}).get("price"), "cancel": cancel}
                try:
                    from office_scenario_lifecycle import kyiv_hhmm, valid_until_ts, _ts as _lts

                    if frozen and _f(frozen.get("valid_until_ts")):
                        from office_ready_core import kyiv_stamp

                        v["plan"]["valid_until"] = kyiv_stamp(float(frozen["valid_until_ts"]))
                    else:
                        t_conf = _lts(row.get("ts_updated"))
                        if t_conf:
                            v["plan"]["valid_until"] = kyiv_hhmm(valid_until_ts(t_conf, _tf_from_row(row)))
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
    if state == "READY":   # колір і слово — за напрямком угоди (не за готовністю): 🟢 LONG / 🔴 SHORT
        icon = "🔴" if side == "SHORT" else "🟢"
        title = f"{'SHORT' if side == 'SHORT' else 'LONG'} · {title}"
    v.update(state=state, state_ua=title, icon=icon, tone=tone, missing=missing)
    if frozen and state == "READY":
        v["ready"], v["now"] = _ready_then(frozen, side, sym, p, fresh, lo, hi, plan_check)
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
    elif state == "READY" and v.get("ready"):
        v["headline"] = f"План підтверджено о {v['ready']['at_hhmm']} (Київ). " + ("Вхід за цим планом ще можна розглядати." if v["now"]["eligible"] is True else
                        ("Новий вхід за цим планом зараз не розглядати." if v["now"]["eligible"] is False else "Чи можна входити зараз — не перевірено (немає свіжої ціни)."))
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


def _plain_confirms(tags: List[str]) -> str:
    try:
        from office_user_messages import plain_confirms

        return plain_confirms([str(t) for t in tags])
    except Exception:  # noqa: BLE001
        return ""


def _ready_then(plan: Dict[str, Any], side: str, sym: str, price: Optional[float], fresh: bool, lo: Optional[float], hi: Optional[float], plan_check) -> tuple:
    """READY (історичний перехід, незмінний знімок) ≠ можливість увійти ЗАРАЗ (жива перевірка тим самим правилом гейта від поточної ціни)."""
    from office_ready_core import kyiv_stamp

    g = plan.get("gate") or {}
    conf = g.get("confirm") or {}
    ts = _f(plan.get("confirmed_ts"))
    try:
        from zoneinfo import ZoneInfo

        hhmm = datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Kyiv")).strftime("%H:%M") if ts else ""
    except Exception:  # noqa: BLE001
        hhmm = ""
    ready = {"at": ts, "at_hhmm": hhmm, "at_stamp": kyiv_stamp(ts) if ts else "", "entry": px(plan.get("entry"), sym), "max_entry": px(plan.get("max_entry"), sym) if plan.get("max_entry") else None,
             "rr_net": g.get("rr_net"), "rr_weighted": g.get("rr_weighted"), "rr_rule": g.get("rr_rule"), "risk_pct": g.get("risk_pct"),
             "confirm_tags": conf.get("tags") or [], "confirm_ua": _plain_confirms(conf.get("tags") or []), "confirm_mode": conf.get("mode"), "confirm_detail": conf.get("detail"),
             "valid_until": kyiv_stamp(float(plan["valid_until_ts"])) if _f(plan.get("valid_until_ts")) else None}
    now_v: Dict[str, Any] = {"eligible": None, "reasons": [], "price": px(price, sym) if fresh else None}
    if not fresh or price is None:
        return ready, now_v
    reasons: List[str] = []
    try:
        from office_alert_gate import max_entry_price, rr_gate

        sl, t1, t2 = _f(plan.get("sl")), _f(plan.get("tp1")), _f(plan.get("tp2"))
        me = max_entry_price(side, sl, t1, t2)
        if me is not None and ((side != "SHORT" and price > me) or (side == "SHORT" and price < me)):
            reasons.append(f"ціна вже за межею входу ({px(me, sym)})")
        gg = rr_gate(price, sl, t1, t2)
        now_v["rr_net"], now_v["rr_weighted"] = gg.get("rr_net"), gg.get("rr_weighted")
        if not gg.get("ok") and gg.get("reason"):
            reasons.append(str(gg["reason"]).rstrip("."))
        if plan_check:
            bad = plan_check(sym, side, {"entry": price, "sl": sl, "tp1": t1, "tp2": t2}, lo, hi)
            if bad and str(bad).rstrip(".") not in reasons and "Потенціал" not in str(bad):
                reasons.append(str(bad).rstrip("."))
    except Exception:  # noqa: BLE001
        now_v["eligible"] = None
        return ready, now_v
    now_v["reasons"] = reasons
    now_v["eligible"] = not reasons
    return ready, now_v


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

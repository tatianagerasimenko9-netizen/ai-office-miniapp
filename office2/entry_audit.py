"""Аудит «право на вхід» для карток радара: чи paper-вхід відбувся ПІСЛЯ власного тригера картки, чи просто від дотику ціни до рівня входу.

Лише вимірювання на закритих свічках (без lookahead), нічого не пише в БД і не змінює LIVE/paper-логіку.
Джерела формулювань (першоджерела Дарії, docs/sources/evidence.jsonl): D-FIB-REACTION-NOT-LIMITS («не став ліміти „по цифрах“, а дивись на реакцію ціни в зоні»),
D-NO-CONFIRMATION-NO-TRADE («Немає підтвердження — немає угоди», сценарій хибного пробою). Конкретний ТФ тригера (M1/M5/M15) і свічковий тригер у джерелах НЕ ПІДТВЕРДЖЕНО —
тут береться ТРИГЕР, який картка сама заявила (need_text / trigger_text); нових порогів не вводиться."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

M15 = 900.0
NUM = r"([0-9]+(?:[.,][0-9]+)?)"


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def trigger_of(card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Тригер, який картка заявила сама. Пріоритет: need_text (WATCH) → trigger_text (прийнятий Brain на M15). Не вгадуємо: не розпізнано → None."""
    need = str(card.get("need_text") or "")
    long_ = str(card.get("direction") or "").upper() != "SHORT"
    m = re.search(r"(вище|нижче)\s+" + NUM, need)
    if m:
        return {"kind": "CLOSE_BEYOND", "level": _num(m.group(2)), "above": m.group(1) == "вище"}
    m = re.search(r"назад у зону\s+" + NUM + r"\s*[–-]\s*" + NUM, need)
    if m:
        a, b = _num(m.group(1)), _num(m.group(2))
        return {"kind": "CLOSE_IN_ZONE", "lo": min(a, b), "hi": max(a, b)}
    tt = str(card.get("trigger_text") or "")
    m = re.search(r"закриття\s+" + NUM + r"\s*[≥≤]\s*середини зони\s+" + NUM, tt)
    if m:
        return {"kind": "CLOSE_VS_ZONE_MID", "close": _num(m.group(1)), "mid": _num(m.group(2)), "above": long_}
    return None


def closed_m15(candles: List[Dict[str, Any]], as_of: float) -> List[Dict[str, Any]]:
    return [c for c in candles if c["ts"] + M15 <= as_of]


def first_confirm_ts(card: Dict[str, Any], trig: Dict[str, Any], m15: List[Dict[str, Any]]) -> Optional[float]:
    """Закриття (кінець бару) першої ЗАКРИТОЇ M15-свічки після появи картки, що виконала заявлений тригер. Для CLOSE_VS_ZONE_MID тригер уже виконано в момент створення."""
    t0 = float(card["created_ts"])
    if trig["kind"] == "CLOSE_VS_ZONE_MID":
        return t0
    for c in sorted(m15, key=lambda x: x["ts"]):
        if c["ts"] < t0:                       # бар, що відкрився до появи картки, не рахуємо: його закриття вже міг бути враховано при створенні
            continue
        close_ts = c["ts"] + M15
        if trig["kind"] == "CLOSE_BEYOND":
            if (c["close"] > trig["level"]) if trig["above"] else (c["close"] < trig["level"]):
                return close_ts
        elif trig["kind"] == "CLOSE_IN_ZONE":
            if trig["lo"] <= c["close"] <= trig["hi"]:
                return close_ts
    return None


def audit_card(card: Dict[str, Any], m15: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Факти по одній картці. fill_before_confirm=True — paper-вхід відбувся до того, як заявлений тригер виконався на закритій M15-свічці (або тригер так і не виконався)."""
    trig = trigger_of(card)
    out: Dict[str, Any] = {"card_id": card["card_id"], "symbol": card["symbol"], "trigger": trig, "fill_ts": card.get("entry_ts")}
    if not trig:
        out["verdict"] = "ТРИГЕР_НЕ_РОЗПІЗНАНО"
        return out
    if trig["kind"] != "CLOSE_VS_ZONE_MID" and not m15:
        out["verdict"] = "НЕМАЄ_СВІЧОК"           # без реальних свічок «тригер не виконано» не стверджуємо
        return out
    ct = first_confirm_ts(card, trig, m15)
    out["confirm_close_ts"] = ct
    ft = card.get("entry_ts")
    if ft is None:
        out["verdict"] = "ВХОДУ_НЕ_БУЛО"
    elif trig["kind"] == "CLOSE_VS_ZONE_MID":
        close_px = trig["close"]
        out["entry_vs_confirm_close_pct"] = round((close_px - float(card["entry"])) / float(card["entry"]) * 100.0, 3)
        out["verdict"] = "ТРИГЕР_ПРИ_СТВОРЕННІ_ВХІД_ЛІМІТОМ_НИЖЧЕ_ЗА_ЦІНУ_ТРИГЕРА" if (trig["above"] and card["entry"] < close_px) or ((not trig["above"]) and card["entry"] > close_px) else "ТРИГЕР_ПРИ_СТВОРЕННІ"
    elif ct is None or float(ft) < ct:
        out["verdict"] = "ВХІД_ДО_ТРИГЕРА" if ct is not None else "ВХІД_БЕЗ_ВИКОНАНОГО_ТРИГЕРА"
        out["minutes_fill_before_confirm"] = None if ct is None else round((ct - float(ft)) / 60.0, 1)
    else:
        out["verdict"] = "ВХІД_ПІСЛЯ_ТРИГЕРА"
    return out


def confirmed_variant(card: Dict[str, Any], m15: List[Dict[str, Any]], now: float) -> Optional[Dict[str, Any]]:
    """Контрфактичний paper: той самий вхід/SL/цілі, але вхід дозволено лише ПІСЛЯ закриття тригерної M15-свічки. Не підміняє фактичний результат картки (лише порівняння)."""
    from office2 import radar_watch as RW

    trig = trigger_of(card)
    if not trig or trig["kind"] == "CLOSE_VS_ZONE_MID" or not m15:
        return None
    ct = first_confirm_ts(card, trig, closed_m15(m15, now))
    if ct is None:
        return {"status": "NO_CONFIRM", "r_net": None}
    c2 = dict(card, sent_ts=ct - 1.0, created_ts=min(float(card["created_ts"]), ct - 1.0))
    ev = RW.evaluate_card(c2, closed_m15(m15, now), now)
    return {"status": ev["paper_status"], "r_net": ev["r_net"], "entry_ts": ev["entry_ts"], "confirm_close_ts": ct}

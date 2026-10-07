"""Узгодженість ринкових фактів з напрямом сигналу: кожен фактор явно ЗА / ПРОТИ / НЕЙТРАЛЬНО. Лише опис для навчання, жодного впливу на рішення READY.
Суперечності (наприклад, sweep підтримує SHORT, а монета сильніша за BTC) накопичуються для пакетного аналізу."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

RS_EPS = 0.10     # п.п.: менше — нейтрально
BTC_EPS = 0.10    # % за годину


def _n(x: Optional[float], d: int = 2) -> str:
    return "—" if x is None else (("+" if x >= 0 else "−") + f"{abs(x):.{d}f}".replace(".", ","))


def _verdict(sign: int, direction: str) -> str:
    """sign>0 — факт говорить «вгору», <0 — «вниз», 0 — нейтрально."""
    if sign == 0:
        return "НЕЙТРАЛЬНО"
    up = direction == "LONG"
    return "ЗА " + direction if (sign > 0) == up else "ПРОТИ " + direction


def alignment(direction: str, market: Dict[str, Any], rel: Dict[str, Any], htf: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    d = "LONG" if str(direction).upper() != "SHORT" else "SHORT"
    out: List[Dict[str, Any]] = []
    rs = rel.get("rs_vs_btc_1h")
    if rs is not None:
        s = 1 if rs > RS_EPS else -1 if rs < -RS_EPS else 0
        v = _verdict(s, d)
        word = "сильніша за BTC" if rs > 0 else "слабша за BTC"
        out.append({"factor": "відносна сила vs BTC (1г)", "value": rs, "verdict": v, "text": f"відносна сила: {v} (монета {word} на {_n(rs)} п.п.)"})
    b = market.get("btc_ret_1h")
    if b is not None:
        s = 1 if b > BTC_EPS else -1 if b < -BTC_EPS else 0
        v = _verdict(s, d)
        out.append({"factor": "BTC за годину", "value": b, "verdict": v, "text": f"BTC {_n(b)}% / 1г: {v}"})
    br = market.get("breadth_up_4h")
    if br is not None:
        s = 1 if br > 0.6 else -1 if br < 0.4 else 0
        v = _verdict(s, d)
        out.append({"factor": "breadth альтів 4г", "value": br, "verdict": v, "text": f"{round(br * 100)}% альтів вгору за 4 год: {v}"})
    for tf in ("H4", "D1"):
        row = (htf or {}).get(tf) or {}
        tr = row.get("trend_eff", row.get("trend"))   # актуальний стан (з урахуванням зламу swing ціною зараз), не лише базовий тренд
        if tr is not None:
            v = _verdict(int(tr), d)
            out.append({"factor": f"тренд {tf}", "value": tr, "verdict": v, "text": f"тренд {tf} ({'вгору' if tr > 0 else 'вниз' if tr < 0 else 'діапазон'}): {v}"})
    return out


def summary(items: List[Dict[str, Any]]) -> Dict[str, int]:
    return {"for": sum(1 for i in items if i["verdict"].startswith("ЗА")), "against": sum(1 for i in items if i["verdict"].startswith("ПРОТИ")), "neutral": sum(1 for i in items if i["verdict"] == "НЕЙТРАЛЬНО")}

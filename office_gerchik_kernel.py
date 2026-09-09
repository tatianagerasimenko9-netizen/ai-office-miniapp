"""
Операційне ядро Герчика для промптів і фільтрів офісу.

Шар А — правила з книги. Шар Б — бали 0–10 для AI (не winrate).
Не вигадує статистику; якщо даних немає — score = None.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

# Компактний блок у system-промпт (не 25 файлів цілком).
GERCHIK_KERNEL = """
ЯДРО ГЕРЧИКА (застосовуй на КОЖНОМУ сетапі; цифри з радара, не з голови):
1) Рівень D1/сесійний/PDH-PDL. Плаваючий і середина діапазону — не вхід.
2) Одна модель: відбій (підтверджуючі бари, не поджатие) / пробій (малі бари + імпульс) / хибний пробій (немає імпульсу + повернення).
3) ATR: якщо day_used ≥75–80% — не по тренду (контртренд/ЛП або ПРОПУСК), крім локального екстремуму «в порожнечі».
4) Технічний стоп ЗА структуру (крипта — технічний, не рухати проти позиції). Тейк за Герчиком ≥3R; якщо RR < 3 — не називай сетапом Герчика.
5) Крипта: спочатку BTC; альт — чи живе своїм життям; лімітки; заявки заздалегідь.
6) XAUUSD: 24h, overnight-ризик; ті самі рівні/ATR/ЛП.
7) Бал ops (шар Б, не книга): D1/рівень +2, ЛП/sweep +3, ATR<70% +2, імпульс/BOS +1, обсяг +1, M15 +1.
   0–4 ПРОПУСК; 5–7 середній; 8–10 сильний. Не змішувати з edge_score 0–100.
Дерево: немає рівня → далі; бак порожній → не по тренду; немає моделі → чекати; RR<3 або стоп у повітрі → вето.
"""


def interpret_gerchik_ops(score: int) -> str:
    if score <= 4:
        return "skip"
    if score <= 7:
        return "medium"
    return "strong"


def gerchik_ops_from_facts(
    *,
    day_used_pct: Optional[float],
    near_level: bool,
    sweep_or_false_break: bool,
    impulse_bos: bool,
    volume_spike: bool = False,
    m15_confirm: bool = False,
    atr_unknown: bool = False,
) -> Dict[str, Any]:
    """Чистий рахунок шару Б. Без мережі."""
    if atr_unknown and not near_level and not sweep_or_false_break and not impulse_bos:
        return {
            "gerchik_ops_score": None,
            "gerchik_ops_band": "unknown",
            "gerchik_atr_trend_veto": False,
            "gerchik_ops_reasons": ["даних недостатньо"],
        }
    score = 0
    reasons = []
    if near_level:
        score += 2
        reasons.append("рівень D1/сесія/PDH-PDL +2")
    if sweep_or_false_break:
        score += 3
        reasons.append("sweep/ЛП +3")
    used = float(day_used_pct) if day_used_pct is not None else None
    atr_trend_veto = bool(used is not None and used >= 80.0)
    if used is not None and used < 70.0:
        score += 2
        reasons.append("ATR used <70% +2")
    elif used is not None:
        reasons.append(f"ATR used {used:.0f}% (без +2)")
    if impulse_bos:
        score += 1
        reasons.append("імпульс/BOS +1")
    if volume_spike:
        score += 1
        reasons.append("обсяг +1")
    if m15_confirm:
        score += 1
        reasons.append("M15 +1")
    score = max(0, min(10, score))
    band = interpret_gerchik_ops(score)
    if atr_trend_veto:
        reasons.append("ATR≥80% — не по тренду за Герчиком")
    return {
        "gerchik_ops_score": score,
        "gerchik_ops_band": band,
        "gerchik_atr_trend_veto": atr_trend_veto,
        "gerchik_ops_reasons": reasons,
    }


def compute_gerchik_ops(symbol: str) -> Dict[str, Any]:
    """Живі дані радара. Порожня відповідь API → unknown, без вигаданих балів."""
    try:
        from office_market_data import (
            _near_session_or_pdh_pdl,
            fetch_atr_context,
            fetch_candles,
            fetch_liquidity_sweep,
            fetch_market_structure,
            fetch_pd_array,
            fetch_session_levels,
        )
    except Exception:
        return gerchik_ops_from_facts(
            day_used_pct=None,
            near_level=False,
            sweep_or_false_break=False,
            impulse_bos=False,
            atr_unknown=True,
        )

    sym = str(symbol or "").upper().strip()
    atr_d = fetch_atr_context(sym) if sym else {}
    atr_d = atr_d if isinstance(atr_d, dict) else {}
    used = atr_d.get("day_used_pct")
    try:
        used_f = float(used) if used is not None else None
    except (TypeError, ValueError):
        used_f = None

    session_d = fetch_session_levels(sym) if sym else {}
    session_d = session_d if isinstance(session_d, dict) else {}
    pd_d = fetch_pd_array(sym, "4h") if sym else {}
    pd_d = pd_d if isinstance(pd_d, dict) else {}
    try:
        price = float(pd_d.get("current_price") or 0.0)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        c1h = fetch_candles(sym, "1h", 1) if sym else []
        if isinstance(c1h, list) and c1h and isinstance(c1h[-1], dict):
            try:
                price = float(c1h[-1].get("close") or 0.0)
            except (TypeError, ValueError):
                price = 0.0

    near = bool(price > 0 and _near_session_or_pdh_pdl(price, session_d))
    sweep_d = fetch_liquidity_sweep(sym, "1h") if sym else {}
    sweep_d = sweep_d if isinstance(sweep_d, dict) else {}
    sweep_or_fb = bool(sweep_d.get("bsl_sweep") or sweep_d.get("ssl_sweep"))
    structure_d = fetch_market_structure(sym, "1h") if sym else {}
    structure_d = structure_d if isinstance(structure_d, dict) else {}
    ev = str(structure_d.get("event") or "")
    impulse = ev in ("BOS_BULLISH", "BOS_BEARISH")

    volume_spike = False
    m15_confirm = False
    c15 = fetch_candles(sym, "15m", 8) if sym else []
    if isinstance(c15, list) and len(c15) >= 5:
        try:
            vols = [float((c or {}).get("volume") or 0.0) for c in c15[:-1]]
            last_v = float((c15[-1] or {}).get("volume") or 0.0)
            avg = (sum(vols) / len(vols)) if vols else 0.0
            volume_spike = bool(avg > 0 and last_v > avg * 1.5)
            last = c15[-1] or {}
            cl = float(last.get("close") or 0.0)
            op = float(last.get("open") or 0.0)
            if near and cl > 0 and op > 0:
                m15_confirm = (cl > op) or (cl < op)
        except (TypeError, ValueError):
            pass

    atr_unknown = used_f is None and not atr_d
    return gerchik_ops_from_facts(
        day_used_pct=used_f,
        near_level=near,
        sweep_or_false_break=sweep_or_fb,
        impulse_bos=impulse,
        volume_spike=volume_spike,
        m15_confirm=m15_confirm,
        atr_unknown=atr_unknown and not near and not sweep_or_fb and not impulse,
    )

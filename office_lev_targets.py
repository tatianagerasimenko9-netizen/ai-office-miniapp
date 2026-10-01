"""Цілі Лева ЗІ СТРУКТУРИ, а не з формули «1,5R».

Раніше TP1 будували рівно на 1,5R до комісій, а фінальний гейт після комісій (0,10%) відхиляв такий план — READY був неможливий.
Тепер: збираємо реальні рівні попереду входу (свінги H1/H4, зони рівнів з ≥2 торканнями, PDH/PWH, межі азійської сесії),
перебираємо їх від найближчого і беремо перший, для якого план проходить ЄДИНИЙ гейт RR (`office_alert_gate.rr_gate`) після комісій:
  · є реальний наступний рівень (TP2) → зважене правило: 40% TP1 + 60% TP2 ≥ 1,5 І RR до TP1 ≥ 1,0;
  · TP2 немає → RR до TP1 після комісій ≥ 1,5.
Реального рівня з потрібним RR немає → сценарій відхилено (цілі не вигадуємо і не «підтягуємо»). Поріг 1,5 не змінюється."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import office_alert_gate as _gate

MAX_ATR_D1 = 3.0        # ціль не далі за 3×ATR(D1) від входу (як у office_targets)
MERGE_PCT = 0.15        # рівні ближче за 0,15% ціни — один рівень
TP2_GAP_FRAC = 0.25     # TP2 далі за TP1 щонайменше на чверть відстані до TP1 (як у office_targets)


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


def _swing_levels(candles: Any, side_long: bool, tag: str) -> List[Tuple[float, str]]:
    import office_levels as ol

    rows = ol._rows(candles)[-200:]
    want = "H" if side_long else "L"
    return [(float(s["p"]), tag) for s in ol._swings(rows) if s["t"] == want]


def collect_levels(*, direction: str, candles_m15: Any = None, candles_h1: Any = None, candles_h4: Any = None,
                   candles_d1: Any = None, candles_w: Any = None) -> Tuple[List[Tuple[float, str]], Optional[float]]:
    """[(ціна, походження)] усіх реальних рівнів у бік цілі + ATR(D1). Не відфільтровані за входом."""
    import office_levels as ol
    import office_targets as ot

    long_ = str(direction or "").upper() != "SHORT"
    out: List[Tuple[float, str]] = []
    try:
        out += _swing_levels(candles_h1, long_, "свінг H1")
        out += _swing_levels(candles_h4, long_, "свінг H4")
    except Exception:  # noqa: BLE001
        pass
    try:
        for z in ol.zones(candles_h1):
            out.append((float(z["lo"] if long_ else z["hi"]), "зона рівня"))
    except Exception:  # noqa: BLE001
        pass
    atr_d1 = None
    try:
        pl = ol.previous_levels(candles_d1, candles_w)
        out += [(pl["PDH" if long_ else "PDL"], "рівень попереднього дня"), (pl["PWH" if long_ else "PWL"], "рівень попереднього тижня")]
        lv = ot.levels(m15=candles_m15, daily=candles_d1, weekly=candles_w)
        out.append((lv.get("asia_high" if long_ else "asia_low"), "межа азійської сесії"))
        atr_d1 = _f(lv.get("atr_d1"))
    except Exception:  # noqa: BLE001
        pass
    return [(float(p), w) for p, w in out if _f(p) is not None], atr_d1


def _ahead(levels: Sequence[Tuple[float, str]], long_: bool, entry: float, reach: Optional[float]) -> List[Tuple[float, str]]:
    sign = 1.0 if long_ else -1.0
    pts = sorted(((p, w) for p, w in levels if sign * (p - entry) > 0 and (reach is None or sign * (p - entry) <= reach)),
                 key=lambda x: sign * x[0])
    merged: List[Tuple[float, str]] = []
    for p, w in pts:
        if merged and abs(p - merged[-1][0]) / entry * 100.0 < MERGE_PCT:
            continue
        merged.append((p, w))
    return merged


def pick_targets(*, direction: str, entry: Any, sl: Any, levels: Optional[Sequence[Tuple[float, str]]] = None,
                 atr_d1: Optional[float] = None, min_tp1_pct: float = 0.0, **candles: Any) -> Dict[str, Any]:
    """{'ok', 'tp1','tp2','why1','why2','rr','rr_net','rr_weighted','reason','n_levels'}. levels — явні рівні (тести/replay) замість свічок."""
    e, s = _f(entry), _f(sl)
    res: Dict[str, Any] = {"ok": False, "tp1": None, "tp2": None, "why1": "", "why2": "", "rr": None, "rr_net": None,
                           "rr_weighted": None, "reason": "", "n_levels": 0}
    if e is None or s is None or e <= 0 or abs(e - s) <= 0:
        res["reason"] = "немає входу або стопа — цілі не рахую"
        return res
    long_ = str(direction or "").upper() != "SHORT"
    if levels is None:
        levels, atr_d1 = collect_levels(direction=direction, **candles)
    reach = MAX_ATR_D1 * atr_d1 if atr_d1 else None
    ahead = _ahead(levels, long_, e, reach)
    res["n_levels"] = len(ahead)
    if not ahead:
        res["reason"] = "попереду немає реальних структурних рівнів для цілі (свінги, зони, PDH/PWH, Азія) — ціль не вигадую"
        return res
    sign = 1.0 if long_ else -1.0
    last_reason = ""
    for i, (p1, w1) in enumerate(ahead):
        if abs(p1 - e) / e * 100.0 + 1e-9 < float(min_tp1_pct or 0.0):   # чинний мінімум простору до TP1 (1,2% мажори / 3% альти) не знижуємо
            last_reason = f"найближчі рівні ближче за мінімум простору до цілі 1 ({float(min_tp1_pct):g}%)"
            continue
        g1 = _gate.rr_gate(e, s, p1, None)
        tp2, w2 = None, ""
        for p2, ww in ahead[i + 1:]:
            if sign * (p2 - p1) >= abs(p1 - e) * TP2_GAP_FRAC:
                tp2, w2 = p2, ww
                break
        g = _gate.rr_gate(e, s, p1, tp2) if tp2 is not None else g1
        if not g["ok"] and tp2 is not None and g1["ok"]:
            g, tp2, w2 = g1, None, ""
        last_reason = str(g.get("reason") or "")
        if g["ok"]:
            governing = g["rr_weighted"] if g["rule"] == "weighted" else g["rr_net"]
            res.update(ok=True, tp1=p1, tp2=tp2, why1=w1, why2=w2, rr=governing, rr_net=g["rr_net"], rr_weighted=g["rr_weighted"],
                       reason="", skipped_nearer=i)
            return res
    res["reason"] = ("жоден реальний структурний рівень не дає RR після комісій за правилом — сценарій відхилено. " + last_reason).strip()
    return res

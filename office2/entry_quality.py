"""Якість входу і стопа на replay: чи був вхід передчасним, чи ціна після SL усе ж дійшла до початкового TP1, чим пояснюються стопи, що дають альтернативи.
Лише ВИМІР на закритих барах (нічого не змінює в Brain). Усі правила класифікації та альтернативи задано до перегляду результатів:
  • рекавері: після SL ціна торкається початкового TP1 за 24 год (96 M15-барів) / 72 год (288);
  • «глибше»: до SL ціна торкалась дальнього краю зони входу;
  • причини SL (пріоритет зверху вниз):
      PREMATURE_ENTRY      — TP1 пізніше досягнуто ≤72 год І до SL ціна заходила до дальнього краю зони (напрям вгадано, вхід раніше кращої ціни);
      STOP_WICK            — TP1 пізніше досягнуто ≤72 год, а зона не була пройдена (напрям вгадано; інвалідація/люфт вибито тінню);
      WRONG_DIRECTION      — TP1 не досягнуто ≤72 год І ціна пішла ≥1R за SL проти угоди;
      NO_FOLLOWTHROUGH     — TP1 не досягнуто ≤72 год, але й ≥1R за SL ціна не пішла;
  • альтернативи (TP1 той самий): E2 — лімітний вхід на дальньому краї зони (вікно 8 барів, як T3); SG — SL = екстремум − 20% розрахункового стопа (Герчик: люфт ≈20% стопа,
    екстремум ≈ SL варіанта v2); SA — SL = екстремум − 1×ATR(M15). Пропущений вхід = 0R."""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import numpy as np

from office2.smc import replay as RP

REC_24H, REC_72H = 96, 288
LIMIT_BARS = 8
FEE_RT_PCT = RP.DEFAULT_FEE_RT_PCT
SLIP_BPS = RP.DEFAULT_SLIPPAGE_RT_BPS


def _sim(m15, i, d, entry, sl, tp):
    risk = abs(entry - sl)
    if risk <= 0 or abs(tp - entry) <= 0 or (d == "LONG" and not (sl < entry < tp)) or (d == "SHORT" and not (tp < entry < sl)):
        return {"o": "NO_DATA", "r": None}
    s = RP.simulate(m15, i, d, entry, sl, tp, abs(tp - entry) / risk, risk / entry * 100.0, fee_rt_pct=FEE_RT_PCT, slippage_rt_bps=SLIP_BPS)
    return {"o": s["outcome"], "r": s["r_net"], "k": s.get("bars")}


def _limit(m15, i, d, price, sl, tp):
    sg = 1.0 if d == "LONG" else -1.0
    n = len(m15["t"])
    for j in range(i + 1, min(n, i + 1 + LIMIT_BARS)):
        touched = (m15["l"][j] <= price) if sg > 0 else (m15["h"][j] >= price)
        sl_hit = (m15["l"][j] <= sl) if sg > 0 else (m15["h"][j] >= sl)
        tp_hit = (m15["h"][j] >= tp) if sg > 0 else (m15["l"][j] <= tp)
        if (sl_hit or tp_hit) and not touched:
            return {"o": "MISSED", "r": None}
        if touched:
            return _sim(m15, j - 1, d, price, sl, tp)
    return {"o": "MISSED", "r": None}


def analyze(m15, i: int, ev: Mapping[str, Any], atr: float) -> Optional[Dict[str, Any]]:
    d, entry, sl, tp = ev["dir"], float(ev["entry"]), float(ev["sl"]), float(ev["tp1"])
    sg = 1.0 if d == "LONG" else -1.0
    n = len(m15["t"])
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    base = _sim(m15, i, d, entry, sl, tp)
    q: Dict[str, Any] = {"o": base["o"], "r": base["r"]}
    z = ev.get("zone")
    far = None
    if z and len(z) == 2:
        far = float(min(z)) if sg > 0 else float(max(z))
    j_sl = None
    if base["o"] == "SL":
        j_sl = i + int(base["k"] or 1)
        q["ts_sl"] = float(m15["t"][min(j_sl, n - 1)])
        # глибше в зону до SL
        if far is not None and j_sl > i:
            lo = m15["l"][i + 1:j_sl + 1] if sg > 0 else m15["h"][i + 1:j_sl + 1]
            q["deeper"] = bool((lo <= far).any() if sg > 0 else (lo >= far).any())
        else:
            q["deeper"] = False
        # рекавері після SL
        rest_h, rest_l = m15["h"][j_sl + 1:j_sl + 1 + REC_72H], m15["l"][j_sl + 1:j_sl + 1 + REC_72H]
        if len(rest_h) >= 8:
            hit = (rest_h >= tp) if sg > 0 else (rest_l <= tp)
            kt = int(np.argmax(hit)) if hit.any() else -1
            upto = rest_l[:kt + 1] if kt >= 0 else rest_l
            uptoh = rest_h[:kt + 1] if kt >= 0 else rest_h
            ext = float(((sl - upto.min()) if sg > 0 else (uptoh.max() - sl)) / risk)
            q.update(tp1_24h=bool(kt >= 0 and kt < REC_24H), tp1_72h=bool(kt >= 0), k_tp1=(kt + 1 if kt >= 0 else None), ext_r=round(max(ext, 0.0), 2), rec_n=int(len(rest_h)))
            if kt >= 0:
                q["cls"] = "PREMATURE_ENTRY" if q["deeper"] else "STOP_WICK"
            else:
                q["cls"] = "WRONG_DIRECTION" if ext >= 1.0 else "NO_FOLLOWTHROUGH"
        else:
            q["cls"] = "NO_DATA"
    # альтернативи на тих самих подіях
    alt: Dict[str, Any] = {}
    if far is not None and ((sg > 0 and far < entry) or (sg < 0 and far > entry)):
        alt["E2"] = _limit(m15, i, d, far, sl, tp)
    ext_px = ev.get("sl_v2")
    if ext_px is not None:
        e = float(ext_px)
        stop = abs(entry - e)
        if stop > 0 and ((sg > 0 and e < entry) or (sg < 0 and e > entry)):
            alt["SG"] = _sim(m15, i, d, entry, e - sg * 0.2 * stop, tp)
            if atr and atr > 0:
                alt["SA"] = _sim(m15, i, d, entry, e - sg * float(atr), tp)
    q["alt"] = {k: {"o": v["o"], "r": v["r"]} for k, v in alt.items()}
    return q

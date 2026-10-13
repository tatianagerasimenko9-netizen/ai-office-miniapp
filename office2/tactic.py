"""Тактики входу відносно першої перешкоди: формальні варіанти плану на ТИХ САМИХ READY-подіях (replay) і правила вибору, що перевіряються на даних.

Принцип: перешкода до TP1 (< 1R) НЕ блокує сигнал автоматично. Для кожної події визначено наперед (до побачених результатів) п'ять варіантів дії:
  T0  ВХІД ЗАРАЗ        — план як є (вхід за ціною READY, SL, TP1).
  T1  СКАЛЬП ДО ПЕРЕШКОДИ — ціль = перша перешкода до TP1 (вхід і SL ті самі).
  T2  ЧЕКАТИ ПРОБОЮ     — вхід лише після закриття M15 за перешкодою (до WAIT_BREAK_BARS барів; SL раніше → пропуск), SL і TP1 ті самі.
  T3  КРАЩА ЦІНА        — лімітний вхід у середині зони входу (лише якщо вона вигідніша за ціну READY; fill ≤ LIMIT_BARS барів), SL і TP1 ті самі. ГІПОТЕЗА.
  T4  КОРОТШИЙ СТРУКТУРНИЙ SL — SL варіанта «Стоп 2 · за структурою» з тези, якщо він ближче до входу й з правильного боку (інакше як T0).
  T5  ВІДМОВА           — 0R (лише як контрафакт для оцінки жорсткого фільтра).
Пороги не вигадуються: 1R — природна одиниця ризику; WAIT_BREAK_BARS/LIMIT_BARS — горизонти очікування, зафіксовані наперед (ГІПОТЕЗА, не з джерел).
Вибір тактики для бойового режиму робить ТАБЛИЦЯ, навчена на частині періодів і перевірена на решті (scripts/replay_tactics_study.py); поки перевага не доведена — тактика лише рекомендація.
Контролі: C1 — той самий вхід, протилежний напрям із дзеркальними SL/TP; C2 — простий імпульсний контроль (напрям останніх 4 барів, SL=TP=1 ATR15)."""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

import numpy as np

from office2.smc import core as K
from office2.smc import replay as RP

WAIT_BREAK_BARS = 8
LIMIT_BARS = 8
FEE_RT_PCT = RP.DEFAULT_FEE_RT_PCT
SLIP_BPS = RP.DEFAULT_SLIPPAGE_RT_BPS
TACTICS = ["T0_enter_now", "T1_scalp_to_obstacle", "T2_wait_break", "T3_limit_zone_mid", "T4_tight_structural_sl"]
BUCKETS = ["NO_OBSTACLE", "OBST_LT_0.5R", "OBST_0.5_1R", "OBST_GE_1R"]
BUCKET_EDGES = (0.5, 1.0)       # 1R — одиниця ризику; 0.5R — половина одиниці (описові корзини, не пороги фільтра)


def bucket(ev: Mapping[str, Any]) -> str:
    ob = ev.get("obst") or []
    if not ob:
        return "NO_OBSTACLE"
    r = ob[0].get("r")
    if r is None:
        return "NO_OBSTACLE"
    return "OBST_LT_0.5R" if r < BUCKET_EDGES[0] else "OBST_0.5_1R" if r < BUCKET_EDGES[1] else "OBST_GE_1R"


def _compact(s: Dict[str, Any]) -> Dict[str, Any]:
    return {"outcome": s["outcome"], "r_net": s["r_net"], "bars": s.get("bars")}


def _run(m15, i, d, entry, sl, tp, delay_bars_from=None):
    risk = abs(entry - sl)
    if risk <= 0 or abs(tp - entry) <= 0 or (d == "LONG" and not (sl < entry < tp)) or (d == "SHORT" and not (tp < entry < sl)):
        return {"outcome": "NO_DATA", "r_net": None, "bars": 0}
    return _compact(RP.simulate(m15, i, d, entry, sl, tp, abs(tp - entry) / risk, risk / entry * 100.0, fee_rt_pct=FEE_RT_PCT, slippage_rt_bps=SLIP_BPS))


def t0(m15, i, ev):
    return _run(m15, i, ev["dir"], ev["entry"], ev["sl"], ev["tp1"])


def t1_scalp(m15, i, ev):
    ob = ev.get("obst") or []
    if not ob:
        return t0(m15, i, ev)
    return _run(m15, i, ev["dir"], ev["entry"], ev["sl"], float(ob[0]["p"]))


def t2_wait_break(m15, i, ev):
    ob = ev.get("obst") or []
    if not ob:
        return t0(m15, i, ev)
    sg = 1.0 if ev["dir"] == "LONG" else -1.0
    lvl = float(ob[0]["p"])
    n = len(m15["t"])
    for j in range(i + 1, min(n - 1, i + 1 + WAIT_BREAK_BARS)):
        if (sg > 0 and m15["l"][j] <= ev["sl"]) or (sg < 0 and m15["h"][j] >= ev["sl"]):
            return {"outcome": "MISSED_SL_BEFORE_BREAK", "r_net": None, "bars": 0}
        c = float(m15["c"][j])
        if (sg > 0 and c > lvl) or (sg < 0 and c < lvl):
            if (sg > 0 and c >= ev["tp1"]) or (sg < 0 and c <= ev["tp1"]):
                return {"outcome": "MISSED_NO_ROOM", "r_net": None, "bars": 0}
            return _run(m15, j, ev["dir"], c, ev["sl"], ev["tp1"])
    return {"outcome": "MISSED_NO_BREAK", "r_net": None, "bars": 0}


def t3_limit_mid(m15, i, ev):
    z = ev.get("zone")
    if not z:
        return t0(m15, i, ev)
    mid = (float(z[0]) + float(z[1])) / 2.0
    sg = 1.0 if ev["dir"] == "LONG" else -1.0
    if (sg > 0 and not mid < ev["entry"]) or (sg < 0 and not mid > ev["entry"]):
        return t0(m15, i, ev)
    n = len(m15["t"])
    for j in range(i + 1, min(n, i + 1 + LIMIT_BARS)):
        touched = (m15["l"][j] <= mid) if sg > 0 else (m15["h"][j] >= mid)
        sl_hit = (m15["l"][j] <= ev["sl"]) if sg > 0 else (m15["h"][j] >= ev["sl"])
        tp_first = (m15["h"][j] >= ev["tp1"]) if sg > 0 else (m15["l"][j] <= ev["tp1"])
        if sl_hit and not touched:
            return {"outcome": "MISSED_SL_BEFORE_FILL", "r_net": None, "bars": 0}
        if tp_first and not touched:
            return {"outcome": "MISSED_TP_BEFORE_FILL", "r_net": None, "bars": 0}
        if touched:
            return _run(m15, j - 1, ev["dir"], mid, ev["sl"], ev["tp1"])
    return {"outcome": "MISSED_NO_FILL", "r_net": None, "bars": 0}


def t4_tight_sl(m15, i, ev):
    sl2 = ev.get("sl_v2")
    if sl2 is None:
        return t0(m15, i, ev)
    sg = 1.0 if ev["dir"] == "LONG" else -1.0
    ok = (sg > 0 and ev["sl"] < sl2 < ev["entry"]) or (sg < 0 and ev["entry"] < sl2 < ev["sl"])
    return _run(m15, i, ev["dir"], ev["entry"], float(sl2), ev["tp1"]) if ok else t0(m15, i, ev)


def c1_mirror(m15, i, ev):
    d = "SHORT" if ev["dir"] == "LONG" else "LONG"
    risk, gain = abs(ev["entry"] - ev["sl"]), abs(ev["tp1"] - ev["entry"])
    sg = 1.0 if d == "LONG" else -1.0
    return _run(m15, i, d, ev["entry"], ev["entry"] - sg * risk, ev["entry"] + sg * gain)


def c2_momentum(m15, i, ev, atr_arr):
    if i < 4:
        return {"outcome": "NO_DATA", "r_net": None, "bars": 0}
    a = K.atr_at(atr_arr, i)
    c = float(m15["c"][i])
    d = "LONG" if c >= float(m15["c"][i - 4]) else "SHORT"
    sg = 1.0 if d == "LONG" else -1.0
    return _run(m15, i, d, c, c - sg * a, c + sg * a)


def all_variants(m15, i, ev, atr_arr) -> Dict[str, Any]:
    return {"T0_enter_now": t0(m15, i, ev), "T1_scalp_to_obstacle": t1_scalp(m15, i, ev), "T2_wait_break": t2_wait_break(m15, i, ev),
            "T3_limit_zone_mid": t3_limit_mid(m15, i, ev), "T4_tight_structural_sl": t4_tight_sl(m15, i, ev),
            "C1_mirror_direction": c1_mirror(m15, i, ev), "C2_momentum_1atr": c2_momentum(m15, i, ev, atr_arr)}


# ---- рекомендація для живого READY (з тези; без перегляду майбутнього) -----------------------------------------------------------------------

def advise(th: Mapping[str, Any], table: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Тактична рекомендація до READY. table: {корзина → тактика} з replay-навчання; без таблиці або без доведеної переваги — T0 (план як є).
    Повертає розрахунки R для кожного варіанту з рівнів тези (арифметика, не прогноз)."""
    d = th.get("dir")
    entry, sl = th.get("entry"), th.get("sl")
    tg = th.get("targets") or []
    ob = th.get("obstacles_before_tp1") or []
    if None in (entry, sl) or not tg or d not in ("LONG", "SHORT"):
        return {"tactic": "T0_enter_now", "reason": "недостатньо рівнів", "table_used": False, "options": {}}
    risk = abs(entry - sl)
    sg = 1.0 if d == "LONG" else -1.0
    rr = lambda p, e=entry, r=risk: round(sg * (p - e) / r, 2) if r > 0 else None   # noqa: E731
    ev = {"obst": [{"p": o.get("p"), "r": o.get("r")} for o in ob], "zone": th.get("entry_zone") or th.get("zone"),
          "sl_v2": ((th.get("stops") or {}).get("v2") or {}).get("sl")}
    b = bucket(ev)
    opts: Dict[str, Any] = {"T0_enter_now": {"entry": entry, "sl": sl, "tp": tg[0].get("p"), "r_to_tp": rr(tg[0].get("p"))}}
    if ob:
        opts["T1_scalp_to_obstacle"] = {"entry": entry, "sl": sl, "tp": ob[0].get("p"), "r_to_tp": rr(ob[0].get("p")), "note": "вихід біля першої перешкоди"}
        opts["T2_wait_break"] = {"trigger": f"закриття M15 за {ob[0].get('p')}", "sl": sl, "tp": tg[0].get("p"), "note": f"чекати до {WAIT_BREAK_BARS} барів; вхід за ціною закриття; R рахується від неї"}
    z = ev["zone"]
    if z:
        mid = (float(z[0]) + float(z[1])) / 2.0
        if (sg > 0 and mid < entry) or (sg < 0 and mid > entry):
            opts["T3_limit_zone_mid"] = {"entry": round(mid, 8), "sl": sl, "tp": tg[0].get("p"), "r_to_tp": rr(tg[0].get("p"), mid, abs(mid - sl)), "note": "лімітний вхід, ГІПОТЕЗА"}
    v2 = ev["sl_v2"]
    if v2 is not None and ((sg > 0 and sl < v2 < entry) or (sg < 0 and entry < v2 < sl)):
        opts["T4_tight_structural_sl"] = {"entry": entry, "sl": v2, "tp": tg[0].get("p"), "r_to_tp": rr(tg[0].get("p"), entry, abs(entry - v2)), "note": "SL «за структурою» ближче до входу"}
    pick = (table or {}).get(b)
    if pick in opts:
        return {"tactic": pick, "bucket": b, "reason": f"таблиця replay для корзини {b}", "table_used": True, "options": opts}
    return {"tactic": "T0_enter_now", "bucket": b, "reason": "перевага альтернативних тактик на replay не доведена — план як є", "table_used": False, "options": opts}

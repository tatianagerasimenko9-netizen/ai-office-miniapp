"""Дослідження денного ліміту «3 стопи за добу UTC» на would-be READY, яких він відсік. ЛИШЕ дослідження: у LIVE нічого не змінює і не вмикає.

Дані: fixtures/learning/gate_{blocked,delivered,milestones}_2026-10.json (знімок production) + 1m-свічки Binance (data.binance.vision, Actions).
Правила виконання — ті самі, що в paper-контурі (office2/paper.py): вхід = open першої 1m-свічки після (потенційної) доставки; MISSED, якщо вхід недоступний; SL-first у спірній свічці;
витрати 0.15 % кола; ризик $10. Заблокованим кандидатам НЕ приписується фактична Telegram-доставка: умовна доставка = рішення + 60 с.
«Стоп» для лічильника ліміту = SCENARIO_MILESTONE «SL» (office2.engine.day_stops): ціна торкнулась оригінального SL до досягнення останньої цілі — навіть якщо раніше був TP1/TP2."""
from __future__ import annotations

import json
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from office2 import paper as P

ASSUMED_DELIVERY_SEC = 60
MAX_READY_PER_DAY = 8
DAY = 86400


def _day(ts: float) -> int:
    return int(ts // DAY)


def simulate_event(ev: Dict[str, Any], bars: List[Tuple[float, ...]], data_end: float) -> Dict[str, Any]:
    """Результат кандидата за paper-правилами. Повертає {entered, miss_reason, fill_ts, a_outcome, a_ts, pnl_a/b/c, r_a, sl_milestone_ts, tp1_ts, resolved}."""
    d = ev["dir"]
    tp = ev.get("tp") or []
    deliv = float(ev.get("delivered_ts") or (float(ev["decision_ts"]) + ASSUMED_DELIVERY_SEC))
    out: Dict[str, Any] = {"id": ev["id"], "entered": False, "miss_reason": None, "fill_ts": None, "a_outcome": None, "a_ts": None, "pnl_a": None, "pnl_b": None, "pnl_c": None, "r_a": None,
                           "sl_milestone_ts": None, "tp1_ts": None, "resolved": False}
    if not tp or not bars:
        out["miss_reason"] = "NO_DATA: немає цілей або свічок"
        return out
    fill = P.decide_fill(d, ev["entry"], ev["sl"], tp[0], deliv, bars)
    if not fill["ok"]:
        out["miss_reason"] = fill["reason"]
        return out
    out["entered"], out["fill_ts"] = True, fill["fill_ts"]
    w = P.walk(d, fill["fill_ts"], fill["fill_price"], ev["sl"], [tp[0], tp[1] if len(tp) > 1 else None, tp[2] if len(tp) > 2 else None], bars, data_end)
    pos = {"direction": d, "fill_price": fill["fill_price"], "sl": ev["sl"], "plan_entry": ev["entry"]}
    P._apply(pos, w, data_end)
    out.update(pnl_a=pos.get("pnl_a"), pnl_b=pos.get("pnl_b"), pnl_c=pos.get("pnl_c"), r_a=pos.get("r_a"), tp1_ts=w["tp_ts"].get("TP1"))
    a = w["closed"]["A"]
    if a["done"]:
        out["a_outcome"] = "SL" if a["why"] == "SL" else ("TP" if str(a["why"]).startswith("TP") else "EXP")
        out["a_ts"], out["resolved"] = a["ts"], True
    else:
        out["a_outcome"] = "OPEN"
    # SL-«milestone» (як у трекері Office2): оригінальний SL торкнуто до досягнення останньої цілі; рахується і після TP1/TP2
    last = tp[-1]
    long_ = d == "LONG"
    for t, o, h, l, c in bars:
        if t < fill["fill_ts"] or t + 60 > data_end:
            continue
        hit_sl = (l <= ev["sl"]) if long_ else (h >= ev["sl"])
        hit_last = (h >= last) if long_ else (l <= last)
        if hit_sl:
            out["sl_milestone_ts"] = t + 60
            break
        if hit_last:
            break
    return out


# ------------------------------------------------------------------ правила (дослідницькі)
class State:
    def __init__(self) -> None:
        self.admitted: List[Dict[str, Any]] = []

    def stops_today(self, now: float, only_a_loss: bool = False) -> int:
        n = 0
        for e in self.admitted:
            ts = e.get("sl_milestone_ts")
            if ts and ts <= now and _day(ts) == _day(now):
                if only_a_loss and e.get("tp1_ts") and e["tp1_ts"] < ts:
                    continue
                n += 1
        return n

    def net_r_today(self, now: float) -> float:
        return sum((e.get("r_a") or 0.0) for e in self.admitted if e.get("a_ts") and e["a_ts"] <= now and _day(e["a_ts"]) == _day(now))

    def admitted_today(self, now: float) -> int:
        return sum(1 for e in self.admitted if _day(e["decision_ts"]) == _day(now))

    def last_stop(self, now: float) -> Optional[float]:
        ts = [e["sl_milestone_ts"] for e in self.admitted if e.get("sl_milestone_ts") and e["sl_milestone_ts"] <= now]
        return max(ts) if ts else None


RISK_FLAGS = ("counter_trend", "m5_trigger_no", "pd_against", "retest_not_fresh")


def risk_flag_count(ev: Dict[str, Any]) -> int:
    f = ev.get("f") or {}
    n = sum(1 for k in RISK_FLAGS if f.get(k))
    if ev.get("weekend"):
        n += 1
    return n


def _cap(st: State, ev: Dict[str, Any]) -> bool:
    return st.admitted_today(ev["decision_ts"]) < MAX_READY_PER_DAY


RULES: Dict[str, Callable[[State, Dict[str, Any]], bool]] = {
    "R_gate3_replica": lambda st, ev: _cap(st, ev) and st.stops_today(ev["decision_ts"]) < 3,
    "R1_no_limit": lambda st, ev: _cap(st, ev),
    "R2_count_only_A_losses": lambda st, ev: _cap(st, ev) and st.stops_today(ev["decision_ts"], only_a_loss=True) < 3,
    "R3_lock_at_minus3R_net": lambda st, ev: _cap(st, ev) and st.net_r_today(ev["decision_ts"]) > -3.0,
    "R4_pause_2h_after_each_stop": lambda st, ev: _cap(st, ev) and not (st.last_stop(ev["decision_ts"]) and ev["decision_ts"] - st.last_stop(ev["decision_ts"]) < 2 * 3600),
    "R5_limit_5_stops": lambda st, ev: _cap(st, ev) and st.stops_today(ev["decision_ts"]) < 5,
    "R6_after_3_stops_pause_3h": lambda st, ev: _cap(st, ev) and not (st.stops_today(ev["decision_ts"]) >= 3 and st.last_stop(ev["decision_ts"]) and ev["decision_ts"] - st.last_stop(ev["decision_ts"]) < 3 * 3600),
    "R7_after_3_stops_only_clean": lambda st, ev: _cap(st, ev) and (st.stops_today(ev["decision_ts"]) < 3 or risk_flag_count(ev) <= 1),
}


def run_rule(name: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """events — хронологічно за decision_ts, кожна з полями симуляції (simulate_event) і source. Повертає метрики прийнятих подій."""
    admit = RULES[name]
    st = State()
    for ev in sorted(events, key=lambda e: e["decision_ts"]):
        if ev.get("tradable") is False:
            continue
        if admit(st, ev):
            st.admitted.append(ev)
    return metrics(st.admitted, name)


def metrics(evs: List[Dict[str, Any]], label: str = "") -> Dict[str, Any]:
    entered = [e for e in evs if e.get("entered")]
    res = [e for e in entered if e.get("a_outcome") in ("TP", "SL")]
    tp = [e for e in res if e["a_outcome"] == "TP"]
    sl = [e for e in res if e["a_outcome"] == "SL"]
    pa = [e["pnl_a"] for e in res if e.get("pnl_a") is not None]
    ra = [e["r_a"] for e in res if e.get("r_a") is not None]
    pb = [e["pnl_b"] for e in entered if e.get("pnl_b") is not None]
    pc = [e["pnl_c"] for e in entered if e.get("pnl_c") is not None]
    gain, loss = sum(x for x in pa if x > 0), -sum(x for x in pa if x < 0)
    eq, peak, dd = 0.0, 0.0, 0.0
    for e in sorted(res, key=lambda e: e["a_ts"]):
        eq += e["pnl_a"] or 0.0
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {"label": label, "admitted": len(evs), "entered": len(entered), "missed_entry": len(evs) - len(entered), "tp1_first": len(tp), "sl_first": len(sl),
            "unresolved": len(entered) - len(res), "pnl_a_usd": round(sum(pa), 2), "pnl_b_usd": round(sum(pb), 2), "pnl_c_usd": round(sum(pc), 2),
            "expectancy_r_a": round(sum(ra) / len(ra), 3) if ra else None, "win_rate_a": round(len(tp) / len(res), 3) if res else None,
            "profit_factor_a": round(gain / loss, 2) if loss > 0 else None, "max_drawdown_usd": round(dd, 2), "n_resolved": len(res)}


def bootstrap_mean_ci(xs: List[float], n: int = 2000, seed: int = 7) -> Optional[List[float]]:
    import random

    if len(xs) < 10:
        return None
    rnd = random.Random(seed)
    ms = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return [round(ms[int(0.025 * n)], 3), round(ms[int(0.975 * n)], 3)]


def flag_table(evs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Розріз по ознаках методик (Герчик/SMC/ICT/Вайкофф/PA/BTC-контекст) на ВСІХ події з розв'язаним A (і доставлені, і відсічені). Ознаки — не причини."""
    flags: Dict[str, Callable[[Dict[str, Any]], bool]] = {
        "PA: повторний тест, не свіжий sweep": lambda e: bool((e.get("f") or {}).get("retest_not_fresh")),
        "PA: свіжий sweep/raid": lambda e: not (e.get("f") or {}).get("retest_not_fresh"),
        "Герчик: є дзеркальний рівень": lambda e: bool((e.get("f") or {}).get("mirror_for")),
        "Герчик: рівень strength≥3": lambda e: (e.get("lvl_strength") or 0) and int(e["lvl_strength"]) >= 3,
        "Герчик: рівень strength=1": lambda e: str(e.get("lvl_strength")) == "1",
        "ICT: premium/discount проти": lambda e: bool((e.get("f") or {}).get("pd_against")),
        "SMC/HTF: проти старшої структури": lambda e: bool((e.get("f") or {}).get("counter_trend")),
        "M5-тригер не підтверджений": lambda e: bool((e.get("f") or {}).get("m5_trigger_no")),
        "Вайкофф: фаза визначена": lambda e: not (e.get("f") or {}).get("wyckoff_unknown"),
        "Булковскі: фігура за напрямом": lambda e: bool((e.get("f") or {}).get("bulkowski_for")),
        "Сесія: вихідні": lambda e: bool(e.get("weekend")),
        "Напрям LONG": lambda e: e["dir"] == "LONG",
        "Напрям SHORT": lambda e: e["dir"] == "SHORT",
        "≥2 ризик-ознак": lambda e: risk_flag_count(e) >= 2,
        "0–1 ризик-ознак": lambda e: risk_flag_count(e) <= 1,
    }
    res = [e for e in evs if e.get("entered") and e.get("a_outcome") in ("TP", "SL") and e.get("r_a") is not None]
    out: Dict[str, Any] = {}
    for name, fn in flags.items():
        sub = [e for e in res if fn(e)]
        if not sub:
            continue
        rs = [e["r_a"] for e in sub]
        out[name] = {"n": len(sub), "tp1_first": sum(1 for e in sub if e["a_outcome"] == "TP"), "sl_first": sum(1 for e in sub if e["a_outcome"] == "SL"),
                     "expectancy_r": round(sum(rs) / len(rs), 3), "pnl_usd": round(sum(e["pnl_a"] for e in sub), 2), "status": "INSUFFICIENT (n<30)" if len(sub) < 30 else "OK"}
    return out


def load_events(blocked_path: str, delivered_path: str) -> List[Dict[str, Any]]:
    blocked = json.load(open(blocked_path))["items"]
    deliv = json.load(open(delivered_path))["items"]
    out = []
    for b in blocked:
        out.append(dict(b, source="BLOCKED", tradable=True))
    for d in deliv:
        out.append(dict(d, source="DELIVERED" if d.get("status") == "DELIVERED" else "SUPPRESSED", tradable=d.get("status") == "DELIVERED"))
    return out


def gate_timeline(milestones: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """За реальними SL-milestone: коли лічильник вперше досяг 3 і коли ліміт закінчується (наступна UTC-доба 00:00)."""
    sl = sorted((float(r["sent"]), r["sid"]) for r in milestones if r["level"] == "SL")
    tp1 = {}
    for r in milestones:
        if r["level"] == "TP1":
            tp1.setdefault(r["sid"], float(r["sent"]))
    days: Dict[int, List[Tuple[float, str]]] = {}
    for ts, sid in sl:
        days.setdefault(_day(ts), []).append((ts, sid))
    out = []
    for d, lst in sorted(days.items()):
        third = lst[2] if len(lst) >= 3 else None
        out.append({"utc_day": d, "stops": len(lst), "after_tp1": sum(1 for ts, sid in lst if tp1.get(sid, 1e18) < ts), "limit_reached_at": third[0] if third else None,
                    "third_stop_signal": third[1] if third else None, "third_stop_after_tp1": bool(third and tp1.get(third[1], 1e18) < third[0]),
                    "lock_ends_at": (d + 1) * DAY if third else None})
    return out

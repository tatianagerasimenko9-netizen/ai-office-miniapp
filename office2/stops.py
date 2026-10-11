"""Три варіанти стопа для кожної навчальної ідеї (порівняння, не заміна): принцип — стоп стоїть там, де сценарій справді стає неправильним, а не на фіксованому %.

  Стоп 1 «поточний»        — те, що рахує Brain: екстремум події (sweep/початок руху) ± доказовий люфт (медіана проколів цього рівня).
  Стоп 2 «за структурою»   — просто за екстремумом події, мінімальний запас (0,02 % ціни): тугіше, ризик менший.
  Стоп 3 «структура + ATR» — за екстремумом із запасом 12,5 % ATR(M15) (середина гіпотези 10–15 % ATR з матеріалів власниці; перевіряється, а не приймається).

«Обґрунтований» = стоп за екстремумом події, ризик у допустимих межах, не менше за 1 ATR(M15) від входу (поза нормальним шумом) і НЕ стоїть біля очевидного
рівня/круглого числа (де збирається ліквідність). Фактичний результат навчальної угоди лишається за поточним стопом; варіанти оцінюються окремо (office2.radar_watch)."""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

ATR_MARGIN_PCT = 12.5          # гіпотеза «10–15 % ATR»; не обов'язкове правило
TICK_PCT = 0.02                # мінімальний запас «за екстремум», % ціни
LIQ_WINDOW_ATR = 0.20          # рівень/кругле число ближче за 0,2 ATR до стопа = «очевидне місце ліквідності»
MIN_STOP_ATR = 1.0
MIN_RISK_PCT, MAX_RISK_PCT = 0.15, 6.0
NAMES = {"v1": "Стоп 1 · поточний", "v2": "Стоп 2 · за структурою", "v3": "Стоп 3 · структура + запас ATR"}


def near_round(price: float, atr: float) -> Optional[float]:
    """Найближче «кругле» число (кратне половині степеня десяти), якщо воно в межах LIQ_WINDOW_ATR від ціни."""
    if price <= 0 or atr <= 0:
        return None
    step = 10 ** math.floor(math.log10(price)) / 2.0
    r = round(price / step) * step
    return r if abs(r - price) <= LIQ_WINDOW_ATR * atr else None


def liquidity_hint(direction: str, stop: float, atr: float, levels: List[Dict[str, Any]]) -> Optional[str]:
    """Чи стоїть стоп біля очевидного рівня (мінімум/максимум, сесійний, EQ) або кругле число з боку стопа."""
    if atr <= 0:
        return None
    side = "low" if direction == "LONG" else "high"
    for x in levels or []:
        if x.get("taken_ts") is not None or x.get("side") != side:
            continue
        if abs(float(x["p"]) - stop) <= LIQ_WINDOW_ATR * atr:
            return f"поруч рівень {x.get('kind')} {float(x['p']):.6g}"
    r = near_round(stop, atr)
    if r is not None:
        return f"поруч кругле число {r:.6g}"
    return None


def variants(direction: str, extreme: float, luft: float, atr: float, levels: List[Dict[str, Any]], entry: Optional[float] = None) -> Dict[str, Any]:
    """Варіанти стопа в реальних координатах. extreme — екстремум події (LONG: нижній, SHORT: верхній); luft ≥ 0 — доказовий люфт Brain; atr — ATR(M15)."""
    sg = 1.0 if direction == "LONG" else -1.0
    tick = max(abs(extreme) * TICK_PCT / 100.0, 1e-12)
    raw = {"v1": extreme - sg * max(luft, 0.0), "v2": extreme - sg * tick, "v3": extreme - sg * max(ATR_MARGIN_PCT / 100.0 * atr, tick)}
    out: Dict[str, Any] = {"extreme": extreme, "atr": atr, "margin_pct": ATR_MARGIN_PCT}
    for k, sl in raw.items():
        beyond = (sl <= extreme) if direction == "LONG" else (sl >= extreme)
        v: Dict[str, Any] = {"sl": sl, "name": NAMES[k], "beyond_extreme": bool(beyond), "liq": liquidity_hint(direction, sl, atr, levels)}
        if entry:
            risk = abs(entry - sl)
            rp = risk / entry * 100.0
            v.update(risk_pct=rp, risk_atr=(risk / atr if atr else None), noise_ok=bool(atr and risk / atr >= MIN_STOP_ATR), range_ok=bool(MIN_RISK_PCT <= rp <= MAX_RISK_PCT))
            v["justified"] = bool(beyond and v["noise_ok"] and v["range_ok"] and not v["liq"])
        out[k] = v
    return out


def finalize_for_entry(st: Dict[str, Any], direction: str, entry: float) -> Dict[str, Any]:
    """Дописує ризик/обґрунтованість під фактичний вхід картки (вхід міг зсунутись у зону)."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in st.items()}
    atr = float(st.get("atr") or 0.0)
    for k in ("v1", "v2", "v3"):
        v = out.get(k)
        if not v:
            continue
        side_ok = (v["sl"] < entry) if direction == "LONG" else (v["sl"] > entry)
        risk = abs(entry - v["sl"])
        rp = risk / entry * 100.0
        v.update(risk_pct=rp, risk_atr=(risk / atr if atr else None), noise_ok=bool(atr and risk / atr >= MIN_STOP_ATR), range_ok=bool(MIN_RISK_PCT <= rp <= MAX_RISK_PCT), side_ok=side_ok)
        v["justified"] = bool(side_ok and v.get("beyond_extreme") and v["noise_ok"] and v["range_ok"] and not v.get("liq"))
    just = [k for k in ("v3", "v1", "v2") if out.get(k, {}).get("justified")]
    out["recommended"] = just[0] if just else None
    return out


def explain_ua(st: Dict[str, Any]) -> List[str]:
    """Прості пояснення українською для кожного варіанта."""
    out = []
    for k in ("v1", "v2", "v3"):
        v = st.get(k)
        if not v:
            continue
        why = []
        why.append("за екстремумом події — там, де сценарій справді ламається" if v.get("beyond_extreme") else "ближче за екстремум події — сценарій ще не зламаний")
        if v.get("noise_ok") is False:
            why.append("занадто близько до входу: у межах звичайного шуму ціни")
        if v.get("range_ok") is False:
            why.append("ризик поза допустимими межами")
        if v.get("liq"):
            why.append(f"стоїть біля очевидного місця скупчення стопів ({v['liq']})")
        out.append(("Обґрунтований: " if v.get("justified") else "Сумнівний: ") + "; ".join(why))
    return out


def after_stop(direction: str, candles: List[Dict[str, Any]], stop_ts: float, entry: float, sl: float, tp1: float, extreme: Optional[float], horizon_bars: int = 16, bar: int = 900) -> Dict[str, Any]:
    """Що було з ціною ПІСЛЯ спрацювання стопа (до horizon_bars × 15 хв): ідея справді зламалась чи ціна повернулась у прогнозованому напрямку.
    STOP_HUNT — ціна повернулась до входу (і далі) без закриття за екстремумом події; BROKEN — закриття за екстремумом або рух проти ще ≥ 1 R; UNCLEAR — решта."""
    sg = 1.0 if direction == "LONG" else -1.0
    risk = abs(entry - sl)
    nxt = [c for c in candles if float(c["ts"]) >= stop_ts][:horizon_bars]
    if not nxt or risk <= 0:
        return {"verdict": "NO_DATA", "bars": len(nxt)}
    reclaimed = any((c["high"] >= entry) if sg > 0 else (c["low"] <= entry) for c in nxt)
    hit_tp1 = any((c["high"] >= tp1) if sg > 0 else (c["low"] <= tp1) for c in nxt)
    worst = min((c["low"] - sl) * sg if sg > 0 else (sl - c["high"]) for c in nxt)         # <0: пішла далі проти позиції
    mae_r = abs(min(worst, 0.0)) / risk
    closed_beyond = False
    if extreme is not None and "close" in nxt[0]:
        closed_beyond = any((c["close"] < extreme) if sg > 0 else (c["close"] > extreme) for c in nxt)
    if reclaimed and not closed_beyond:
        v = "STOP_HUNT"
    elif closed_beyond or mae_r >= 1.0:
        v = "BROKEN"
    else:
        v = "UNCLEAR"
    return {"verdict": v, "reclaimed_entry": bool(reclaimed), "reached_tp1_after": bool(hit_tp1), "further_against_r": round(mae_r, 2), "closed_beyond_extreme": bool(closed_beyond), "bars": len(nxt)}


VERDICT_UA = {"STOP_HUNT": "ціну вибило стопом, але вона повернулась у бік ідеї — стоп, імовірно, був занадто тугий",
              "BROKEN": "сценарій справді зламався — стоп спрацював правильно", "UNCLEAR": "після стопа ціна не дала чіткого висновку", "NO_DATA": "після стопа ще немає свічок для висновку"}

"""SHADOW-дослідження: вхід лише після реакції ціни в зоні (замість ліміту на межі зони). НЕ торгове правило, НЕ LIVE, нічого не пише в БД/Telegram.

Джерела Дарії (docs/sources/evidence.jsonl, D-NO-CONFIRMATION-NO-TRADE / D-FIB-REACTION-NOT-LIMITS / D-CANDLE-STRENGTH):
  кадри 225–226: сценарій хибного пробою — «ждём реакции, торгуем реакцію ціни»: повернення → реакція (підтверджувальна свічка / поглинання / відкат до рівня й відбій) → вхід;
  кадр 267: «не став ліміти по цифрах, а дивись на реакцію ціни в зоні»; кадр 212: «що зробила наступна свічка (підтвердила / скасувала)».
НЕ ПІДТВЕРДЖЕНО в джерелах: ТФ реакції, кількість свічок, формальна ознака «реакції», відсоток відкату. Тому визначення нижче — DOСЛІДНИЦЬКА ГІПОТЕЗА (RESEARCH_HYPOTHESIS), а не авторське правило.

Визначення (LONG; SHORT дзеркально), на закритих барах ТФ картки (M15), без lookahead:
  TOUCH   — перший закритий бар з відкриттям ≥ created_ts, що торкнувся зони (low ≤ zone_hi).            [RESEARCH_HYPOTHESIS]
  REACT   — перший закритий бар ПІСЛЯ TOUCH: бичачий (close > open) і закриття вище zone_hi.             [RESEARCH_HYPOTHESIS; «відбій» і «закриття» — за змістом кадрів 225–226/212, поріг — наш]
  CONFIRM — наступний закритий бар після REACT: low не нижче low REACT і бичачий (close > open).          [RESEARCH_HYPOTHESIS; за змістом кадру 212 «наступна свічка підтвердила»]
  V1 = вхід ринково на open бару після REACT; V2 = вхід ринково на open бару після CONFIRM; SL/цілі картки без змін.
Скасування до входу: low ≤ SL картки або сплив expires_ts → НЕМАЄ_ВХОДУ."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

M15 = 900.0
LABEL = "RESEARCH_HYPOTHESIS"


def _long(card: Dict[str, Any]) -> bool:
    return str(card.get("direction") or "").upper() != "SHORT"


def _bull(b: Dict[str, Any], long_: bool) -> bool:
    return b["close"] > b["open"] if long_ else b["close"] < b["open"]


def signal_bar_start(card: Dict[str, Any]) -> float:
    """Початок M15-бару, у якому картка стала відомою (момент доставки/створення). Бари, що закрились ДО цього моменту, не використовуються;
    бар, який формувався на момент сигналу, — використовується, але лише після свого закриття (рішення на закритті, вхід на відкритті наступного бару)."""
    sig = max(float(card["created_ts"]), float(card.get("sent_ts") or 0.0))
    return (sig // M15) * M15


def find_events(card: Dict[str, Any], bars: List[Dict[str, Any]], now: float) -> Dict[str, Any]:
    """TOUCH/REACT/CONFIRM за закритими барами. Повертає індекси та часи; None — подія не настала до now/expires/SL."""
    long_ = _long(card)
    zhi, zlo, sl = float(card["zone_hi"]), float(card["zone_lo"]), float(card["sl"])
    t0, tx = signal_bar_start(card), float(card["expires_ts"])
    bs = [b for b in sorted(bars, key=lambda x: x["ts"]) if b["ts"] + M15 <= now and b["ts"] >= t0 and b["ts"] < tx]
    out: Dict[str, Any] = {"touch": None, "react": None, "confirm": None, "cancelled": None, "bars": len(bs)}
    st = 0                                           # 0 чекаємо TOUCH, 1 — REACT, 2 — CONFIRM
    react_extreme = None
    for i, b in enumerate(bs):
        invalid = (b["low"] <= sl) if long_ else (b["high"] >= sl)
        if invalid and st < 3:
            out["cancelled"] = b["ts"]
            break
        if st == 0:
            if (b["low"] <= zhi) if long_ else (b["high"] >= zlo):
                out["touch"], st = i, 1
            continue
        if st == 1:
            ok = _bull(b, long_) and ((b["close"] > zhi) if long_ else (b["close"] < zlo))
            if ok:
                out["react"], st, react_extreme = i, 2, (b["low"] if long_ else b["high"])
            continue
        if st == 2:
            held = (b["low"] >= react_extreme) if long_ else (b["high"] <= react_extreme)
            if held and _bull(b, long_):
                out["confirm"], st = i, 3
                break
            if not held:                              # реакцію скасовано наступною свічкою — шукаємо нову REACT з цього бару
                st = 1
                ok = _bull(b, long_) and ((b["close"] > zhi) if long_ else (b["close"] < zlo))
                if ok:
                    out["react"], st, react_extreme = i, 2, (b["low"] if long_ else b["high"])
    out["_bars"] = bs
    return out


def simulate_entry(card: Dict[str, Any], bars: List[Dict[str, Any]], entry_idx: int, cost_r_fn=None) -> Dict[str, Any]:
    """Ринковий вхід на open бару entry_idx; SL/TP1 картки; у барі входу SL перевіряється першим (консервативно, як office_signal_track)."""
    long_ = _long(card)
    sl, tp1 = float(card["sl"]), card.get("tp1")
    if entry_idx >= len(bars):
        return {"status": "НЕМАЄ_ВХОДУ", "why": "бар входу ще не закрито"}
    e = float(bars[entry_idx]["open"])
    if tp1 is None:
        return {"status": "НЕМАЄ_ЦІЛІ"}
    tp1 = float(tp1)
    if (long_ and not (sl < e < tp1)) or ((not long_) and not (tp1 < e < sl)):
        return {"status": "ПРОПУЩЕНО_ЦІНА_ПОЗА_ПЛАНОМ", "entry": e}
    risk = abs(e - sl)
    rr = abs(tp1 - e) / risk
    risk_pct = risk / e * 100.0
    cost = (cost_r_fn(risk_pct) or 0.0) if cost_r_fn else 0.0
    res: Dict[str, Any] = {"entry": e, "entry_ts": bars[entry_idx]["ts"], "rr_to_tp1": round(rr, 3), "risk_pct": round(risk_pct, 3), "cost_r": round(cost, 3), "status": "ВІДКРИТА", "r_net": None}
    mfe = mae = 0.0
    for b in bars[entry_idx:]:
        hi, lo = b["high"], b["low"]
        adv = ((hi - e) if long_ else (e - lo)) / risk
        dd = ((e - lo) if long_ else (hi - e)) / risk
        mfe, mae = max(mfe, adv), max(mae, dd)
        if (lo <= sl) if long_ else (hi >= sl):
            res.update(status="SL", r_net=round(-1.0 - cost, 3), exit_ts=b["ts"])
            break
        if (hi >= tp1) if long_ else (lo <= tp1):
            res.update(status="TP1", r_net=round(rr - cost, 3), exit_ts=b["ts"])
            break
    res.update(mfe_r=round(mfe, 2), mae_r=round(mae, 2))
    return res


def evaluate(card: Dict[str, Any], bars: List[Dict[str, Any]], now: float, cost_r_fn=None) -> Dict[str, Any]:
    """V1/V2 для однієї картки. Вхід шукається лише до expires_ts картки, але супровід угоди (SL/TP1) триває на всіх закритих барах після входу — як у фактичному paper.
    Фактичний V0 береться окремо (radar_watch.evaluate_card) у скрипті replay."""
    ev = find_events(card, bars, now)
    bs = ev.pop("_bars")
    t0, tx = signal_bar_start(card), float(card["expires_ts"])
    full = [b for b in sorted(bars, key=lambda x: x["ts"]) if b["ts"] + M15 <= now and b["ts"] >= t0]      # bs — префікс full (обрізаний за expires_ts)
    ohlc = lambda i: None if i is None else {k: bs[i][k] for k in ("ts", "open", "high", "low", "close")}  # noqa: E731
    out: Dict[str, Any] = {"events": {**{k: (bs[ev[k]]["ts"] if ev.get(k) is not None else None) for k in ("touch", "react", "confirm")}, "cancelled": ev.get("cancelled")}, "label": LABEL,
                           "events_ohlc": {k: ohlc(ev.get(k)) for k in ("touch", "react", "confirm")}, "data_end_ts": (full[-1]["ts"] + M15) if full else None}
    if ev.get("cancelled") is not None:
        out["cancel_bar"] = next(({k: b[k] for k in ("ts", "open", "high", "low", "close")} for b in bs if b["ts"] == ev["cancelled"]), None)
    for name, key in (("V1_react", "react"), ("V2_react_confirm", "confirm")):
        i = ev.get(key)
        if i is None:
            out[name] = {"status": "НЕМАЄ_ВХОДУ", "why": "скасовано до реакції (low досяг SL)" if ev.get("cancelled") else "реакції ще не було"}
        elif i + 1 >= len(full):
            out[name] = {"status": "НЕМАЄ_ВХОДУ", "why": "бар входу ще не закрито"}
        elif full[i + 1]["ts"] >= tx:
            out[name] = {"status": "НЕМАЄ_ВХОДУ", "why": "строк картки минув до входу"}
        else:
            r = simulate_entry(card, full, i + 1, cost_r_fn)
            if r.get("entry_ts"):
                r["delay_min_vs_touch"] = None if ev.get("touch") is None else round((r["entry_ts"] - bs[ev["touch"]]["ts"]) / 60.0, 1)
            out[name] = r
    return out

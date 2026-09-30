"""Ведення позначеної угоди до кінця руху (поради, не ордери). Чисті правила на свічках; кожна подія — один раз (ключ = код[:рівень]).

Схема: беззбиток (ціна пройшла 1R) → TP1: закрий 40%, стоп у беззбиток → TP2: закрий ще 30%, стоп на TP1 → runner 30%: тримаємо, поки жива
структура H1/H4, стоп підтягуємо за кожним новим HL (лонг) / LH (шорт) → кінець угоди — лише злам структури старшого ТФ або стоп runner'а.
Добір — один раз: ретест пробитого H1-рівня з підтвердженням M15; сумарний ризик не більший за початковий. Перезахід — один раз після стопу:
старша структура ціла + нове підтвердження на M15 + RR ≥ мінімуму. Без свіжих свічок порад немає."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

H1 = 3600.0
M15 = 900.0
PART_TP1, PART_TP2 = 40, 30
TRAIL_MIN_ATR = 0.25          # стоп підтягуємо, лише якщо новий рівень кращий за поточний не менше ніж на 0,25×ATR(H1)
REENTRY_WINDOW_SEC = 6 * 3600
ADD_MAX = 1
REENTRY_MAX = 1


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except (TypeError, ValueError):
        return None


def _closed(rows: Any, step: float, now: float) -> List[Dict[str, Any]]:
    out = []
    for c in rows if isinstance(rows, list) else []:
        t = _ts((c or {}).get("ts"))
        if t is not None and t + step <= now and all(_f(c.get(k)) is not None for k in ("high", "low", "close")):
            out.append({**c, "_t": t})
    return sorted(out, key=lambda r: r["_t"])


def swings(rows: List[Dict[str, Any]], long_: bool, k: int = 2) -> List[Dict[str, Any]]:
    """Підтверджені свінги (по k свічок з боків): для лонга — HL (свінг-мінімуми), для шорта — LH (свінг-максимуми)."""
    key = "low" if long_ else "high"
    out = []
    for i in range(k, len(rows) - k):
        v = float(rows[i][key])
        around = [float(rows[j][key]) for j in range(i - k, i + k + 1) if j != i]
        if (long_ and all(v < a for a in around)) or ((not long_) and all(v > a for a in around)):
            out.append({"t": rows[i]["_t"], "price": v})
    return out


def atr(rows: List[Dict[str, Any]], n: int = 14) -> Optional[float]:
    trs = []
    for i in range(1, len(rows)):
        h, l, pc = float(rows[i]["high"]), float(rows[i]["low"]), float(rows[i - 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    trs = trs[-n:]
    return sum(trs) / len(trs) if len(trs) >= 3 else None


def _hit_time(rows: List[Dict[str, Any]], long_: bool, level: Optional[float], since: float) -> Optional[float]:
    if level is None:
        return None
    for r in rows:
        if r["_t"] + H1 <= since:
            continue
        if (long_ and float(r["high"]) >= level) or ((not long_) and float(r["low"]) <= level):
            return r["_t"] + H1
    return None


def advise(pos: Dict[str, Any], *, h1: Any, m15: Any, h4: Any = None, sent: Optional[set] = None, now_ts: float, price: Optional[float] = None) -> List[Dict[str, str]]:
    """Список нових порад (ще не надісланих) у порядку важливості. `sent` — коди/ключі, що вже надсилались для цієї угоди."""
    from office_user_messages import ticker
    from office_user_messages import _px as px

    sent = sent or set()
    side = str(pos.get("direction") or "").upper()
    long_ = side != "SHORT"
    sym = str(pos.get("symbol") or "")
    T = ticker(sym)
    entry, sl0, tp1, tp2 = (_f(pos.get(k)) for k in ("entry", "sl", "tp1", "tp2"))
    opened = _ts(pos.get("opened_at")) or 0.0
    hh = _closed(h1, H1, now_ts)
    mm = _closed(m15, M15, now_ts)
    if not hh or entry is None or sl0 is None:
        return []   # без свіжих свічок порад немає
    last_close = _f(price) if price is not None else float(hh[-1]["close"])
    a1 = atr(hh)
    out: List[Dict[str, str]] = []

    def add(code: str, text: str) -> None:
        if code not in sent:
            out.append({"code": code, "text": text})

    # стоп ціною (до всього іншого)
    if (long_ and last_close <= sl0) or ((not long_) and last_close >= sl0):
        stop_hit = True
    else:
        stop_hit = False
    t_tp1 = _hit_time(hh, long_, tp1, opened)
    t_tp2 = _hit_time(hh, long_, tp2, opened)
    risk = abs(entry - sl0)
    # беззбиток: ціна пройшла 1R (ще до TP1)
    one_r = entry + risk if long_ else entry - risk
    if t_tp1 is None and _hit_time(hh, long_, one_r, opened) is not None and not stop_hit:
        add("BREAKEVEN", f"🟡 {T} · беззбиток · стоп → {px(entry, sym)}")
    if t_tp1 is not None:
        add("TP1", f"🎯 {T} · TP1 · закрий {PART_TP1}%, стоп у беззбиток {px(entry, sym)}")
    if t_tp2 is not None:
        add("TP2", f"🎯 {T} · TP2 · закрий ще {PART_TP2}%, стоп на TP1 {px(tp1, sym)}")
    # runner: після TP2 (якщо TP2 немає — після TP1) стоп за кожним новим HL/LH
    t_run = t_tp2 or (t_tp1 if tp2 is None else None)
    cur_stop = tp1 if t_tp2 else entry
    if t_run is not None and a1:
        sw = [s for s in swings(hh, long_) if s["t"] >= t_run - H1]
        best = None
        for s in sw:
            lvl = s["price"]
            better = (lvl > cur_stop + TRAIL_MIN_ATR * a1) if long_ else (lvl < cur_stop - TRAIL_MIN_ATR * a1)
            if better:
                best = lvl if best is None else (max(best, lvl) if long_ else min(best, lvl))
        if best is not None:
            add(f"TRAIL:{round(best, 8)}", f"📈 {T} · трейлінг · стоп → {px(best, sym)}")
            cur_stop = best
        # кінець угоди: злам структури старшого ТФ (закриття H1 за останнім підтвердженим HL/LH) або стоп runner'а
        run_sw = sw[-1]["price"] if sw else None
        stop_lvl = max([x for x in (cur_stop, run_sw) if x is not None]) if long_ and (cur_stop or run_sw) else (min([x for x in (cur_stop, run_sw) if x is not None]) if (cur_stop or run_sw) else None)
        if stop_lvl is not None:
            for r in hh:
                if r["_t"] + H1 > t_run and ((long_ and float(r["close"]) < stop_lvl) or ((not long_) and float(r["close"]) > stop_lvl)):
                    add("END_STRUCTURE", f"🏁 {T} · злам структури H1 · закрий залишок")
                    break
    if stop_hit:
        add("STOP_PRICE", f"🔴 {T} · ціна досягла стопа")
    # добір: один раз, після TP1, ретест пробитого H1-рівня з підтвердженням M15
    if t_tp1 is not None and not stop_hit and "END_STRUCTURE" not in {o["code"] for o in out} and sum(1 for k in sent if k.startswith("ADD")) < ADD_MAX and a1 and mm:
        prior = [s for s in swings([r for r in hh if r["_t"] + H1 <= (t_tp1 or now_ts)], not long_)]   # пробитий рівень: останній протилежний свінг до TP1
        lvl = prior[-1]["price"] if prior else None
        if lvl is not None:
            tol = 0.15 * a1
            last = mm[-1]
            touched = (float(last["low"]) <= lvl + tol) if long_ else (float(last["high"]) >= lvl - tol)
            held = (float(last["close"]) > lvl and float(last["close"]) > float(last["open"])) if long_ else (float(last["close"]) < lvl and float(last["close"]) < float(last["open"]))
            if touched and held and ((long_ and last_close > entry) or ((not long_) and last_close < entry)):
                new_stop = lvl - 0.25 * a1 if long_ else lvl + 0.25 * a1
                add("ADD", f"➕ {T} · добір · {px(last_close, sym)}, стоп {px(new_stop, sym)}")
    return out


def reentry(pos: Dict[str, Any], *, m15: Any, h4: Any, sent: set, now_ts: float, stop_alert_ts: Optional[float], tp1: Any = None) -> Optional[Dict[str, str]]:
    """Перезахід — один раз на ідею, після стопу: у межах вікна, старша структура (H4) ціла, є нове підтвердження на M15, RR ≥ мінімуму."""
    from office_user_messages import ticker, _px as px
    from office_alert_gate import net_rr

    if stop_alert_ts is None or "REENTRY" in sent or now_ts - stop_alert_ts > REENTRY_WINDOW_SEC:
        return None
    side = str(pos.get("direction") or "").upper()
    long_ = side != "SHORT"
    entry, sl0 = _f(pos.get("entry")), _f(pos.get("sl"))
    t1 = _f(tp1 if tp1 is not None else pos.get("tp1"))
    mm = [r for r in _closed(m15, M15, now_ts) if r["_t"] >= stop_alert_ts - M15]
    h4c = _closed(h4, 4 * H1, now_ts)
    if entry is None or sl0 is None or t1 is None or len(mm) < 2 or len(h4c) < 8:
        return None
    # старша структура ціла: жодне закриття H4 після входу не за останнім H4-свінгом проти угоди
    sw4 = swings([r for r in h4c if r["_t"] < stop_alert_ts], long_)
    if sw4:
        lvl4 = sw4[-1]["price"]
        if any(((long_ and float(r["close"]) < lvl4) or ((not long_) and float(r["close"]) > lvl4)) for r in h4c if r["_t"] >= stop_alert_ts - 4 * H1):
            return None
    sweep_ext = min(float(r["low"]) for r in mm) if long_ else max(float(r["high"]) for r in mm)
    last = mm[-1]
    reclaimed = (float(last["close"]) > entry) if long_ else (float(last["close"]) < entry)
    bullish = (float(last["close"]) > float(last["open"])) if long_ else (float(last["close"]) < float(last["open"]))
    if not (reclaimed and bullish):
        return None
    a1 = atr(_closed(h4c, 4 * H1, now_ts)) or abs(entry - sl0)
    new_entry = float(last["close"])
    new_stop = sweep_ext - 0.25 * (a1 / 4.0) if long_ else sweep_ext + 0.25 * (a1 / 4.0)
    nr = net_rr(new_entry, new_stop, t1)
    if not nr or nr["rr_net"] < 1.5:
        return None
    sym = str(pos.get("symbol") or "")
    return {"code": "REENTRY", "text": f"🔄 {ticker(sym)} · перезахід · {px(new_entry, sym)}, стоп {px(new_stop, sym)}"}

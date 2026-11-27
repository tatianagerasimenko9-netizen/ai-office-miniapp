"""«Лев» — екран радника в Mini App (перша версія, згода власниці 27.11.2026). ЛИШЕ ЧИТАННЯ: нічого не надсилає, ордерів не відкриває, сигнали не змінює.
Принцип «програма рахує, Лев пояснює»: усі суми рахуються тут із сигналів Офісу (br_test_signal / br_test_event) і поточної ціни; тексти Лева — шаблони над цими числами, без вигаданих прогнозів.
Суми в доларах при ризику RISK_USD на угоду (типово $10, як на картках). Офіс НЕ бачить біржу: «відкрита угода» = сигнал СВІНГ/ІНТРАДЕЙ зі статусом SENT і подією ENTRY.
  зараз        = RISK × (ціна − вхід) у бік угоди / (вхід − стоп)
  якщо стоп    = −RISK (без комісії та гіршого виконання)
  до стопа ще  = зараз − (якщо стоп)
Вимкнути: LEV_APP=0."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
CALM_ATR_PCT = 0.023
_PX: Dict[str, Any] = {"ts": 0.0, "val": {}}


def enabled() -> bool:
    return os.getenv("LEV_APP", "1").strip().lower() in ("1", "true", "yes", "on")


def risk_usd() -> float:
    try: return float(os.getenv("LEV_RISK_USD", "10"))
    except ValueError: return 10.0


def live_prices(max_age: float = 15.0) -> Dict[str, Any]:
    """Усі ціни USDT-M одним запитом (кеш 15 с). Збій → попередній кеш (може бути порожній) із його часом."""
    now = time.time()
    if now - _PX["ts"] <= max_age and _PX["val"]:
        return _PX
    try:
        from office_market_data import _http_get_json
        raw = _http_get_json("https://fapi.binance.com/fapi/v1/ticker/price", {})
        if isinstance(raw, list) and raw:
            _PX["val"] = {str(x["symbol"]): float(x["price"]) for x in raw if x.get("price") not in (None, "")}; _PX["ts"] = now
    except Exception:  # noqa: BLE001
        pass
    return _PX


def _hyp(row: Dict[str, Any]) -> Dict[str, Any]:
    try: return json.loads(row.get("hyp_json") or "{}") or {}
    except Exception: return {}


def _usd(x: float) -> str:
    return ("+" if x >= 0 else "−") + "$" + f"{abs(x):,.0f}".replace(",", " ")


def _px(x: float) -> str:
    a = abs(x)
    s = f"{x:,.0f}" if a >= 1000 else (f"{x:,.2f}" if a >= 10 else (f"{x:.4f}" if a >= 0.1 else f"{x:.6f}"))
    return s.replace(",", " ").replace(".", ",")


def _pl(n: int, one: str, few: str, many: str) -> str:
    """Українська множина: 1 угода, 2 угоди, 5 угод."""
    n10, n100 = abs(n) % 10, abs(n) % 100
    return f"{n} {one if n10 == 1 and n100 != 11 else (few if 2 <= n10 <= 4 and not 12 <= n100 <= 14 else many)}"


SH = ("шорт", "шорти", "шортів"); LG = ("лонг", "лонги", "лонгів"); UG = ("угода", "угоди", "угод")


def _hm(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(KYIV).strftime("%H:%M")


def _dm(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone(KYIV).strftime("%d.%m %H:%M")


def _strat(sig_id: str) -> str:
    return "СВІНГ" if sig_id.startswith("SW|") else ("ІНТРАДЕЙ" if sig_id.startswith("TD|") else ("ВІДСКОК" if sig_id.startswith("BN|") else "B&R"))


def _hold_s(sig_id: str) -> float:
    return 10 * 86400.0 if sig_id.startswith("SW|") else 48 * 3600.0


def _res(d: Dict[str, Any], R: float) -> Optional[float]:
    """Підсумок закритого сигналу в $ (стоп = −ризик, ціль = за ціною цілі, за часом = за ціною події). Для відкритих — None (рахує екран за живою ціною)."""
    try:
        e, sl = float(d["entry"]), float(d["sl"]); risk = abs(e - sl); side = 1 if d["direction"] == "LONG" else -1
        if d["status"] == "SL": return -R
        if d["status"] in ("TP1", "TP3") and d.get("tp"): return round(R * abs(d["tp"] - e) / risk, 1)
        if d["status"] == "TIMEOUT" and "ENTRY" in d["ev"] and d["ev"].get("TIMEOUT") and d["ev"]["TIMEOUT"][1]: return round(R * side * (float(d["ev"]["TIMEOUT"][1]) - e) / risk, 1)
    except Exception: pass
    return None


def _rows(db: str, since: float) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall
    cols = "sig_id, seq, symbol, direction, entry, sl, targets_json, hyp_json, created_ts, status"
    out = []
    for r in _fetchall(db, f"SELECT {cols} FROM br_test_signal WHERE (sig_id LIKE 'SW|%' OR sig_id LIKE 'TD|%' OR sig_id LIKE 'BN|%') AND (status = 'SENT' OR created_ts >= ?) ORDER BY created_ts", (since,)):
        d = dict(zip(cols.split(", "), r))
        try: d["tp"] = float((json.loads(d["targets_json"]) or [{}])[0].get("p"))
        except Exception: d["tp"] = None
        out.append(d)
    ev: Dict[str, Dict[str, Any]] = {}
    ids = [d["sig_id"] for d in out]
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        for sid, level, ts, price in _fetchall(db, f"SELECT sig_id, level, touched_ts, price FROM br_test_event WHERE sig_id IN ({','.join('?' * len(chunk))})", tuple(chunk)):
            ev.setdefault(sid, {})[level] = (ts, price)
    for d in out: d["ev"] = ev.get(d["sig_id"], {})
    return out


def _trade(d: Dict[str, Any], price: Optional[float], now: float, R: float) -> Dict[str, Any]:
    side = 1 if d["direction"] == "LONG" else -1; e, sl = float(d["entry"]), float(d["sl"]); risk = abs(e - sl); t_in = float(d["ev"]["ENTRY"][0]); hold = _hold_s(d["sig_id"])
    sw = d["sig_id"].startswith("SW|"); hy = _hyp(d); sym = d["symbol"].replace("USDT", "")
    t: Dict[str, Any] = {"sig_id": d["sig_id"], "seq": d["seq"], "sym": sym, "strat": _strat(d["sig_id"]), "dir": d["direction"], "dir_ua": "лонг" if side > 0 else "шорт", "entry": _px(e), "sl": _px(sl),
                         "tp": _px(d["tp"]) if d["tp"] else "—", "if_stop": -R, "exit_ts": t_in + hold, "exit_at": _dm(t_in + hold), "opened": _dm(t_in), "tp_usd": (_usd(R * abs(d["tp"] - e) / risk) if d["tp"] and risk > 0 else ""), "rep": bool(hy.get("rep")), "opp": hy.get("opp"), "pair": hy.get("pair")}
    t["age"] = (f"{int((now - t_in) // 86400) + 1}-й день із 10" if sw else f"{max(1, int((now - t_in) // 3600) + 1)}-та год із 48")
    if price is None or risk <= 0:
        t.update({"price": None, "now": None, "to_stop": None, "pos": None, "dist_pct": None}); return t
    r_now = side * (price - e) / risk; t["price"] = _px(price); t["now"] = round(R * r_now, 1); t["to_stop"] = round(R * (r_now + 1), 1); t["dist_pct"] = round(100 * side * (price - sl) / price, 1)
    if d["tp"]:
        span = (d["tp"] - sl) * side; t["pos"] = round(min(1.0, max(0.0, side * (price - sl) / span)), 3) if span > 0 else None; t["entry_pos"] = round(min(1.0, max(0.0, side * (e - sl) / span)), 3) if span > 0 else None
    else: t["pos"] = None
    return t


def _verdict(d: Dict[str, Any], same_n: int, same_if_stop: float, R: float, is_open: bool = False) -> Dict[str, Any]:
    """Висновок Лева про сигнал — лише з позначок, які вже перевірені на історії й погоджені (спокійна монета, повторний після стопа, протилежні сигнали, новини/слабкий сигнал)."""
    hy = _hyp(d); e = float(d["entry"]); sw = d["sig_id"].startswith("SW|"); W = SH if d["direction"] == "SHORT" else LG
    cautions = [str(x) for x in (hy.get("pair"), hy.get("opp"), hy.get("rep")) if x]
    w = hy.get("warn"); cautions += [str(x) for x in (w if isinstance(w, list) else ([w] if w else []))]
    c = hy.get("caution"); cautions += [str(x) for x in (c if isinstance(c, list) else ([c] if c else []))]
    calm = bool(sw and hy.get("atr") and float(hy["atr"]) / e < CALM_ATR_PCT)
    facts = [["Стратегія", f"{_strat(d['sig_id'])} · {'до 10 діб' if sw else 'до 48 год'}"]]
    if sw: facts.append(["Монета", "спокійна — на історії такі кращі (+$2,20 на угоду)" if calm else "рухлива — на історії слабші за спокійні"])
    if hy.get("why"): facts.append(["Чому сигнал", str(hy["why"])])
    cl = (hy.get("cluster") or {}).get("n") or 0
    if cl: facts.append(["Разом із ним", f"ще {cl} монет дали сигнал у той самий бік"])
    facts.append(["Ваш портфель", (f"крім нього відкрито {_pl(same_n, *W)}" if is_open else f"уже відкрито {_pl(same_n, *W)}") if same_n else f"інших відкритих {W[2]} немає"])
    after = (f"Разом із ним зараз відкрито {_pl(same_n + 1, *W)} в один бік." if is_open else f"З цим сигналом буде {_pl(same_n + 1, *W)} в один бік.") + f" Якщо всі закриються стопом: {_usd(same_if_stop - R)}."
    if cautions: title = "Є застереження — дивіться нижче"; text = "Сигнал пройшов правила, але на історії такі випадки слабші: " + "; ".join(cautions) + "."
    elif calm: title = "Чистий сигнал на спокійній монеті"; text = "Застережень немає. Монета спокійна — саме на таких наша історія найкраща."
    else: title = "Звичайний сигнал, застережень немає"; text = "Сигнал пройшов правила. Особливих плюсів чи мінусів на історії для нього немає."
    return {"title": title, "text": text, "after": after, "facts": facts, "cautions": cautions, "calm": calm}


def state(db: str, prices: Optional[Dict[str, float]] = None, price_ts: Optional[float] = None, now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now; R = risk_usd()
    if prices is None:
        p = live_prices(); prices, price_ts = p["val"], p["ts"]
    rows = _rows(db, now - 48 * 3600)
    opened = [d for d in rows if d["status"] == "SENT" and "ENTRY" in d["ev"]]
    trades = [_trade(d, prices.get(d["symbol"]), now, R) for d in opened]
    known = [t for t in trades if t["now"] is not None]
    sums = {"n": len(trades), "now": round(sum(t["now"] for t in known), 0), "to_stop": round(sum(t["to_stop"] for t in known), 0), "if_stop": round(-R * len(trades), 0), "unknown": len(trades) - len(known)}
    groups = []
    for strat in ("СВІНГ", "ІНТРАДЕЙ"):
        for dr, nm in (("SHORT", "шорти"), ("LONG", "лонги")):
            g = [t for t in trades if t["strat"] == strat and t["dir"] == dr]
            if not g: continue
            gk = [t for t in g if t["now"] is not None]
            groups.append({"title": f"{strat} · {nm} · {len(g)}", "sub": ("одна ставка на " + ("падіння" if dr == "SHORT" else "ріст")) if len(g) >= 5 else "", "now": round(sum(t["now"] for t in gk), 0) if gk else None, "n": len(g),
                           "trades": sorted(g, key=lambda t: (t["now"] is None, -(t["now"] or 0)))})
    for t in trades:
        t["soon"] = bool(t["exit_ts"] - now <= 86400); t["near"] = bool(t["now"] is not None and t["now"] <= -R / 2)       # «біля стопа» = уже втрачено понад половину ризику
    att: List[Dict[str, Any]] = []
    near = sorted((t for t in trades if t["near"]), key=lambda t: t["now"])
    if near: att.append({"level": "red", "title": (f"{near[0]['sym']} біля стопа" if len(near) == 1 else f"{_pl(len(near), *UG)} біля стопа"), "detail": ", ".join(f"{t['sym']} {_usd(t['now'])}" for t in near[:4]) + (" …" if len(near) > 4 else ""), "filter": "near"})
    soon = sorted((t for t in trades if t["soon"]), key=lambda t: t["exit_ts"])
    if soon: att.append({"level": "yellow", "title": f"За часом сьогодні виходить {_pl(len(soon), *UG)}", "detail": f"перша — {soon[0]['sym']}, {soon[0]['exit_at']}", "filter": "soon"})
    for dr, mv in (("SHORT", "піде вгору"), ("LONG", "піде вниз")):
        n = sum(1 for t in trades if t["dir"] == dr)
        if n >= 5: att.append({"level": "yellow", "title": f"{_pl(n, *(SH if dr == 'SHORT' else LG))} — одна ставка", "detail": f"якщо ринок {mv} до стопів: {_usd(-R * n)}", "filter": dr.lower()})
    by_sym: Dict[str, set] = {}
    for t in trades: by_sym.setdefault(t["sym"], set()).add(t["dir"])
    both = sorted(s for s, v in by_sym.items() if len(v) == 2)
    if both: att.append({"level": "yellow", "title": f"{', '.join(both)} — угоди в обидва боки", "detail": "вони гасять одна одну", "filter": "both"})
    for t in trades: t["both"] = t["sym"] in both
    if not trades: lev = "Відкритих угод немає. Чекаємо на сигнал."
    else:
        ns = sum(1 for t in trades if t["dir"] == "SHORT"); nl = len(trades) - ns
        if len(trades) >= 5 and max(ns, nl) / len(trades) >= 0.8: lev = f"Майже все — {'шорти' if ns > nl else 'лонги'}. Нову угоду в той самий бік я б зважив двічі."
        elif near: lev = "Є угоди біля стопа — подивіться першими."
        else: lev = "Усе йде за планом. Нових дій не потрібно."
    open_same = {dr: sum(1 for t in trades if t["dir"] == dr) for dr in ("LONG", "SHORT")}
    ST = {"NEW": "щойно прийшов", "SENT": "відкрито", "SL": "стоп", "TP1": "ціль", "TP3": "ціль", "TIMEOUT": "закрито за часом", "EXPIRED_UNSENT": "не надіслано", "CANCEL": "скасовано"}
    signals = []
    for d in sorted((d for d in rows if d["created_ts"] >= now - 48 * 3600), key=lambda d: -d["created_ts"])[:40]:
        same = open_same[d["direction"]] - (1 if d["status"] == "SENT" and "ENTRY" in d["ev"] else 0); mins = int((now - d["created_ts"]) / 60)
        signals.append({"sig_id": d["sig_id"], "strat": _strat(d["sig_id"]), "seq": d["seq"], "sym": d["symbol"].replace("USDT", ""), "dir": d["direction"], "dir_ua": "лонг" if d["direction"] == "LONG" else "шорт",
                        "entry": _px(float(d["entry"])), "sl": _px(float(d["sl"])), "tp": _px(d["tp"]) if d["tp"] else "—", "tp_usd": (_usd(R * abs(d["tp"] - float(d["entry"])) / abs(float(d["entry"]) - float(d["sl"]))) if d["tp"] else ""),
                        "status": ST.get(d["status"], d["status"]), "open": d["status"] == "SENT", "res": _res(d, R), "kind": {"SL": "sl", "TP1": "tp", "TP3": "tp", "TIMEOUT": "time", "SENT": "open", "NEW": "open"}.get(d["status"], "none"), "ago": (f"{mins} хв тому" if mins < 90 else f"{mins // 60} год тому"), "at": _dm(d["created_ts"]), "lev": _verdict(d, same, -R * same, R, is_open=(d["status"] == "SENT" and "ENTRY" in d["ev"]))})
    return {"ok": True, "ts": now, "updated": _hm(now), "price_ts": price_ts, "price_at": _hm(price_ts) if price_ts else None, "stale": bool(not price_ts or now - price_ts > 120), "risk": R,
            "lev": lev, "note": "Рахую за сигналами Офісу, біржу не бачу. При різкому русі стоп може виконатись гірше за розрахунок.", "attention": att, "sums": sums, "groups": groups, "signals": signals, "order_authorized": False}


def zvirka(db: str, prices: Optional[Dict[str, float]] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Живий підсумок стратегій: закриті (стоп / ціль / за часом) і відкриті угоди, суми при ризику RISK_USD. Без комісії."""
    from office_bridge import _fetchall
    now = time.time() if now is None else now; R = risk_usd(); prices = live_prices()["val"] if prices is None else prices; out = []
    for pfx, name in (("SW", "СВІНГ"), ("TD", "ІНТРАДЕЙ"), ("BN", "ВІДСКОК")):
        rs = _fetchall(db, "SELECT sig_id, symbol, direction, entry, sl, targets_json, status, created_ts FROM br_test_signal WHERE sig_id LIKE ? ORDER BY created_ts", (pfx + "|%",))
        tout = {sid: px for sid, px in _fetchall(db, "SELECT sig_id, price FROM br_test_event WHERE level = 'TIMEOUT' AND sig_id LIKE ?", (pfx + "|%",))}
        ent = {sid for (sid,) in _fetchall(db, "SELECT sig_id FROM br_test_event WHERE level = 'ENTRY' AND sig_id LIKE ?", (pfx + "|%",))}
        s = {"name": name, "since": _dm(rs[0][7]) if rs else None, "sl": 0, "tp": 0, "time": 0, "time_unknown": 0, "closed_usd": 0.0, "open": 0, "open_usd": 0.0, "open_unknown": 0}
        for sid, sym, dr, e, sl, tj, st, _ in rs:
            side = 1 if dr == "LONG" else -1; risk = abs(e - sl)
            if risk <= 0: continue
            if st == "SL": s["sl"] += 1; s["closed_usd"] -= R
            elif st in ("TP1", "TP3"):
                try: tp = float((json.loads(tj) or [{}])[0].get("p")); s["tp"] += 1; s["closed_usd"] += R * abs(tp - e) / risk
                except Exception: pass
            elif st == "TIMEOUT":
                if tout.get(sid) is not None: s["time"] += 1; s["closed_usd"] += R * side * (float(tout[sid]) - e) / risk
                else: s["time_unknown"] += 1
            elif st == "SENT" and sid in ent:
                s["open"] += 1; p = prices.get(sym)
                if p is None: s["open_unknown"] += 1
                else: s["open_usd"] += R * side * (p - e) / risk
        s["closed_usd"] = round(s["closed_usd"], 0); s["open_usd"] = round(s["open_usd"], 0); out.append(s)
    return {"ok": True, "updated": _hm(now), "risk": R, "rows": out}

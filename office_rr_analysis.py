"""Аналіз запропонованого правила RR ДО його впровадження (лише читання; правило на production НЕ змінюється).

Старе правило (діє): RR до TP1 після комісій ≥ 1,5.
Запропоноване правило (рішення власниці, чекає підтвердження): (1) зважений RR ≥ 1,5 за планом виходу 40% на TP1 + 30% на TP2 + 30% runner
(runner рахується як вихід на TP2), з комісією 0,10% за круг; (2) RR до TP1 ≥ 1,0 (також після комісій).

Формули (d — відстань до цілі у % від входу, risk — відстань до стопа у %, fee — комісія круга, 0,10%):
  RR до TP1        = (d1 − fee) / (risk + fee)                       — така сама, як `office_alert_gate.net_rr`
  зважений RR      = (0,4·d1 + 0,6·d2 − fee) / (risk + fee)          — TP2 немає → d2 = d1 (весь обсяг виходить на TP1)
Результат у R: симуляція плану виходу на реальних свічках (стоп перевіряється раніше за цілі в межах однієї свічки — консервативно):
  до TP1: стоп → −risk; TP1 → 40% на d1 і стоп у беззбиток; далі беззбиток → решта 60% по 0; TP2 → 60% на d2 (runner = TP2).
  R = (підсумок у % − fee) / risk. Не виконаний за час дії вхід — NOT_FILLED; не вирішена за горизонт — решта за ціною закриття.
TP2, якого в БД немає, відновлюється тією ж логікою, що й у production (`office_targets.structural_targets`), лише зі свічок ДО створення плану
(без підглядання); якщо обґрунтованого TP2 немає — як у production, TP2 нема.
"""
from __future__ import annotations

import io
import json
import os
import time
import urllib.parse
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

W_TP1, W_TP2 = 0.4, 0.6          # 40% TP1; 30% TP2 + 30% runner (= вихід на TP2)
OLD_MIN_RR = 1.5
NEW_MIN_WEIGHTED = 1.5
NEW_MIN_TP1 = 1.0
FILL_WINDOW_SEC = 24 * 3600
HORIZON_SEC = 72 * 3600


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def fee_pct() -> float:
    from office_alert_gate import fee_round_trip_pct

    return float(fee_round_trip_pct())


def rr_pair(entry: float, sl: float, tp1: float, tp2: Optional[float], fee: Optional[float] = None) -> Optional[Dict[str, float]]:
    fee = fee_pct() if fee is None else fee
    if not entry or entry <= 0:
        return None
    risk = abs(entry - sl) / entry * 100.0
    if risk <= 0:
        return None
    d1 = abs(tp1 - entry) / entry * 100.0
    d2 = abs(tp2 - entry) / entry * 100.0 if tp2 is not None else d1
    rr1 = max(d1 - fee, 0.0) / (risk + fee)
    rrw = max(W_TP1 * d1 + W_TP2 * d2 - fee, 0.0) / (risk + fee)
    return {"risk_pct": risk, "d1_pct": d1, "d2_pct": d2, "rr_tp1": rr1, "rr_weighted": rrw}


def passes_old(p: Dict[str, float]) -> bool:
    return p["rr_tp1"] + 1e-12 >= OLD_MIN_RR


def passes_new(p: Dict[str, float]) -> bool:
    return p["rr_weighted"] + 1e-12 >= NEW_MIN_WEIGHTED and p["rr_tp1"] + 1e-12 >= NEW_MIN_TP1


def geometry_ok(direction: str, entry: float, sl: float, tp1: float, tp2: Optional[float]) -> bool:
    long_ = str(direction).upper() != "SHORT"
    s = 1.0 if long_ else -1.0
    if not (s * (sl - entry) < 0 < s * (tp1 - entry)):
        return False
    return tp2 is None or s * (tp2 - tp1) > 0


def _ts(r: Dict[str, Any]) -> float:
    return datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00")).timestamp()


def simulate_R(direction: str, entry: float, sl: float, tp1: float, tp2: Optional[float], candles: List[Dict[str, Any]], start_ts: float,
               fee: Optional[float] = None) -> Dict[str, Any]:
    """Результат плану виходу 40% TP1 / 60% TP2 на свічках 15м. Вхід — перша свічка, що торкнулась ціни входу в межах вікна; далі з НАСТУПНОЇ свічки."""
    fee = fee_pct() if fee is None else fee
    long_ = str(direction).upper() != "SHORT"
    pr = rr_pair(entry, sl, tp1, tp2, fee)
    if not pr or not candles:
        return {"status": "NO_DATA"}
    risk, d1, d2 = pr["risk_pct"], pr["d1_pct"], pr["d2_pct"]
    i0 = None
    for i, r in enumerate(candles):
        t = _ts(r)
        if t + 900 <= start_ts:
            continue
        if t > start_ts + FILL_WINDOW_SEC:
            break
        if float(r["low"]) <= entry <= float(r["high"]):
            i0 = i
            break
    if i0 is None:
        return {"status": "NOT_FILLED"}
    t_fill = _ts(candles[i0]) + 900
    gross, stage = 0.0, 0
    end = t_fill + HORIZON_SEC
    last = None
    for r in candles[i0 + 1:]:
        if _ts(r) > end:
            break
        lo, hi, cl = float(r["low"]), float(r["high"]), float(r["close"])
        last = cl
        if stage == 0:
            if (long_ and lo <= sl) or ((not long_) and hi >= sl):
                return {"status": "STOP", "R": (-risk - fee) / risk, "gross_pct": -risk}
            if (long_ and hi >= tp1) or ((not long_) and lo <= tp1):
                gross += W_TP1 * d1
                stage = 1
                # та сама свічка: беззбиток/TP2 перевіряємо з наступної (консервативно)
                continue
        else:
            if (long_ and lo <= entry) or ((not long_) and hi >= entry):
                return {"status": "TP1_THEN_BE", "R": (gross - fee) / risk, "gross_pct": gross}
            if tp2 is not None and ((long_ and hi >= tp2) or ((not long_) and lo <= tp2)):
                gross += W_TP2 * d2
                return {"status": "TP2", "R": (gross - fee) / risk, "gross_pct": gross}
    if last is None:
        return {"status": "NO_DATA"}
    move = ((last - entry) if long_ else (entry - last)) / entry * 100.0
    if stage == 0:
        return {"status": "OPEN", "R": (move - fee) / risk, "gross_pct": move}
    if tp2 is None:   # TP2 немає: залишок 60% виходить разом із TP1 за планом «весь обсяг на TP1»
        gross += W_TP2 * d1
        return {"status": "TP1_ONLY", "R": (gross - fee) / risk, "gross_pct": gross}
    return {"status": "OPEN_AFTER_TP1", "R": (gross + W_TP2 * move - fee) / risk, "gross_pct": gross + W_TP2 * move}


# ---------- свічки з архіву data.binance.vision (не їсть ліміт API) ----------
_CACHE: Dict[tuple, List[Dict[str, Any]]] = {}
VISION = "https://data.binance.vision/data/futures/um/daily/klines/{sym}/15m/{sym}-15m-{day}.zip"


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def _vision_day(sym: str, day: str, getter: Optional[Callable[[str], bytes]] = None) -> List[Dict[str, Any]]:
    key = (sym, day)
    if key in _CACHE:
        return _CACHE[key]
    import urllib.request

    get = getter or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "office-rr/1"}), timeout=60).read())
    rows: List[Dict[str, Any]] = []
    try:
        z = zipfile.ZipFile(io.BytesIO(get(VISION.format(sym=urllib.parse.quote(sym), day=day))))
        for line in z.read(z.namelist()[0]).decode().splitlines():
            p = line.split(",")
            if p and p[0].isdigit():
                rows.append({"ts": _iso(int(p[0]) / 1000), "open": float(p[1]), "high": float(p[2]), "low": float(p[3]), "close": float(p[4]), "volume": float(p[5])})
    except Exception:  # noqa: BLE001
        rows = []
    _CACHE[key] = rows
    return rows


def candles_between(sym: str, t0: float, t1: float, getter: Optional[Callable[[str], bytes]] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    d = datetime.fromtimestamp(t0, tz=timezone.utc).date()
    last = datetime.fromtimestamp(t1, tz=timezone.utc).date()
    while d <= last:
        out.extend(_vision_day(sym, d.isoformat(), getter))
        d += timedelta(days=1)
    return [r for r in out if t0 <= _ts(r) <= t1]


def _resample(m15: List[Dict[str, Any]], sec: int, offset: int = 0) -> List[Dict[str, Any]]:
    b: Dict[int, Dict[str, Any]] = {}
    for r in m15:
        k = int((_ts(r) - offset) // sec * sec + offset)
        x = b.setdefault(k, {"ts": _iso(k), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": 0.0})
        x["high"] = max(x["high"], r["high"])
        x["low"] = min(x["low"], r["low"])
        x["close"] = r["close"]
    return [b[k] for k in sorted(b)]


def reconstruct_tp2(direction: str, entry: float, tp1: float, before: List[Dict[str, Any]]) -> Optional[float]:
    """TP2, який показав би production у момент плану: рівні лише зі свічок ДО створення (азія, PDH/PDL, тиждень, ATR(D1))."""
    import office_targets as T

    if len(before) < 96:
        return None
    m15 = before[-96:]
    daily = _resample(before, 86400)
    weekly = _resample(before, 604800, offset=4 * 86400)   # тижні Binance починаються в понеділок 00:00 UTC
    lv = T.levels(m15=m15, daily=daily[-20:], weekly=weekly[-4:])
    tg = T.structural_targets(direction=direction, entry=entry, tp1=tp1, lv=lv)
    return _f((tg.get("tp2") or {}).get("price"))


def evaluate_plan(p: Dict[str, Any], getter: Optional[Callable[[str], bytes]] = None) -> Dict[str, Any]:
    """p: symbol, direction, entry, sl, tp1, tp2?, ts (epoch). Повертає RR за обома правилами, прапорці проходження й результат у R."""
    sym, dr = str(p["symbol"]), str(p["direction"]).upper()
    entry, sl, tp1, tp2 = float(p["entry"]), float(p["sl"]), float(p["tp1"]), _f(p.get("tp2"))
    out: Dict[str, Any] = {**{k: p.get(k) for k in ("symbol", "direction", "entry", "sl", "tp1", "id", "note")}, "ts": p["ts"]}
    if not geometry_ok(dr, entry, sl, tp1, tp2):
        return {**out, "status": "BAD_GEOMETRY"}
    data = candles_between(sym, p["ts"] - 16 * 86400, p["ts"] + HORIZON_SEC + FILL_WINDOW_SEC, getter)
    before = [r for r in data if _ts(r) + 900 <= p["ts"]]
    after = [r for r in data if _ts(r) + 900 > p["ts"]]
    src = "БД"
    if tp2 is None:
        tp2 = reconstruct_tp2(dr, entry, tp1, before)
        if tp2 is not None and not geometry_ok(dr, entry, sl, tp1, tp2):
            tp2 = None
        src = "відновлено" if tp2 is not None else "немає"
    pr = rr_pair(entry, sl, tp1, tp2)
    if not pr:
        return {**out, "status": "BAD_GEOMETRY"}
    sim = simulate_R(dr, entry, sl, tp1, tp2, after, p["ts"]) if after else {"status": "NO_DATA"}
    return {**out, "tp2": tp2, "tp2_src": src, **pr, "old": passes_old(pr), "new": passes_new(pr), "sim": sim, "status": "OK"}


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Підсумок по групах: пройшло за старим / за новим / лише за новим; кількість, заповнених, результат у R."""
    ok = [r for r in rows if r.get("status") == "OK"]

    def grp(sel: Callable[[Dict[str, Any]], bool]) -> Dict[str, Any]:
        g = [r for r in ok if sel(r)]
        done = [r for r in g if (r["sim"] or {}).get("R") is not None]
        rs = [float(r["sim"]["R"]) for r in done]
        return {"n": len(g), "filled": len(done), "sum_R": round(sum(rs), 2), "avg_R": round(sum(rs) / len(rs), 2) if rs else None,
                "wins": sum(1 for x in rs if x > 0), "losses": sum(1 for x in rs if x < 0), "not_filled": sum(1 for r in g if (r["sim"] or {}).get("status") == "NOT_FILLED"),
                "no_data": sum(1 for r in g if (r["sim"] or {}).get("status") == "NO_DATA")}

    return {"total": len(rows), "usable": len(ok), "bad_geometry": sum(1 for r in rows if r.get("status") == "BAD_GEOMETRY"),
            "tp2_from_db": sum(1 for r in ok if r.get("tp2_src") == "БД"), "tp2_reconstructed": sum(1 for r in ok if r.get("tp2_src") == "відновлено"),
            "tp2_none": sum(1 for r in ok if r.get("tp2_src") == "немає"),
            "old_pass": grp(lambda r: r["old"]), "new_pass": grp(lambda r: r["new"]),
            "only_new": grp(lambda r: r["new"] and not r["old"]), "only_old": grp(lambda r: r["old"] and not r["new"]),
            "rejected_by_both": grp(lambda r: not r["old"] and not r["new"])}


# ---------- дані з БД ----------
def load_unique_plans(db: str) -> List[Dict[str, Any]]:
    """Унікальні плани з office_signals (службові дублі lev-watch-* щоциклу зводяться до одного за ключем символ/напрям/вхід/стоп/TP1)."""
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT signal_id, symbol, direction, entry_low, entry_high, sl, tp1, tp2, ts_created FROM office_signals "
                         "WHERE sl IS NOT NULL AND tp1 IS NOT NULL ORDER BY ts_created", ())
    seen: Dict[tuple, Dict[str, Any]] = {}
    for r in rows or []:
        sid, sym, dr, lo, hi, sl, tp1, tp2, ts = r
        lo_, hi_, sl_, tp1_ = _f(lo), _f(hi), _f(sl), _f(tp1)
        if None in (lo_, hi_, sl_, tp1_) or not sym or not dr:
            continue
        entry = (lo_ + hi_) / 2.0
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        key = (str(sym).upper(), str(dr).upper(), round(entry, 8), round(sl_, 8), round(tp1_, 8))
        if key in seen:
            continue
        seen[key] = {"id": str(sid)[:40], "symbol": str(sym).upper(), "direction": str(dr).upper(), "entry": entry, "sl": sl_, "tp1": tp1_, "tp2": _f(tp2), "ts": t}
    return sorted(seen.values(), key=lambda x: x["ts"])


def load_journal(db: str) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT trade_id, ts_open_utc, symbol, direction, entry_price, stop_loss, take_profit, r_multiple, outcome, status FROM trade_journal ORDER BY ts_open_utc", ())
    out = []
    for r in rows or []:
        tid, ts, sym, dr, en, sl, tp, rm, oc, st = r
        en_, sl_, tp_ = _f(en), _f(sl), _f(tp)
        if None in (en_, sl_, tp_) or not sym or not dr:
            continue
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        out.append({"id": str(tid)[:40], "symbol": str(sym).upper(), "direction": str(dr).upper(), "entry": en_, "sl": sl_, "tp1": tp_, "tp2": None, "ts": t,
                    "actual_R": _f(rm), "outcome": oc, "status": st})
    return out


CONTROL_CASES = ("AKE", "LONGXIA", "LSK", "ENA")


def run(db: str, printer: Callable[[str], None] = print, getter: Optional[Callable[[str], bytes]] = None) -> Dict[str, Any]:
    """Повний прогін: 4 контрольних кейси + вся історія унікальних планів + журнал угод власниці. Усе — у printer (лог [rr])."""
    import office_replay as RP

    P = lambda s: printer(f"[rr] {s}")  # noqa: E731
    P(f"правило: старе = RR до TP1 ≥ {OLD_MIN_RR:g} після комісій; нове = зважений RR (40% TP1 + 60% TP2, runner=TP2) ≥ {NEW_MIN_WEIGHTED:g} І RR до TP1 ≥ {NEW_MIN_TP1:g}; комісія {fee_pct():.2f}% за круг")
    # 1) контрольні кейси
    for k in CONTROL_CASES:
        c = RP.CASES[k]
        st = datetime.fromisoformat(c["start"].replace("Z", "+00:00")).timestamp()
        ev = evaluate_plan({"symbol": c["symbol"], "direction": c["side"], "entry": c["entry"], "sl": c["sl"], "tp1": c["tp1"], "tp2": c.get("tp2"), "ts": st, "id": k}, getter)
        if ev.get("status") != "OK":
            P(f"кейс {k}: {ev.get('status')}")
            continue
        s = ev["sim"]
        P(f"кейс {k}: ризик {ev['risk_pct']:.2f}% · до TP1 {ev['d1_pct']:.2f}% · TP2 {ev['tp2_src']}"
          f"{' ' + format(ev['tp2'], 'g') + ' (' + format(ev['d2_pct'], '.2f') + '%)' if ev.get('tp2') else ''} · RR до TP1 {ev['rr_tp1']:.2f} · зважений RR {ev['rr_weighted']:.2f} · "
          f"старе {'ПРОЙДЕ' if ev['old'] else 'ВІДХИЛЕНО'} · нове {'ПРОЙДЕ' if ev['new'] else 'ВІДХИЛЕНО'} · симуляція {s.get('status')}"
          f"{' R=' + format(s['R'], '+.2f') if s.get('R') is not None else ''}")
    # 2) вся історія унікальних планів
    plans = load_unique_plans(db)
    P(f"історія планів: унікальних {len(plans)} (із {len(plans)} після зведення службових дублів)")
    evs = []
    for p in plans:
        evs.append(evaluate_plan(p, getter))
        time.sleep(0.05)
    sm = summarize(evs)
    P("історія: " + json.dumps(sm, ensure_ascii=False))
    for name in ("old_pass", "new_pass", "only_new", "only_old", "rejected_by_both"):
        g = sm[name]
        P(f"  {name}: планів {g['n']} · заповнено {g['filled']} · сума R {g['sum_R']:+} · середній R {g['avg_R']} · плюс {g['wins']} / мінус {g['losses']} · не заповнено {g['not_filled']} · без даних {g['no_data']}")
    only_new = [r for r in evs if r.get("status") == "OK" and r["new"] and not r["old"]]
    for r in only_new[:40]:   # плани, які пройшли б лише за новим правилом
        sim = r["sim"] or {}
        P(f"  лише-нове: {r['symbol']} {r['direction']} {datetime.fromtimestamp(r['ts'], tz=timezone.utc):%m-%d %H:%M} · ризик {r['risk_pct']:.2f}% · TP1 {r['d1_pct']:.2f}% · "
          f"TP2 {r['tp2_src']}{' ' + format(r['d2_pct'], '.2f') + '%' if r.get('tp2') else ''} · RR до TP1 {r['rr_tp1']:.2f} · зважений {r['rr_weighted']:.2f} · "
          f"{sim.get('status')}{' R=' + format(sim['R'], '+.2f') if sim.get('R') is not None else ''}")
    # 3) угоди власниці з журналу
    jr = load_journal(db)
    jev = [evaluate_plan(p, getter) for p in jr]
    jsm = summarize(jev)
    acts = [p["actual_R"] for p in jr if p.get("actual_R") is not None]
    P(f"журнал угод власниці: {len(jr)} угод із планом; фактичний R у журналі: {len(acts)} значень, сума {sum(acts):+.2f}, середній {(sum(acts) / len(acts)) if acts else 0:+.2f}")
    P("журнал: " + json.dumps({k: jsm[k] for k in ("usable", "old_pass", "new_pass", "only_new")}, ensure_ascii=False))
    return {"controls": CONTROL_CASES, "history": sm, "journal": jsm}

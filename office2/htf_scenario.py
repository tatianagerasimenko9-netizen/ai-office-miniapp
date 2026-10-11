"""HTF_STRONG_CANDLE_PULLBACK (SHADOW): сильна свічка старшого ТФ → відкат у її область → точний вхід на молодшому ТФ.

Джерело послідовності: опис методики Дарії Жданової від власниці (11.10.2026), docs/strategies/SOURCE_RULES.md. Усе, чого в описі немає, позначено `ГІПОТЕЗА`/`OUR_IMPLEMENTATION`
у кожному доказі (поле `src`) і не видається за правило авторки. Немає даних/підтвердження — `ok=None` («НЕ ПІДТВЕРДЖЕНО»). Лише ЗАКРИТІ бари до `as_of` (без майбутніх).
Один структурний сценарій на одну сильну свічку (scenario_id = HTF|символ|напрям|ТФ|ts свічки). Не торговий сигнал; у LIVE не підключений."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

VERSION = "htf-scp-1"
S_OWNER = "ДЖЕРЕЛО: опис методики Дарії від власниці 11.10.2026"
S_FIB = "ДЖЕРЕЛО: каруселі Дарії (DARIA_ZHDANOVA_METHOD.md п.10)"
S_HYP = "ГІПОТЕЗА (не правило авторки)"
S_OUR = "OUR_IMPLEMENTATION"
FIB_RETRACE = (0.236, 0.382, 0.5, 0.618, 0.786)            # ДЖЕРЕЛО: S_FIB
STRONG = {"vol_sma": 20, "vol_x": 2.0, "atr_period": 14, "range_atr_x": 1.2}   # OUR_IMPLEMENTATION (sc-ours-1): авторська формула не розкрита
SWING_N = 2                                                 # ГІПОТЕЗА: фрактал
RECENT_BARS = {"1d": 10, "4h": 30}                          # ГІПОТЕЗА: скільки останніх барів ТФ вважаємо «свіжою» сильною свічкою
MAX_AGE_BARS = {"1d": 15, "4h": 45}                         # ГІПОТЕЗА: максимальний вік сценарію
TF_SEC = {"1d": 86400, "4h": 14400, "15m": 900, "5m": 300}
TRIGGER_FRESH_BARS = 12                                     # ГІПОТЕЗА: тригер M5 не старший за 1 годину (вимога «не входити після запізнілого руху» без числа в описі)
TRIGGER_BARS = 3                                            # ГІПОТЕЗА: збігається з наявним мікро-підтвердженням Brain (закриття за екстремумом 3 попередніх M5)


def _closed(c: List[Dict[str, Any]], tf: str, as_of: float) -> List[Dict[str, Any]]:
    w = TF_SEC[tf]
    return sorted((b for b in c if b.get("ts") is not None and b["ts"] + w <= as_of), key=lambda b: b["ts"])


def _atr(c: List[Dict[str, Any]], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(c)
    trs = [None] + [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"])) for p, b in zip(c, c[1:])]
    for i in range(n, len(c)):
        out[i] = sum(trs[i - n + 1:i + 1]) / n
    return out


def _sma_vol(c: List[Dict[str, Any]], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(c)
    for i in range(n - 1, len(c)):
        v = [b.get("volume") for b in c[i - n + 1:i + 1]]
        if all(x is not None for x in v):
            out[i] = sum(v) / n
    return out


def strong_candles(c: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    a, vs = _atr(c, STRONG["atr_period"]), _sma_vol(c, STRONG["vol_sma"])
    out = []
    for i, b in enumerate(c):
        if a[i] is None or vs[i] is None or a[i] <= 0 or b.get("volume") is None or b["close"] == b["open"]:
            continue
        if b["volume"] > vs[i] * STRONG["vol_x"] and (b["high"] - b["low"]) > a[i] * STRONG["range_atr_x"]:
            out.append({"i": i, "ts": b["ts"], "direction": "LONG" if b["close"] > b["open"] else "SHORT", "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
                        "body_atr": abs(b["close"] - b["open"]) / a[i], "vol_rel": b["volume"] / vs[i], "atr": a[i]})
    return out


def swings(c: List[Dict[str, Any]], n: int = SWING_N) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """Підтверджені фрактали (потрібні n барів після екстремуму — тобто відомі на момент рішення)."""
    hs, ls = [], []
    for i in range(n, len(c) - n):
        if all(c[i]["high"] > c[i - k]["high"] and c[i]["high"] >= c[i + k]["high"] for k in range(1, n + 1)):
            hs.append((i, c[i]["high"]))
        if all(c[i]["low"] < c[i - k]["low"] and c[i]["low"] <= c[i + k]["low"] for k in range(1, n + 1)):
            ls.append((i, c[i]["low"]))
    return hs, ls


def _ev(step: str, ok: Optional[bool], text: str, src: str, **extra: Any) -> Dict[str, Any]:
    return {"step": step, "ok": ok, "text": text if ok is not None else "НЕ ПІДТВЕРДЖЕНО: " + text, "src": src, **extra}


def _plan(symbol: str, long_: bool, trig: Dict[str, Any], t0: float, c15: List[Dict[str, Any]], c5: List[Dict[str, Any]], hs, ls, h: List[Dict[str, Any]], b_pt) -> Dict[str, Any]:
    """План лише після підтвердженого M5-тригера. Стоп — за структурою (екстремум відкату в області, варіанти office2.stops: ГІПОТЕЗА щодо запасу ATR);
    цілі — зі структури старшого ТФ (максимум/мінімум імпульсу і раніші підтверджені swing-точки), а НЕ за кратністю стопа. Кратності лише інформують."""
    from office2 import stops as SV

    entry = trig["close"]
    since15 = [b for b in c15 if b["ts"] >= t0]
    since5 = [b for b in c5 if b["ts"] >= t0 and b["ts"] <= trig["ts"]]
    lows = [b["low"] for b in since15 + since5] if long_ else [b["high"] for b in since15 + since5]
    extreme = min(lows) if long_ else max(lows)
    a15 = _atr(c15, 14)[-1] or 0.0
    st = SV.finalize_for_entry(SV.variants("LONG" if long_ else "SHORT", extreme, 0.0, a15, [], entry=entry), "LONG" if long_ else "SHORT", entry)
    rec = st.get("recommended")
    if long_:
        tg = sorted({p for i, p in hs if p > entry} | ({h[b_pt[0]]["high"]} if h[b_pt[0]]["high"] > entry else set()))
    else:
        tg = sorted({p for i, p in ls if p < entry} | ({h[b_pt[0]]["low"]} if h[b_pt[0]]["low"] < entry else set()), reverse=True)
    tg = tg[:2]
    sl = st[rec]["sl"] if rec else None
    risk = abs(entry - sl) if sl else None
    return {"entry": entry, "entry_ts": trig["ts"], "stop_extreme": extreme, "stops": st, "recommended_stop": rec, "stop": sl,
            "targets": [{"price": p, "src": "структура старшого ТФ (swing/максимум імпульсу)", "r_info": (abs(p - entry) / risk if risk else None)} for p in tg],
            "would_be_ready": bool(rec and tg and risk and abs(tg[0] - entry) / risk >= 1.0),
            "note": "would_be_ready = є обґрунтований стоп і перша ціль ≥1R (чинний мінімум Brain); це shadow-позначка, не сигнал"}


def evaluate(symbol: str, tf: str, htf: List[Dict[str, Any]], m15: List[Dict[str, Any]], m5: List[Dict[str, Any]], as_of: float, key_levels: Optional[List[float]] = None) -> List[Dict[str, Any]]:
    """Список активних сценаріїв (по одному на сильну свічку й напрям), без майбутніх барів. tf — '1d' або '4h'."""
    h, c15, c5 = _closed(htf, tf, as_of), _closed(m15, "15m", as_of), _closed(m5, "5m", as_of)
    out: List[Dict[str, Any]] = []
    if len(h) < STRONG["vol_sma"] + 5 or not c15:
        return out
    n = len(h)
    seen_dir = set()
    for sc in reversed(strong_candles(h)):
        if n - 1 - sc["i"] > RECENT_BARS[tf] or sc["direction"] in seen_dir:
            continue
        seen_dir.add(sc["direction"])
        long_ = sc["direction"] == "LONG"
        sg = 1.0 if long_ else -1.0
        sid = f"HTF|{symbol}|{sc['direction']}|{tf}|{int(sc['ts'])}"
        ev: List[Dict[str, Any]] = []
        body_lo, body_hi = min(sc["open"], sc["close"]), max(sc["open"], sc["close"])
        ev.append(_ev("сильна свічка старшого ТФ", True, f"{tf.upper()} {_dt(sc['ts'])}: тіло {body_lo:g}–{body_hi:g}, максимум {sc['high']:g}, мінімум {sc['low']:g}, обсяг ×{sc['vol_rel']:.1f}, діапазон/тіло в ATR: {sc['body_atr']:.1f}", S_OUR + "; " + S_OWNER + " (роль кроку)", ts=sc["ts"]))
        hs, ls = swings(h)
        # 2) завершений імпульс і Fibonacci (прив'язка лише до підтверджених swing-точок)
        if long_:
            lows_before = [(i, p) for i, p in ls if i <= sc["i"]]
            highs_after = [(i, p) for i, p in hs if i >= sc["i"]]
            a_pt = lows_before[-1] if lows_before else None
            b_pt = max(highs_after, key=lambda x: x[1]) if highs_after else None
        else:
            highs_before = [(i, p) for i, p in hs if i <= sc["i"]]
            lows_after = [(i, p) for i, p in ls if i >= sc["i"]]
            a_pt = highs_before[-1] if highs_before else None
            b_pt = min(lows_after, key=lambda x: x[1]) if lows_after else None
        state, fib, zone, imp, plan = "NO_IMPULSE", None, None, None, None
        if not a_pt or not b_pt or abs(b_pt[1] - a_pt[1]) <= 0 or b_pt[0] <= a_pt[0]:
            ev.append(_ev("завершений імпульс і Fibonacci", None, "немає підтвердженої пари swing-точок (завершеного імпульсу) — сітку не будуємо", S_OWNER))
        else:
            rng = abs(b_pt[1] - a_pt[1])
            fib = {f"{int(r * 1000) / 10:g}%": b_pt[1] - sg * rng * r for r in FIB_RETRACE}
            imp = {"from": {"price": a_pt[1], "ts": h[a_pt[0]]["ts"]}, "to": {"price": b_pt[1], "ts": h[b_pt[0]]["ts"]}}
            ev.append(_ev("завершений імпульс і Fibonacci", True, f"імпульс {a_pt[1]:g} ({_dt(h[a_pt[0]]['ts'])}) → {b_pt[1]:g} ({_dt(h[b_pt[0]]['ts'])}); рівні відкату: " + ", ".join(f"{k} {v:g}" for k, v in fib.items()),
                          S_FIB + "; точки — " + S_HYP + " (фрактал)", anchors=imp))
            # 3) збіги
            inside = {k: v for k, v in fib.items() if body_lo <= v <= body_hi}
            lv = [x for x in (key_levels or []) if body_lo <= x <= body_hi]
            conf = [f"Fibonacci {k} = {v:g} у тілі свічки" for k, v in inside.items()] + [f"рівень {x:g} у тілі свічки" for x in lv]
            ev.append(_ev("збіг області свічки з Fibonacci/рівнями", True if conf else None, "; ".join(conf) if conf else "збігів тіла свічки з Fibonacci-рівнями чи ключовими рівнями не знайдено — збіг не вигадуємо", S_OWNER))
            zone = [body_lo, body_hi]                                  # ГІПОТЕЗА: «область» = тіло сильної свічки
            # 4) відкат
            last = c15[-1]["close"]
            after = [b for b in h[b_pt[0] + 1:]]
            age = n - 1 - b_pt[0]
            lost = any((b["close"] < sc["low"]) if long_ else (b["close"] > sc["high"]) for b in after) or ((last < sc["low"]) if long_ else (last > sc["high"]))
            if lost:
                state = "INVALIDATED"
                ev.append(_ev("актуальність сильної свічки", False, f"закриття за протилежним краєм свічки ({sc['low' if long_ else 'high']:g}) — сценарій скасовано", S_HYP + " (умова втрати сили в описі без числа)"))
            elif age > MAX_AGE_BARS[tf]:
                state = "STALE"
                ev.append(_ev("актуальність сильної свічки", False, f"імпульс завершився {age} барів {tf.upper()} тому — сценарій застарів", S_HYP))
            else:
                touched = [b for b in c15 if b["ts"] >= h[b_pt[0]]["ts"] and ((b["low"] <= body_hi) if long_ else (b["high"] >= body_lo))]
                depth = abs(b_pt[1] - last) / rng
                ev.append(_ev("відкат", True if touched else None,
                              (f"ціна {last:g} повернулась в область {body_lo:g}–{body_hi:g}; глибина відкату {depth * 100:.0f}% імпульсу" if touched else f"ціна {last:g} ще не повернулась в область {body_lo:g}–{body_hi:g} (глибина {depth * 100:.0f}% імпульсу)"),
                              S_OWNER + "; характер відкату (затухання/ретест/зняття ліквідності) — НЕ ПІДТВЕРДЖЕНО автоматично", depth=depth))
                state = "IN_ZONE" if touched else "WAIT_PULLBACK"
                if touched:
                    t0 = touched[0]["ts"]
                    # 5) молодший тригер (M5): після дотику зони
                    c5a = [b for b in c5 if b["ts"] >= t0]
                    trig, why_not = None, "після входу в область закриття M5 за екстремумом 3 попередніх барів ще немає"
                    for k in range(TRIGGER_BARS, len(c5a)):
                        win = c5a[k - TRIGGER_BARS:k]
                        brk = (c5a[k]["close"] > max(x["high"] for x in win)) if long_ else (c5a[k]["close"] < min(x["low"] for x in win))
                        if not brk:
                            continue
                        in_area = (c5a[k]["close"] <= body_hi) if long_ else (c5a[k]["close"] >= body_lo)      # реакція в старшій області, а не погоня за рухом
                        fresh = len(c5a) - 1 - k <= TRIGGER_FRESH_BARS                                          # не входити після запізнілого руху
                        if in_area and fresh:
                            trig = c5a[k]
                        elif not in_area:
                            why_not = "M5-пробій був, але закриття вже поза старшою областю — запізно, не погоня за рухом"
                        elif not fresh:
                            why_not = f"M5-пробій був понад {TRIGGER_FRESH_BARS} барів M5 тому — застарів"
                    if trig:
                        state = "TRIGGERED"
                        plan = _plan(symbol, long_, trig, t0, c15, c5, hs, ls, h, b_pt)
                        ev.append(_ev("точка входу на M5", True, f"M5 {_dt(trig['ts'])}: закриття {trig['close']:g} {'вище максимуму' if long_ else 'нижче мінімуму'} {TRIGGER_BARS} попередніх барів після входу в область", S_HYP + " (мікро-підтвердження як у Brain)", ts=trig["ts"]))
                    else:
                        ev.append(_ev("точка входу на M5", None, why_not, S_HYP))
        out.append({"v": VERSION, "scenario_id": sid, "symbol": symbol, "direction": sc["direction"], "tf": tf, "strong_ts": sc["ts"], "state": state, "as_of": as_of,
                    "zone": zone, "fib": fib, "impulse": imp, "evidence": ev, "plan": plan, "src_note": "shadow; один сценарій на сильну свічку; параметри з позначкою ГІПОТЕЗА не є правилами авторки"})
    return out


def _dt(ts: Any) -> str:
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(float(ts), ZoneInfo("Europe/Kyiv")).strftime("%d.%m %H:%M")
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ shadow-запис (БД) і прохід по universe
DDL = ("""CREATE TABLE IF NOT EXISTS office2_htf_shadow (
    scenario_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, tf TEXT NOT NULL, strong_ts DOUBLE PRECISION, state TEXT,
    first_seen_ts DOUBLE PRECISION, updated_ts DOUBLE PRECISION, trigger_ts DOUBLE PRECISION, would_be_ready INTEGER DEFAULT 0,
    evidence_json TEXT, plan_json TEXT, state_history TEXT, version TEXT)""",)
_READY: set = set()


def _ensure(db: str) -> None:
    if db in _READY:
        return
    from office_bridge import _execute

    for d in DDL:
        _execute(db, d)
    _READY.add(db)


def record(db: str, scen: Dict[str, Any], now: float) -> str:
    """Upsert одного сценарію; історія змін стану зберігається (стан → час). Повертає 'new'/'changed'/'same'."""
    import json

    from office_bridge import _execute, _fetchall

    _ensure(db)
    ex = _fetchall(db, "SELECT state, state_history FROM office2_htf_shadow WHERE scenario_id = ?", (scen["scenario_id"],))
    plan = scen.get("plan")
    trig = next((e.get("ts") for e in scen["evidence"] if e["step"].startswith("точка входу") and e.get("ok")), None)
    ej, pj = json.dumps(scen["evidence"], ensure_ascii=False), json.dumps(plan, ensure_ascii=False) if plan else None
    if not ex:
        _execute(db, "INSERT INTO office2_htf_shadow(scenario_id, symbol, direction, tf, strong_ts, state, first_seen_ts, updated_ts, trigger_ts, would_be_ready, evidence_json, plan_json, state_history, version) "
                     "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (scenario_id) DO NOTHING",
                 (scen["scenario_id"], scen["symbol"], scen["direction"], scen["tf"], scen["strong_ts"], scen["state"], now, now, trig, 1 if plan and plan.get("would_be_ready") else 0, ej, pj,
                  json.dumps([[scen["state"], now]]), VERSION))
        return "new"
    old, hist = ex[0]
    h = json.loads(hist or "[]")
    changed = old != scen["state"]
    if changed:
        h.append([scen["state"], now])
    _execute(db, "UPDATE office2_htf_shadow SET state=?, updated_ts=?, trigger_ts=COALESCE(trigger_ts, ?), would_be_ready=?, evidence_json=?, plan_json=COALESCE(plan_json, ?), state_history=? WHERE scenario_id=?",
             (scen["state"], now, trig, 1 if plan and plan.get("would_be_ready") else 0, ej, pj, json.dumps(h), scen["scenario_id"]))
    return "changed" if changed else "same"


def run_once(db: str, fetch: Any, symbols: List[str], now: float, log: Any = print) -> Dict[str, int]:
    """Один прохід: свічки D1/H4/M15/M5 з наявного кешу Binance (fetch(symbol, tf, limit)), сценарії → shadow-таблиця. Ордерів і Telegram немає."""
    import office_signal_track as T

    def cl(sym: str, tf: str, lim: int) -> List[Dict[str, Any]]:
        rows = fetch(sym, tf, lim)
        out = []
        for b in rows if isinstance(rows, list) else []:
            t = T._ts(b.get("ts")) if isinstance(b, dict) else None
            if t is not None:
                out.append(dict(b, ts=t))
        return out

    res = {"symbols": 0, "new": 0, "changed": 0, "errors": 0}
    for sym in symbols:
        try:
            d1, h4, m15, m5 = cl(sym, "1d", 120), cl(sym, "4h", 200), cl(sym, "15m", 300), cl(sym, "5m", 300)
            res["symbols"] += 1
            for tf, htf in (("1d", d1), ("4h", h4)):
                for sc in evaluate(sym, tf, htf, m15, m5, now):
                    r = record(db, sc, now)
                    if r == "new":
                        res["new"] += 1
                    elif r == "changed":
                        res["changed"] += 1
        except Exception as exc:  # noqa: BLE001
            res["errors"] += 1
            log(f"[htf] {sym}: {type(exc).__name__}: {str(exc)[:100]}")
    return res


def summary(db: str, limit: int = 40, now: Optional[float] = None) -> Dict[str, Any]:
    """Для Mini App: активні й нещодавні shadow-сценарії з доказами (кожен з позначкою джерела/гіпотези) і станом. Не торгові сигнали."""
    import json
    import time

    from office_bridge import _fetchall, office_db_identity

    out: Dict[str, Any] = {"ok": True, "version": VERSION, "items": [], "note": "SHADOW: спостереження за сценарієм «сильна свічка старшого ТФ → відкат → вхід на молодшому ТФ»; не сигнал, у LIVE не підключено. Позначки ГІПОТЕЗА — не правила авторки."}
    try:
        idn = office_db_identity(db)
        out["db"] = {"backend": idn.get("backend"), "fingerprint": idn.get("fingerprint")}
        _ensure(db)
        rows = _fetchall(db, "SELECT scenario_id, symbol, direction, tf, strong_ts, state, first_seen_ts, updated_ts, trigger_ts, would_be_ready, evidence_json, plan_json, state_history FROM office2_htf_shadow "
                             "WHERE updated_ts > ? ORDER BY CASE state WHEN 'TRIGGERED' THEN 0 WHEN 'IN_ZONE' THEN 1 WHEN 'WAIT_PULLBACK' THEN 2 ELSE 3 END, updated_ts DESC LIMIT ?", ((time.time() if now is None else now) - 3 * 86400, limit))
        names = ("scenario_id", "symbol", "direction", "tf", "strong_ts", "state", "first_seen_ts", "updated_ts", "trigger_ts", "would_be_ready", "evidence_json", "plan_json", "state_history")
        for r in rows:
            d = dict(zip(names, r))
            d["evidence"], d["plan"], d["history"] = json.loads(d.pop("evidence_json") or "[]"), json.loads(d.pop("plan_json") or "null"), json.loads(d.pop("state_history") or "[]")
            out["items"].append(d)
        cnt = _fetchall(db, "SELECT state, COUNT(*) FROM office2_htf_shadow GROUP BY state")
        out["counts"] = {a: b for a, b in cnt}
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out

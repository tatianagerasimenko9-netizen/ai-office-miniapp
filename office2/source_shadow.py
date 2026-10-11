"""SOURCE_SHADOW: спостерігачі за числовими правилами, які ЯВНО є у першоджерелах (docs/sources/evidence.jsonl). Лише shadow; у LIVE/Telegram не підключено.

Два незалежні детектори (кожен з версією й rule_id; один сценарій = один id):
  * GERCHIK_PARANORMAL (G-ATR-CALC, G-LVL-PARANORMAL): денний бар D1 з діапазоном ≥ 2× ATR за формулою Герчика (3–5 попередніх D1 без паранормальних).
  * DARIA_POST_IMPULSE_BASE (D-POST-IMPULSE-BASE, D-PARANORMAL-IMPULSE): після паранормального бару — база без нормального відкату; частка відкату імпульсу, положення в третині, тривалість бази в днях D1 (класи з джерела).

Що саме з джерела, а що наше — у полі `src` кожного доказу: `ДЖЕРЕЛО <rule_id>` або `ГІПОТЕЗА` (наше припущення вимірювання). Немає даних/неоднозначно — `ok=None` («НЕ ПІДТВЕРДЖЕНО»).
Лише ЗАКРИТІ D1-бари з ts+86400 ≤ as_of (без поточного дня, без майбутніх). Не торговий сигнал: ні входу, ні SL, ні TP."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

VERSION = "src-shadow-1"
DAY = 86400.0
ATR_BARS = 5                        # ДЖЕРЕЛО G-ATR-CALC: «3–5» попередніх D1 (береться верхня межа; джерело дозволяє 3–5)
PARANORMAL_X = 2.0                  # ДЖЕРЕЛО G-LVL-PARANORMAL / D-PARANORMAL-IMPULSE: розмір ≥ 2× середнього
SMALL_X = 1.0 / 3.0                 # ДЖЕРЕЛО G-ATR-CALC: бари ≤ 1/3 ATR теж не враховуються в ATR
BASE_DAYS = ((0, 1, "ШУМ", "0–1 день: сценарій ще не ясен"), (2, 7, "ОПТИМУМ", "2–7 днів: оптимальна зона"), (8, 20, "ГЛИБОКА", "7–20 днів: ймовірність продовження лишається, але знижується"))   # ДЖЕРЕЛО D-POST-IMPULSE-BASE (слайд #200)
STALE_DAYS = 20                     # ДЖЕРЕЛО: «20+ днів — сценарій втрачає актуальність»
MAX_RETRACE = 0.5                   # ДЖЕРЕЛО D-POST-IMPULSE-BASE (#201): «повертає більше половини імпульсу» — сценарій неактуальний
THIRD = 1.0 / 3.0                   # ДЖЕРЕЛО (#197–199): база в нижній/верхній третині імпульсу
LOOKBACK_IMPULSE_DAYS = 30          # ГІПОТЕЗА: скільки останніх D1 переглядаємо в пошуку паранормального бару (стеля 20+ днів бази + запас)
S_SRC = "ДЖЕРЕЛО"
S_HYP = "ГІПОТЕЗА (наше припущення вимірювання, не правило джерела)"


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def closed_d1(daily: List[Dict[str, Any]], as_of: float) -> List[Dict[str, Any]]:
    """Закриті D1-бари до as_of (ts — початок доби, epoch сек); відсортовані, без дублікатів."""
    seen: Dict[float, Dict[str, Any]] = {}
    for b in daily or []:
        t = _num(b.get("ts"))
        h, l, o, c = (_num(b.get(k)) for k in ("high", "low", "open", "close"))
        if t is None or None in (h, l, o, c) or h < l or t + DAY > as_of:
            continue
        seen[t] = {"ts": t, "open": o, "high": h, "low": l, "close": c}
    return [seen[k] for k in sorted(seen)]


def true_range(bars: List[Dict[str, Any]], i: int) -> float:
    """high−low; гап до попереднього закриття враховуємо (Герчик: «гап з'їдає частину ATR»). ГІПОТЕЗА: гап через true range."""
    b = bars[i]
    if i == 0:
        return b["high"] - b["low"]
    pc = bars[i - 1]["close"]
    return max(b["high"], pc) - min(b["low"], pc)


def gerchik_atr(bars: List[Dict[str, Any]], end: int, n: int = ATR_BARS) -> Optional[Dict[str, Any]]:
    """ATR за Герчиком (G-ATR-CALC) на барах [..end) — сам бар `end` НЕ входить. Паранормальні (≥2×ATR, ≤1/3 ATR) замінюються сусідніми (старішими).
    Початкова оцінка для відсікання — медіана n останніх діапазонів (ГІПОТЕЗА: у книзі порядок першої оцінки не заданий)."""
    if end < 3:
        return None
    rng = [true_range(bars, i) for i in range(max(0, end - 4 * n), end)]    # ГІПОТЕЗА: вікно пошуку замінників — 4·n барів
    recent = sorted(rng[-n:])
    if not recent:
        return None
    base0 = recent[len(recent) // 2]
    if base0 <= 0:
        return None
    kept: List[float] = []
    for r in reversed(rng):
        if r >= PARANORMAL_X * base0 or r <= SMALL_X * base0:
            continue
        kept.append(r)
        if len(kept) >= n:
            break
    if len(kept) < 3:
        return None
    return {"atr": sum(kept) / len(kept), "bars_used": len(kept), "base0": base0}


def paranormal_bars(bars: List[Dict[str, Any]], last_n: int = LOOKBACK_IMPULSE_DAYS) -> List[Dict[str, Any]]:
    """Бари з діапазоном ≥ 2× ATR(Герчика) за попередні бари; лише серед останніх last_n закритих D1."""
    out: List[Dict[str, Any]] = []
    start = max(3, len(bars) - last_n)
    for i in range(start, len(bars)):
        a = gerchik_atr(bars, i)
        if not a:
            continue
        rng = true_range(bars, i)
        if rng >= PARANORMAL_X * a["atr"]:
            b = bars[i]
            out.append({"i": i, "ts": b["ts"], "direction": "DOWN" if b["close"] < b["open"] else "UP", "range": rng, "atr": a["atr"], "x_atr": rng / a["atr"], "high": b["high"], "low": b["low"], "open": b["open"], "close": b["close"]})
    return out


def _ev(step: str, ok: Optional[bool], text: str, src: str, **kw: Any) -> Dict[str, Any]:
    d = {"step": step, "ok": ok, "text": text if ok is not None else f"НЕ ПІДТВЕРДЖЕНО: {text}", "src": src}
    d.update({k: v for k, v in kw.items() if v is not None})
    return d


def _dt(ts: float) -> str:
    import datetime as _d

    return _d.datetime.utcfromtimestamp(ts).strftime("%d.%m.%Y")


def paranormal_scenarios(symbol: str, daily: List[Dict[str, Any]], as_of: float) -> List[Dict[str, Any]]:
    bars = closed_d1(daily, as_of)
    out = []
    for p in paranormal_bars(bars):
        age = len(bars) - 1 - p["i"]
        out.append({"scenario_id": f"GPB|{symbol}|{int(p['ts'])}", "kind": "GERCHIK_PARANORMAL", "symbol": symbol, "direction": p["direction"], "tf": "1d", "anchor_ts": p["ts"],
                    "state": "RECENT" if age <= 1 else "KNOWN", "rule_ids": ["G-ATR-CALC", "G-LVL-PARANORMAL"],
                    "evidence": [_ev("паранормальний бар D1", True, f"{_dt(p['ts'])}: діапазон {p['range']:.6g} = {p['x_atr']:.1f}× ATR({p['atr']:.6g}); напрям {'вниз' if p['direction']=='DOWN' else 'вгору'}", f"{S_SRC} G-LVL-PARANORMAL (≥2× середнього); ATR — {S_SRC} G-ATR-CALC; гап через true range — {S_HYP}", ts=p["ts"]),
                                 _ev("рівні паранормального бару", None, "джерело: обидва кінці бару можуть створювати рівень лише з підтвердженням дотиками/хибними пробоями — підтвердження не вимірюємо", f"{S_SRC} G-LVL-PARANORMAL")]})
    return out


def base_state(p: Dict[str, Any], after: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Стан бази після паранормального бару p за закритими барами `after` (лише після p). Чисто, без БД; використовується й у replay."""
    days = len(after)
    rng = p["high"] - p["low"]
    down = p["direction"] == "DOWN"
    ev: List[Dict[str, Any]] = [
        _ev("паранормальний рух (варіант A: один бар)", True, f"{_dt(p['ts'])}: {p['x_atr']:.1f}× ATR; {'падіння' if down else 'зростання'}", f"{S_SRC} D-PARANORMAL-IMPULSE (>2 ATR; один величезний бар)", ts=p["ts"]),
        _ev("паранормальний рух (варіант B: серія барів)", None, "джерело наводить серію односпрямованих барів без кількісного критерію — не формалізовано", f"{S_SRC} D-PARANORMAL-IMPULSE")]
    out: Dict[str, Any] = {"state": "NO_BASE_YET", "evidence": ev, "days": days, "retrace": None, "third_ok": None}
    if days == 0 or rng <= 0:
        ev.append(_ev("база після імпульсу", None, "після паранормального бару ще немає закритого D1", f"{S_SRC} D-POST-IMPULSE-BASE"))
        return out
    if down:
        base_edge = max(b["high"] for b in after)
        retrace = (base_edge - p["low"]) / rng
        third_ok = base_edge <= p["low"] + THIRD * rng
    else:
        base_edge = min(b["low"] for b in after)
        retrace = (p["high"] - base_edge) / rng
        third_ok = base_edge >= p["high"] - THIRD * rng
    retrace = max(0.0, retrace)
    cls = next((n for lo, hi, n, _ in BASE_DAYS if lo <= days <= hi), None)
    note = next((t for lo, hi, n, t in BASE_DAYS if lo <= days <= hi), "")
    if days > STALE_DAYS:
        cls, note = "ЗАСТАРІЛО", "20+ днів: сценарій втрачає актуальність"
    ev.append(_ev("відкат імпульсу", retrace <= MAX_RETRACE, f"база повернула {retrace*100:.0f}% діапазону імпульсу (межа з джерела: більше половини — сценарій неактуальний)",
                  f"{S_SRC} D-POST-IMPULSE-BASE (>50% = інвалідація); вимір відкату через діапазон одного бару — {S_HYP}", depth=retrace))
    ev.append(_ev("база в потрібній третині", third_ok, f"база {'не вище нижньої' if down else 'не нижче верхньої'} третини імпульсу: {'так' if third_ok else 'ні'} (край бази {base_edge:.6g})",
                  f"{S_SRC} D-POST-IMPULSE-BASE (нижня/верхня третина)"))
    ev.append(_ev("тривалість бази", True, f"{days} дн. D1: {note}", f"{S_SRC} D-POST-IMPULSE-BASE (слайд: 0–1 / 2–7 / 7–20 / 20+ днів)", days=days))
    ev.append(_ev("краї бази й напрям продовження", None, "у джерелі неоднозначно, який край бази підтверджує продовження — не вимірюємо", f"{S_SRC} D-POST-IMPULSE-BASE (п.7–8 чек-листа)"))
    if retrace > MAX_RETRACE:
        state = "INVALIDATED"
    elif days > STALE_DAYS:
        state = "STALE"
    elif cls == "ШУМ":
        state = "BASE_NOISE"
    elif cls == "ОПТИМУМ":
        state = "BASE_OPTIMAL" if third_ok else "BASE_OFF_THIRD"
    else:
        state = "BASE_EXTENDED" if third_ok else "BASE_OFF_THIRD"
    out.update(state=state, retrace=retrace, third_ok=third_ok)
    return out


def base_scenarios(symbol: str, daily: List[Dict[str, Any]], as_of: float) -> List[Dict[str, Any]]:
    """Для кожного паранормального бару (варіант A «один величезний бар») — база після нього."""
    bars = closed_d1(daily, as_of)
    out = []
    for p in paranormal_bars(bars):
        if p["high"] - p["low"] <= 0:
            continue
        st = base_state(p, bars[p["i"] + 1:])
        out.append({"scenario_id": f"DPB|{symbol}|{int(p['ts'])}", "kind": "DARIA_POST_IMPULSE_BASE", "symbol": symbol, "direction": "DOWN_BASE" if p["direction"] == "DOWN" else "UP_BASE", "tf": "1d", "anchor_ts": p["ts"],
                    "state": st["state"], "rule_ids": ["D-POST-IMPULSE-BASE", "D-PARANORMAL-IMPULSE"], "evidence": st["evidence"]})
    return out


def evaluate(symbol: str, daily: List[Dict[str, Any]], as_of: float) -> List[Dict[str, Any]]:
    return paranormal_scenarios(symbol, daily, as_of) + base_scenarios(symbol, daily, as_of)


# ------------------------------------------------------------------ shadow-запис (БД) і прохід по universe
DDL = ("""CREATE TABLE IF NOT EXISTS office2_source_shadow (
    scenario_id TEXT PRIMARY KEY, kind TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT, tf TEXT, anchor_ts DOUBLE PRECISION, state TEXT,
    first_seen_ts DOUBLE PRECISION, updated_ts DOUBLE PRECISION, rule_ids TEXT, evidence_json TEXT, state_history TEXT, version TEXT)""",)
_READY: set = set()


def _ensure(db: str) -> None:
    if db in _READY:
        return
    from office_bridge import _execute

    for d in DDL:
        _execute(db, d)
    _READY.add(db)


def record(db: str, sc: Dict[str, Any], now: float) -> str:
    from office_bridge import _execute, _fetchall

    _ensure(db)
    ex = _fetchall(db, "SELECT state, state_history FROM office2_source_shadow WHERE scenario_id = ?", (sc["scenario_id"],))
    ej = json.dumps(sc["evidence"], ensure_ascii=False)
    if not ex:
        _execute(db, "INSERT INTO office2_source_shadow(scenario_id, kind, symbol, direction, tf, anchor_ts, state, first_seen_ts, updated_ts, rule_ids, evidence_json, state_history, version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (scenario_id) DO NOTHING",
                 (sc["scenario_id"], sc["kind"], sc["symbol"], sc["direction"], sc["tf"], sc["anchor_ts"], sc["state"], now, now, ",".join(sc["rule_ids"]), ej, json.dumps([[sc["state"], now]]), VERSION))
        return "new"
    old, hist = ex[0]
    h = json.loads(hist or "[]")
    changed = old != sc["state"]
    if changed:
        h.append([sc["state"], now])
    _execute(db, "UPDATE office2_source_shadow SET state=?, updated_ts=?, evidence_json=?, state_history=? WHERE scenario_id=?", (sc["state"], now, ej, json.dumps(h), sc["scenario_id"]))
    return "changed" if changed else "same"


def run_once(db: str, fetch: Any, symbols: List[str], now: float, log: Any = print) -> Dict[str, int]:
    import office_signal_track as T

    res = {"symbols": 0, "new": 0, "changed": 0, "errors": 0}
    for sym in symbols:
        try:
            rows = fetch(sym, "1d", 120)
            d1 = []
            for b in rows if isinstance(rows, list) else []:
                t = T._ts(b.get("ts")) if isinstance(b, dict) else None
                if t is not None:
                    d1.append(dict(b, ts=t))
            res["symbols"] += 1
            for sc in evaluate(sym, d1, now):
                r = record(db, sc, now)
                if r in ("new", "changed"):
                    res[r] += 1
        except Exception as exc:  # noqa: BLE001
            res["errors"] += 1
            log(f"[srcshadow] {sym}: {type(exc).__name__}: {str(exc)[:100]}")
    return res


def summary(db: str, limit: int = 60, now: Optional[float] = None) -> Dict[str, Any]:
    import time

    from office_bridge import _fetchall, office_db_identity

    out: Dict[str, Any] = {"ok": True, "version": VERSION, "items": [], "note": "SHADOW: спостереження за числовими правилами з першоджерел (docs/sources/evidence.jsonl). Це не сигнал, у LIVE не підключено; ефект на ринку НЕ ДОВЕДЕНО."}
    try:
        idn = office_db_identity(db)
        out["db"] = {"backend": idn.get("backend"), "fingerprint": idn.get("fingerprint")}
        _ensure(db)
        rows = _fetchall(db, "SELECT scenario_id, kind, symbol, direction, tf, anchor_ts, state, first_seen_ts, updated_ts, rule_ids, evidence_json, state_history FROM office2_source_shadow WHERE updated_ts > ? ORDER BY updated_ts DESC LIMIT ?",
                         ((time.time() if now is None else now) - 3 * 86400, limit))
        names = ("scenario_id", "kind", "symbol", "direction", "tf", "anchor_ts", "state", "first_seen_ts", "updated_ts", "rule_ids", "evidence_json", "state_history")
        for r in rows:
            d = dict(zip(names, r))
            d["evidence"], d["history"] = json.loads(d.pop("evidence_json") or "[]"), json.loads(d.pop("state_history") or "[]")
            d["rule_ids"] = (d["rule_ids"] or "").split(",")
            out["items"].append(d)
        out["counts"] = {f"{a}:{b}": c for a, b, c in _fetchall(db, "SELECT kind, state, COUNT(*) FROM office2_source_shadow GROUP BY kind, state")}
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out

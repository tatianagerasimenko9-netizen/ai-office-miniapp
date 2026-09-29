"""Рушій збігів зони + підтвердження на молодшому ТФ.

Правила з ICT SMC HUNTER / PUMP-DUMP Pine і ядра Булковскі. Нічого не вигадуємо.
Пробій ренджу — подія, не вхід. Менше 2 збігів — лише БД.
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5. Не ордер.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from office_radar import detect_sweep_from_candles
from office_range_radar import classify_range_event, detect_range_bounds
from office_trade_steer import _bars, _f, last_strong_candle, plan_strong_candle_ote

OTE_LO = 0.618
OTE_HI = 0.786
OVERLAP_PCT = 0.35
GRADE_A = 3
GRADE_B = 2
TTL_H1_SEC = 12 * 3600
TTL_M15_SEC = 3 * 3600

# Живі сетапи в процесі: ключ монета+напрям+зона.
_LIVE: Dict[str, Dict[str, Any]] = {}
_DB_ONLY: Dict[str, float] = {}

TAG_UA = {
    "sc_ote": "сильна свічка",
    "ob": "OB",
    "breaker": "брейкер",
    "fib_h4": "Фібо H4",
    "dw": "рівень D/W",
    "mirror": "дзеркало",
    "range_edge": "межа боковика",
    "sweep": "свіп ліквідності",
    "bpr": "BPR",
}

CONFIRM_UA = {
    "double_top": "подвійна вершина",
    "double_bottom": "подвійне дно",
    "triple_top": "потрійна вершина",
    "triple_bottom": "потрійне дно",
    "sfp": "SFP",
    "engulf": "поглинання",
    "bos": "BOS",
    "choch": "CHOCH",
    "spring": "Wyckoff spring",
    "upthrust": "Wyckoff upthrust",
}


def setup_key(*, symbol: str, direction: str, zone_lo: Any, zone_hi: Any) -> str:
    lo, hi = _f(zone_lo), _f(zone_hi)
    if lo is None:
        lo = 0.0
    if hi is None:
        hi = lo
    if lo > hi:
        lo, hi = hi, lo
    return f"{str(symbol or '').upper()}|{str(direction or '').upper()}|{lo:.6g}|{hi:.6g}"


def confirm_timeframe(setup_tf: str) -> str:
    tf = str(setup_tf or "M15").upper()
    if tf in ("H1", "1H", "H4", "4H", "D1", "1D"):
        return "M15"
    return "M5"


def ttl_sec(setup_tf: str) -> int:
    tf = str(setup_tf or "M15").upper()
    if tf in ("H1", "1H", "H4", "4H", "D1", "1D"):
        return TTL_H1_SEC
    return TTL_M15_SEC


def kind_ua(setup_type: str, direction: str) -> str:
    """Тип українською. Слово range заборонене на картці."""
    side = "Лонг" if str(direction or "").upper() == "LONG" else "Шорт"
    raw = str(setup_type or "").strip()
    ul = raw.upper()
    if "СИЛЬН" in raw or "HUNTER" in ul or "SC-OTE" in ul or "SC_OTE" in ul:
        return "Відкат у сильну свічку"
    if ul in ("ЛЕВ", "LEV", "LEV_ANALYST"):
        return f"{side} Лева"
    if ul in ("DUMP", "PUMP") or "PUMP" in ul or "DUMP" in ul:
        return f"{side} на відкаті"
    if "РАДАР" in ul or ul == "RADAR":
        return "Рівень зі старшого ТФ"
    if "BOUNCE" in ul or "ВІДСКІК" in ul:
        return "Відскік від межі"
    if "RANGE" in ul or "РЕНДЖ" in ul or "БОКОВ" in ul:
        return "Відскік від межі"
    if raw and "range" not in raw.lower():
        return raw.replace("_", " ")[:40]
    return f"{side} на відкаті"


def _overlap(a_lo: float, a_hi: float, b_lo: float, b_hi: float) -> bool:
    if a_lo > a_hi:
        a_lo, a_hi = a_hi, a_lo
    if b_lo > b_hi:
        b_lo, b_hi = b_hi, b_lo
    mid = (min(a_hi, b_hi) + max(a_lo, b_lo)) / 2.0
    if mid <= 0:
        return False
    # Інтервали перетинаються або центри ближчі за OVERLAP_PCT.
    if a_hi >= b_lo and b_hi >= a_lo:
        return True
    ca, cb = (a_lo + a_hi) / 2.0, (b_lo + b_hi) / 2.0
    return abs(ca - cb) / mid * 100.0 <= OVERLAP_PCT


def _cand(
    tag: str,
    lo: Any,
    hi: Any,
    *,
    tf: str,
    label: str,
    origin_ts: str = "",
    why: str = "",
) -> Optional[Dict[str, Any]]:
    a, b = _f(lo), _f(hi)
    if a is None and b is None:
        return None
    if a is None:
        a = b
    if b is None:
        b = a
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    if a > b:
        a, b = b, a
    out = {
        "tag": tag,
        "lo": float(a),
        "hi": float(b),
        "tf": tf,
        "label": label,
        "why": why or label,
        "fresh": True,
    }
    if origin_ts:
        out["origin_ts"] = origin_ts
    return out


def _fvgs(rows: List[Dict[str, Any]]) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """Бичачий: low[i] > high[i-2]; ведмежий: high[i] < low[i-2]. Як 3-свічковий FVG Pine."""
    bull: List[Tuple[float, float]] = []
    bear: List[Tuple[float, float]] = []
    if len(rows) < 3:
        return bull, bear
    for i in range(2, len(rows)):
        a, c = rows[i - 2], rows[i]
        if float(c["low"]) > float(a["high"]):
            bull.append((float(a["high"]), float(c["low"])))
        if float(c["high"]) < float(a["low"]):
            bear.append((float(c["high"]), float(a["low"])))
    return bull, bear


def _last_ob(rows: List[Dict[str, Any]], *, direction: str) -> Optional[Tuple[float, float, str]]:
    """Останній ордер-блок / брейкер: свічка проти імпульсу, яку пробили."""
    side = str(direction or "").upper()
    if len(rows) < 4:
        return None
    for i in range(len(rows) - 2, 1, -1):
        b = rows[i]
        nxt = rows[i + 1]
        ts = str(b.get("ts") or "")
        if side == "LONG":
            if float(b["close"]) < float(b["open"]) and float(nxt["close"]) > float(b["high"]):
                return float(b["low"]), float(b["high"]), ts
        else:
            if float(b["close"]) > float(b["open"]) and float(nxt["close"]) < float(b["low"]):
                return float(b["low"]), float(b["high"]), ts
    return None


def _swing_hi_lo(rows: List[Dict[str, Any]], lookback: int = 20) -> Optional[Tuple[float, float]]:
    window = rows[-max(5, lookback) :]
    if len(window) < 5:
        return None
    return max(r["high"] for r in window), min(r["low"] for r in window)


def _fib_zone(hi: float, lo: float, *, direction: str) -> Optional[Tuple[float, float]]:
    span = hi - lo
    if span <= 0:
        return None
    side = str(direction or "").upper()
    if side == "LONG":
        return hi - span * OTE_HI, hi - span * OTE_LO
    return lo + span * OTE_LO, lo + span * OTE_HI


def collect_zone_candidates(
    *,
    direction: str,
    candles_m15: Any = None,
    candles_h1: Any = None,
    candles_h4: Any = None,
    candles_d1: Any = None,
    candles_w: Any = None,
) -> List[Dict[str, Any]]:
    """Кандидати старшого ТФ. Порожні свічки — просто немає тега."""
    side = str(direction or "").upper()
    m15 = _bars(candles_m15)
    h1 = _bars(candles_h1)
    h4 = _bars(candles_h4)
    d1 = _bars(candles_d1)
    w1 = _bars(candles_w)
    out: List[Dict[str, Any]] = []

    sc_src = m15 if len(m15) >= 22 else h1
    sc_tf = "M15" if len(m15) >= 22 else "H1"
    sc = last_strong_candle(sc_src, direction=side)
    if sc:
        plan = plan_strong_candle_ote(direction=side, candles=sc_src)
        if plan.get("data_status") == "DATA_OK":
            c = _cand(
                "sc_ote",
                plan.get("ote_lo"),
                plan.get("ote_hi"),
                tf=sc_tf,
                label=f"сильна свічка {sc_tf}",
                origin_ts=str(sc.get("ts") or ""),
                why="імпульс: обсяг×2 SMA і діапазон > ATR×1.2, тіло в бік сетапу",
            )
            if c:
                out.append(c)

    ob_src = h1 if len(h1) >= 6 else m15
    ob = _last_ob(ob_src, direction=side)
    if ob:
        c = _cand(
            "ob",
            ob[0],
            ob[1],
            tf="H1" if len(h1) >= 6 else "M15",
            label="OB H1" if len(h1) >= 6 else "OB",
            origin_ts=ob[2],
            why="свічка проти імпульсу, яку наступна пробила",
        )
        if c:
            out.append(c)

    hi_lo = _swing_hi_lo(h4 if len(h4) >= 8 else h1)
    if hi_lo:
        fz = _fib_zone(hi_lo[0], hi_lo[1], direction=side)
        if fz:
            src = h4 if len(h4) >= 8 else h1
            c = _cand(
                "fib_h4",
                fz[0],
                fz[1],
                tf="H4" if len(h4) >= 8 else "H1",
                label="Фібо 0.618–0.786 H4",
                origin_ts=str((src[-1] or {}).get("ts") or "") if src else "",
                why="OTE 0.618–0.786 від swing H4, не від поточної ціни",
            )
            if c:
                out.append(c)

    if len(d1) >= 2:
        prev = d1[-2]
        # Рівень D — PDH для шорта / PDL для лонга, не вся денна ширина.
        if side == "SHORT":
            c = _cand("dw", float(prev["high"]) * 0.999, float(prev["high"]), tf="D1", label="рівень D")
        else:
            c = _cand("dw", float(prev["low"]), float(prev["low"]) * 1.001, tf="D1", label="рівень D")
        if c:
            out.append(c)
        mid = (float(prev["high"]) + float(prev["low"])) / 2.0
        c2 = _cand("mirror", mid * 0.998, mid * 1.002, tf="D1", label="дзеркало D")
        if c2:
            out.append(c2)
    if len(w1) >= 2:
        prevw = w1[-2]
        if side == "SHORT":
            c = _cand("dw", float(prevw["high"]) * 0.999, float(prevw["high"]), tf="W", label="рівень W")
        else:
            c = _cand("dw", float(prevw["low"]), float(prevw["low"]) * 1.001, tf="W", label="рівень W")
        if c:
            out.append(c)

    rng_src = h1 if len(h1) >= 10 else m15
    bounds = detect_range_bounds(rng_src) if rng_src else None
    if bounds:
        c = _cand("range_edge", bounds.get("low"), bounds.get("high"), tf="H1", label="межа боковика")
        if c:
            # Для входу беремо край у бік сетапу, не всю ширину.
            if side == "SHORT":
                edge = _cand("range_edge", bounds["high"] * 0.999, bounds["high"], tf="H1", label="межа боковика")
            else:
                edge = _cand("range_edge", bounds["low"], bounds["low"] * 1.001, tf="H1", label="межа боковика")
            if edge:
                out.append(edge)

    sw_src = m15 if len(m15) >= 3 else h1
    sw = detect_sweep_from_candles(sw_src)
    lv = _f(sw.get("sweep_level"))
    if lv is not None and (
        (side == "SHORT" and sw.get("bsl_sweep")) or (side == "LONG" and sw.get("ssl_sweep"))
    ):
        c = _cand("sweep", lv * 0.999, lv * 1.001, tf="M15", label="свіп ліквідності")
        if c:
            out.append(c)

    bull, bear = _fvgs(h1 if len(h1) >= 8 else m15)
    if bull and bear:
        b_lo, b_hi = bull[-1]
        e_lo, e_hi = bear[-1]
        if _overlap(b_lo, b_hi, e_lo, e_hi):
            lo, hi = max(b_lo, e_lo), min(b_hi, e_hi)
            if hi < lo:
                lo, hi = min(b_lo, e_lo), max(b_hi, e_hi)
            c = _cand("bpr", lo, hi, tf="H1", label="BPR")
            if c:
                out.append(c)

    return [x for x in out if x]


def cluster_zones(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Зона входу — кластер з найбільшою кількістю унікальних тегів."""
    if not cands:
        return []
    clusters: List[Dict[str, Any]] = []
    used = [False] * len(cands)
    for i, a in enumerate(cands):
        if used[i]:
            continue
        members = [a]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, b in enumerate(cands):
                if used[j]:
                    continue
                if any(_overlap(m["lo"], m["hi"], b["lo"], b["hi"]) for m in members):
                    members.append(b)
                    used[j] = True
                    changed = True
        tags = []
        for m in members:
            if m["tag"] not in tags:
                tags.append(m["tag"])
        lo = min(m["lo"] for m in members)
        hi = max(m["hi"] for m in members)
        clusters.append(
            {
                "lo": lo,
                "hi": hi,
                "mid": (lo + hi) / 2.0,
                "tags": tags,
                "n": len(tags),
                "labels": [m["label"] for m in members],
                "members": members,
            }
        )
    clusters.sort(key=lambda x: (-int(x["n"]), float(x["hi"] - x["lo"])))
    return clusters


def _swings(rows: List[Dict[str, Any]]) -> Tuple[List[float], List[float]]:
    highs: List[float] = []
    lows: List[float] = []
    if len(rows) < 5:
        return highs, lows
    for i in range(1, len(rows) - 1):
        if rows[i]["high"] >= rows[i - 1]["high"] and rows[i]["high"] >= rows[i + 1]["high"]:
            highs.append(float(rows[i]["high"]))
        if rows[i]["low"] <= rows[i - 1]["low"] and rows[i]["low"] <= rows[i + 1]["low"]:
            lows.append(float(rows[i]["low"]))
    return highs, lows


def detect_ltf_confirms(
    *,
    direction: str,
    candles_ltf: Any,
    zone_lo: Any,
    zone_hi: Any,
    range_bounds: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Підтвердження Булковскі/Pine на молодшому ТФ у зоні."""
    side = str(direction or "").upper()
    rows = _bars(candles_ltf)
    hits: List[str] = []
    if len(rows) < 4:
        return hits
    last = rows[-1]
    lo, hi = _f(zone_lo), _f(zone_hi)
    if lo is None or hi is None:
        return hits
    if lo > hi:
        lo, hi = hi, lo
    # Ціна має торкнутись зони тінню.
    touched = float(last["low"]) <= hi and float(last["high"]) >= lo
    if not touched:
        # Допускаємо, якщо попередня свічка торкнулась.
        prev = rows[-2]
        touched = float(prev["low"]) <= hi and float(prev["high"]) >= lo
    if not touched:
        return hits

    highs, lows = _swings(rows)
    tol = (hi - lo) * 0.35 if hi > lo else abs(hi) * 0.002
    if side == "SHORT" and len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if abs(a - b) <= max(tol, abs(a) * 0.002):
            hits.append("double_top")
        if len(highs) >= 3 and abs(highs[-3] - b) <= max(tol, abs(b) * 0.002):
            hits.append("triple_top")
    if side == "LONG" and len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if abs(a - b) <= max(tol, abs(a) * 0.002):
            hits.append("double_bottom")
        if len(lows) >= 3 and abs(lows[-3] - b) <= max(tol, abs(b) * 0.002):
            hits.append("triple_bottom")

    # SFP: тінь за зону, закриття всередині / назад у зону (Turtle Soup).
    if side == "SHORT" and float(last["high"]) > hi and float(last["close"]) <= hi:
        hits.append("sfp")
    if side == "LONG" and float(last["low"]) < lo and float(last["close"]) >= lo:
        hits.append("sfp")

    prev = rows[-2]
    if side == "SHORT":
        if float(last["open"]) > float(last["close"]) and float(last["open"]) >= float(prev["close"]) and float(last["close"]) <= float(prev["open"]):
            if float(last["open"]) - float(last["close"]) > abs(float(prev["close"]) - float(prev["open"])):
                hits.append("engulf")
    else:
        if float(last["close"]) > float(last["open"]) and float(last["close"]) >= float(prev["open"]) and float(last["open"]) <= float(prev["close"]):
            if float(last["close"]) - float(last["open"]) > abs(float(prev["close"]) - float(prev["open"])):
                hits.append("engulf")

    # BOS/CHOCH: закриття за останній свінг.
    if side == "SHORT" and highs:
        if float(last["close"]) < min(r["low"] for r in rows[-4:-1]):
            hits.append("bos")
            hits.append("choch")
    if side == "LONG" and lows:
        if float(last["close"]) > max(r["high"] for r in rows[-4:-1]):
            hits.append("bos")
            hits.append("choch")

    if range_bounds:
        rh, rl = _f(range_bounds.get("high")), _f(range_bounds.get("low"))
        if rh is not None and rl is not None:
            if side == "LONG" and float(last["low"]) < rl and float(last["close"]) > rl:
                hits.append("spring")
            if side == "SHORT" and float(last["high"]) > rh and float(last["close"]) < rh:
                hits.append("upthrust")

    # Унікальний порядок. Triple з тих самих свінгів замінює double.
    seen = []
    for h in hits:
        if h not in seen:
            seen.append(h)
    if "triple_top" in seen and "double_top" in seen:
        seen = [h for h in seen if h != "double_top"]
    if "triple_bottom" in seen and "double_bottom" in seen:
        seen = [h for h in seen if h != "double_bottom"]
    return seen


def _retest_close_after_break(
    rows: List[Dict[str, Any]],
    *,
    side: str,
    zone_lo: float,
    zone_hi: float,
) -> Optional[float]:
    """Після пробою потрібна пізніша свічка із закриттям знову в зоні. Не вигадуємо ціну."""
    if len(rows) < 2:
        return None
    lo, hi = float(zone_lo), float(zone_hi)
    broke_i = None
    for i, r in enumerate(rows):
        c = _f(r.get("close"))
        if c is None:
            continue
        if side == "SHORT" and c <= lo:
            broke_i = i
        if side == "LONG" and c >= hi:
            broke_i = i
    if broke_i is None or broke_i >= len(rows) - 1:
        return None
    for r in rows[broke_i + 1 :]:
        c = _f(r.get("close"))
        if c is None:
            continue
        if lo <= c <= hi:
            return float(c)
    return None


def range_break_is_event(
    *,
    candles_h1: Any,
    candles_m15: Any = None,
) -> Optional[Dict[str, Any]]:
    """Пробій ренджу — не картка входу."""
    h1 = _bars(candles_h1)
    if len(h1) < 10:
        return None
    bounds = detect_range_bounds(h1)
    if not bounds:
        return None
    last = h1[-1]
    prev = h1[-2] if len(h1) >= 2 else None
    ev = classify_range_event(
        bounds=bounds,
        last=last,
        prev=prev,
        confirm_candles=_bars(candles_m15) if candles_m15 is not None else None,
    )
    if str(ev.get("event") or "").startswith("BREAK"):
        return {**ev, "is_event": True, "send_card": False, "reason": "пробій ренджу — подія, не вхід"}
    return None


def grade_for(*, n_zone: int, confirms: List[str] | None = None) -> str:
    """Сила зони: A = 3+ збіги, B = 2. Підтвердження LTF — окреме повідомлення після картки."""
    _ = confirms
    if n_zone >= GRADE_A:
        return "A"
    if n_zone >= GRADE_B:
        return "B"
    return ""


def zone_line(cluster: Dict[str, Any]) -> str:
    labels = []
    for m in cluster.get("members") or []:
        lab = str(m.get("label") or TAG_UA.get(m.get("tag"), m.get("tag")))
        if lab and lab not in labels:
            labels.append(lab)
    return " + ".join(labels[:6])


def confirm_line(confirms: List[str], wait_tf: str, *, direction: str = "") -> str:
    names = [CONFIRM_UA.get(x, x) for x in confirms]
    if names:
        return f"Чекаю на {wait_tf}: " + " або ".join(names[:3]) + " у зоні"
    if str(direction or "").upper() == "LONG":
        return f"Чекаю на {wait_tf}: подвійне дно або SFP у зоні"
    return f"Чекаю на {wait_tf}: подвійна вершина або SFP у зоні"


def now_status_line(*, price: Any, zone_lo: Any, zone_hi: Any, direction: str, symbol: str = "") -> str:
    from office_price_format import format_level_span

    px, lo, hi = _f(price), _f(zone_lo), _f(zone_hi)
    if lo is None or hi is None:
        return "Немає підтверджених меж зони"
    if lo > hi:
        lo, hi = hi, lo
    span = format_level_span(lo, hi, symbol)
    if px is None:
        return f"Зараз: межі {span}, ціна невідома"
    if lo <= px <= hi:
        return f"Зараз: ціна в зоні {span}, чекаю підтвердження"
    side = str(direction or "").upper()
    if side == "SHORT" and px < lo:
        return f"Зараз: ціна вже нижче зони {span} — не ганяю"
    if side == "LONG" and px > hi:
        return f"Зараз: ціна вже вище зони {span} — не ганяю"
    return f"Зараз: поза зоною {span}, чекаємо відкат у ці межі"


def scenario_story(
    *,
    timeframe: str,
    zone_lo: Any,
    zone_hi: Any,
    tags: Any = None,
    labels: Any = None,
    wait_tf: str = "",
    confirms: Any = None,
    direction: str = "",
    symbol: str = "",
) -> Dict[str, Any]:
    """Людською мовою. Без меж — не пишемо «чекаємо відкат/зону».

    Ціни — через єдиний tick-форматер (не :g, що дає 1.23e-05 / 1.23457e+08).
    """
    lo, hi = _f(zone_lo), _f(zone_hi)
    kinds = [str(x) for x in (labels or []) if str(x).strip()]
    if not kinds:
        kinds = [TAG_UA.get(str(t), str(t)) for t in (tags or []) if t]
    if lo is None or hi is None:
        return {
            "ok": False,
            "missing": ["межі зони"],
            "text": "Немає підтверджених меж зони — не чекаємо вигаданий відкат.",
        }
    ztype = kinds[0] if kinds else "зону"
    reasons = f"тут збігаються {' · '.join(kinds[:3])}" if kinds else "незалежних збігів немає"
    from office_price_format import format_level_span

    wt = wait_tf or confirm_timeframe(timeframe)
    conf_names = [CONFIRM_UA.get(x, x) for x in (confirms or []) if x]
    if conf_names:
        need = " або ".join(conf_names[:3])
    elif str(direction or "").upper() == "LONG":
        need = "подвійне дно або SFP"
    else:
        need = "подвійна вершина або SFP"
    return {
        "ok": True,
        "missing": [],
        "zone_type": ztype,
        "text": (
            f"Чекаємо відкат у {ztype} {format_level_span(lo, hi, symbol)} на {timeframe or 'H1'}; "
            f"{reasons}; на {wt} потрібне підтвердження: {need}."
        ),
    }


def lifecycle_from_status(
    status: Any,
    *,
    confirms: Any = None,
    has_position: bool = False,
    ttl_done: bool = False,
) -> Dict[str, str]:
    """Мапінг backend → екран. ENTERED лише при явному /position."""
    if has_position:
        return {"key": "entered", "ua": "У позиції (/position)"}
    st = str(status or "").upper()
    if ttl_done or st in ("EXPIRED",):
        return {"key": "ttl", "ua": "TTL вичерпано"}
    if st in ("CANCELLED", "STOPPED", "HIT_SL"):
        return {"key": "cancelled", "ua": "Скасовано"}
    if st in ("WATCHING", "WAIT"):
        return {"key": "waiting_zone", "ua": "Чекаємо зону"}
    if st in ("CONFIRMED", "CONFIRMATION_PENDING"):
        return {"key": "confirmed", "ua": "Підтверджено (не позиція)"}
    if st in ("ACTIVE", "HIT_ENTRY", "HIT_TP1", "HIT_TP2"):
        if confirms:
            return {"key": "confirmed", "ua": "Підтверджено (не позиція)"}
        return {"key": "found", "ua": "Знайдено"}
    return {"key": "found", "ua": str(status or "Знайдено")}


def evaluate_confluence(
    *,
    symbol: str,
    direction: str,
    timeframe: str,
    candles_m15: Any = None,
    candles_h1: Any = None,
    candles_h4: Any = None,
    candles_d1: Any = None,
    candles_w: Any = None,
    candles_ltf: Any = None,
    price: Any = None,
    now_ts: Any = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Повний вердикт: зона, сила, картка так/ні."""
    side = str(direction or "").upper()
    empty = {
        "send_card": False,
        "grade": "",
        "reason": "немає зони",
        "cluster": None,
        "confirms": [],
        "setup_key": "",
        "zone_lo": None,
        "zone_hi": None,
        "entry": None,
        "tags": [],
        "is_range_break": False,
    }
    if candidates is None:
        br = range_break_is_event(candles_h1=candles_h1, candles_m15=candles_m15)
        if br and br.get("is_event"):
            return {**empty, "reason": br.get("reason"), "is_range_break": True}

    cands = candidates if candidates is not None else collect_zone_candidates(
        direction=side,
        candles_m15=candles_m15,
        candles_h1=candles_h1,
        candles_h4=candles_h4,
        candles_d1=candles_d1,
        candles_w=candles_w,
    )
    clusters = cluster_zones(cands)
    px_side = _f(price)
    if px_side is not None and clusters:
        # Відкат іде проти поточного руху: LONG — зона на/під ціною, SHORT — на/над ціною; з іншого боку — це погоня
        if side == "SHORT":
            clusters = [c for c in clusters if float(c["hi"]) >= px_side]
        else:
            clusters = [c for c in clusters if float(c["lo"]) <= px_side]
        if not clusters:
            return {**empty, "reason": "зона збігів з іншого боку ціни — не відкат"}
    if not clusters:
        return {**empty, "reason": "немає збігів"}
    best = clusters[0]
    n = int(best["n"])
    wait_tf = confirm_timeframe(timeframe)
    ltf = candles_ltf if candles_ltf is not None else (candles_m15 if wait_tf == "M15" else candles_m15)
    bounds = detect_range_bounds(_bars(candles_h1) or _bars(candles_m15))
    confirms = detect_ltf_confirms(
        direction=side,
        candles_ltf=ltf,
        zone_lo=best["lo"],
        zone_hi=best["hi"],
        range_bounds=bounds,
    )
    grade = grade_for(n_zone=n, confirms=confirms)
    zone_key = setup_key(symbol=symbol, direction=side, zone_lo=best["lo"], zone_hi=best["hi"])
    from office_scenario_memory import (
        canonical_scenario_id,
        market_basis_key,
        scenario_identity_matches,
    )

    basis = market_basis_key(best)
    key = canonical_scenario_id(
        symbol=symbol,
        direction=side,
        timeframe=timeframe,
        basis=basis,
        zone_lo=best["lo"],
        zone_hi=best["hi"],
    )
    ts = float(now_ts if now_ts is not None else time.time())
    live = _LIVE.get(key)
    if not live:
        for existing_key, existing in _LIVE.items():
            if scenario_identity_matches(
                existing,
                symbol=symbol,
                direction=side,
                timeframe=timeframe,
                basis=basis,
                zone_lo=best["lo"],
                zone_hi=best["hi"],
            ):
                key, live = existing_key, existing
                break
    if live:
        born = float(live.get("ts") or 0)
        if ts - born < ttl_sec(timeframe):
            live.update(
                {
                    "zone_lo": float(best["lo"]),
                    "zone_hi": float(best["hi"]),
                    "entry_low": float(best["lo"]),
                    "entry_high": float(best["hi"]),
                    "zone_key": zone_key,
                }
            )
            return {
                **empty,
                "reason": f"сетап живий: {str(live.get('status') or 'WATCHING').upper()}",
                "setup_key": key,
                "scenario_id": key,
                "market_basis": basis,
                "zone_key": zone_key,
                "cluster": best,
                "grade": live.get("grade") or grade,
                "zone_lo": best["lo"],
                "zone_hi": best["hi"],
                "entry": float(best["mid"]),
                "tags": best["tags"],
                "confirms": confirms,
                "n": n,
            }

    if n < GRADE_B:
        return {
            **empty,
            "reason": "менше 2 збігів",
            "cluster": best,
            "n": n,
            "tags": best["tags"],
            "setup_key": key,
            "scenario_id": key,
            "market_basis": basis,
            "zone_key": zone_key,
            "zone_lo": best["lo"],
            "zone_hi": best["hi"],
            "entry": float(best["mid"]),
            "confirms": confirms,
        }

    px = _f(price)
    # Вхід — зона відкату, не поточна ціна. Картка watching; LTF — наступне повідомлення.
    entry_mid = float(best["mid"])
    return {
        "send_card": True,
        "grade": grade,
        "reason": "ok",
        "cluster": best,
        "confirms": confirms,
        "setup_key": key,
        "scenario_id": key,
        "market_basis": basis,
        "zone_key": zone_key,
        "zone_lo": float(best["lo"]),
        "zone_hi": float(best["hi"]),
        "entry": entry_mid,
        "tags": best["tags"],
        "n": n,
        "wait_tf": wait_tf,
        "zone_line": zone_line(best),
        "confirm_wait": confirm_line(confirms, wait_tf, direction=side),
        "now_line": now_status_line(price=px, zone_lo=best["lo"], zone_hi=best["hi"], direction=side, symbol=symbol),
        "price": px,
        "ttl_sec": ttl_sec(timeframe),
        "story": scenario_story(
            timeframe=timeframe,
            zone_lo=best["lo"],
            zone_hi=best["hi"],
            tags=best["tags"],
            labels=best.get("labels") or [],
            wait_tf=wait_tf,
            confirms=confirms,
            direction=side,
            symbol=symbol,
        ),
        "lifecycle": lifecycle_from_status("ACTIVE", confirms=confirms),
        "zones": best.get("members") or [],
    }


def mark_live(key: str, payload: Dict[str, Any]) -> None:
    if not key:
        return
    _LIVE[key] = {
        **payload,
        "status": str(payload.get("status") or "WATCHING").upper(),
        "ts": float(payload.get("ts") or time.time()),
    }


def live_items() -> List[Tuple[str, Dict[str, Any]]]:
    return list(_LIVE.items())


def live_drop(key: str) -> None:
    _LIVE.pop(key, None)


def reset_live() -> None:
    """Для тестів: порожній реєстр живих сетапів."""
    _LIVE.clear()
    _DB_ONLY.clear()


def note_db_only(key: str) -> bool:
    """Один запис у БД на ключ без картки."""
    if not key or key in _DB_ONLY:
        return False
    _DB_ONLY[key] = time.time()
    return True


def _iso_ts(v: Any) -> float:
    from office_scenario_lifecycle import _ts

    return _ts(v) or 0.0


def hydrate_live_from_db(db_path: str) -> int:
    """Після рестарту Worker: канонічний ID і lifecycle з БД."""
    import re

    from office_bridge import signal_get_active, signal_get_scenarios
    from office_desk_card import is_legacy_desk_range
    from office_scenario_memory import parse_note_meta

    n = 0
    try:
        canonical_rows = signal_get_scenarios(db_path) or []
        canonical_ids = {str(x.get("signal_id") or "") for x in canonical_rows}
        rows = canonical_rows + [
            x for x in (signal_get_active(db_path) or []) if str(x.get("signal_id") or "") not in canonical_ids
        ]
    except Exception:
        return 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        if is_legacy_desk_range(r):
            continue
        st = str(r.get("status") or "").upper()
        if st not in ("ACTIVE", "HIT_ENTRY", "WATCHING", "ZONE_REACHED", "CONFIRMED", "CANCELLED"):
            continue
        note = str(r.get("analysis_note") or "")
        meta = parse_note_meta(note)
        m = re.search(r"ckey=([^\s]+)", note)
        key = str(meta.get("scenario_id") or "")
        if not key:
            key = m.group(1) if m else setup_key(
                symbol=str(r.get("symbol") or ""),
                direction=str(r.get("direction") or ""),
                zone_lo=r.get("entry_low"),
                zone_hi=r.get("entry_high"),
            )
        if not key or key in _LIVE:
            continue
        sid = str(r.get("signal_id") or "")
        if sid.startswith(("lev-watch-", "watch-")):
            continue  # службові спостереження: картки не було, повідомляти про їх «скасування» не можна
        tf_h = str(parse_note_meta(note).get("timeframe") or "H1")
        born = _iso_ts(r.get("ts_created"))
        if st != "CANCELLED" and born and time.time() - born >= ttl_sec(tf_h):
            continue  # протермінований до перезапуску — не воскрешаємо (завершені лишаємо: цикл їх не чіпає, а стан переживає рестарт)
        mark_live(
            key,
            {
                "symbol": r.get("symbol"),
                "direction": r.get("direction"),
                "timeframe": parse_note_meta(note).get("timeframe") or "H1",
                "origin": parse_note_meta(note).get("origin") or "desk",
                "signal_id": r.get("signal_id"),
                "sl": r.get("sl"),
                "tp1": r.get("tp1"),
                "tp2": r.get("tp2"),
                "zone_lo": r.get("entry_low"),
                "zone_hi": r.get("entry_high"),
                "entry_low": r.get("entry_low"),
                "entry_high": r.get("entry_high"),
                "basis": meta.get("basis") or "",
                "grade": "",
                "status": st,
                "ts": born or time.time(),
            },
        )
        n += 1
    return n


def follow_setup(
    *,
    setup: Dict[str, Any],
    price: Any,
    candles_ltf: Any,
    now_ts: Any = None,
    candles_h1: Any = None,
) -> Dict[str, Any]:
    """Після картки: підтвердження входу / скасування (скасування за рівнем — лише за закриттям H1: потрібні `candles_h1`)."""
    side = str(setup.get("direction") or "").upper()
    sl = _f(setup.get("sl"))
    lo, hi = _f(setup.get("zone_lo")), _f(setup.get("zone_hi"))
    px = _f(price)
    ts = float(now_ts if now_ts is not None else time.time())
    born = float(setup.get("ts") or 0)
    tf = str(setup.get("timeframe") or "M15")
    if born and ts - born >= ttl_sec(tf):
        return {"action": "cancel", "reason": f"таймаут {ttl_sec(tf)//3600} год без входу"}
    if sl is not None and candles_h1 is not None:
        # рівень скасування — за ЗАКРИТТЯМ годинної свічки, а не за проколом ціни (на картці так і написано)
        from office_scenario_lifecycle import cancel_reason_h1, closed_h1_beyond

        hit = closed_h1_beyond(candles_h1, side=side, level=sl, since_ts=born, now_ts=ts)
        if hit:
            return {"action": "cancel", "reason": cancel_reason_h1(side, sl, str(setup.get("symbol") or "")), "closed_h1": hit["close"]}
    confirms = detect_ltf_confirms(
        direction=side,
        candles_ltf=candles_ltf,
        zone_lo=lo,
        zone_hi=hi,
    )
    rows = _bars(candles_ltf)
    cl = float(rows[-1]["close"]) if rows else px
    broke = False
    inside = False
    if cl is not None and lo is not None and hi is not None:
        broke = (side == "SHORT" and cl <= lo) or (side == "LONG" and cl >= hi)
        inside = lo <= cl <= hi
    if sl is not None and lo is not None and hi is not None:
        from office_alert_gate import validate_trade_geometry

        geo = validate_trade_geometry(
            direction=side,
            sl=sl,
            tp1=setup.get("tp1"),
            entry_low=lo,
            entry_high=hi,
            tp2=setup.get("tp2"),
            require_tp=setup.get("tp1") is not None,
        )
        if not geo.get("ok"):
            return {
                "action": "hold",
                "reason": str(geo.get("reason") or "геометрія"),
                "geometry_invalid": True,
                "price": cl,
            }
    if broke:
        retest_px = _retest_close_after_break(rows, side=side, zone_lo=lo, zone_hi=hi)
        if retest_px is None:
            return {
                "action": "hold",
                "reason": "пробій зони — чекаю ретест окремими свічками",
                "need_retest": True,
                "price": cl,
            }
        names = " + ".join(CONFIRM_UA.get(x, x) for x in confirms[:3]) if confirms else "ретест"
        return {
            "action": "confirm",
            "reason": names,
            "price": retest_px,
            "detail": f"{names} + ретест у зоні після пробою",
            "need_retest": False,
            "confirms": confirms,
        }
    if inside and confirms:
        from office_telegram_filter import format_level_span

        names = " + ".join(CONFIRM_UA.get(x, x) for x in confirms[:3])
        return {
            "action": "confirm",
            "reason": names,
            "price": cl,
            "detail": f"{names} + закриття в зоні {format_level_span(lo, hi)}",
            "need_retest": False,
            "confirms": confirms,
        }
    return {"action": "hold", "reason": "чекаємо"}


def format_confirm_card(*, symbol: str, direction: str, price: Any, detail: str) -> str:
    from office_telegram_filter import format_px

    side = str(direction or "").upper()
    return (
        f"✅ {str(symbol).upper()} {side} · сценарій підтверджено (не /position) · {format_px(price, symbol)}\n"
        f"Підтвердження: {detail}"
    )


def format_cancel_card(*, symbol: str, direction: str, reason: str) -> str:
    side = str(direction or "").upper()
    return f"❌ {str(symbol).upper()} {side} · скасовано — {reason}"

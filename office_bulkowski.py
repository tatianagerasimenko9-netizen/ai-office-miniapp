"""Фігури Булковскі як перевірювані правила на закритих свічках (LTF). Перелік із `office_worker_library/books/bulkowski_encyclopedia_chart_patterns`
(52 картки); реалізовано: голова і плечі (пряма/перевернута), подвійні/потрійні вершини й дна (Adam/Eve — `office_patterns`), трикутники
(висхідний/низхідний/симетричний), прямокутник, клини (висхідний/спадний), прапор і вимпел. Решта фігур бібліотеки (діаманти, чашка з ручкою, острови,
горни, pipe, scallops, broadening, bump-and-run, measured move та ін.) поки НЕ перевіряється кодом → у картках їх немає.

Спільні правила: фігура «вмикається» лише ЗАКРИТТЯМ свічки за межею після її формування; допуски від ATR(14); скасування — закриття за протилежною межею;
ціль — measure rule (висота фігури від точки пробою). Повертається список знайдених фігур: {kind, side, confirmed, level, target, why}. Стати БУЛКОВСКІ
(failure rate, середній %) не використовуємо — лише геометрію."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from office_patterns import atr as _atr, closed_only

K = 2                # свінги: по 2 свічки з боків
MIN_BARS = 12
KINDS_IMPLEMENTED = ("head_shoulders", "inverse_head_shoulders", "ascending_triangle", "descending_triangle", "symmetrical_triangle", "rectangle",
                     "rising_wedge", "falling_wedge", "flag", "pennant")


def _sw(rows: List[Dict[str, Any]], key: str, low: bool) -> List[Tuple[int, float]]:
    out = []
    for i in range(K, len(rows) - K):
        v = float(rows[i][key])
        around = [float(rows[j][key]) for j in range(i - K, i + K + 1) if j != i]
        if (low and all(v < a for a in around)) or ((not low) and all(v > a for a in around)):
            out.append((i, v))
    return out


def _fit(pts: List[Tuple[int, float]]) -> Optional[Tuple[float, float]]:
    """Пряма y = a·x + b за МНК; None, якщо менше двох точок."""
    if len(pts) < 2:
        return None
    n = len(pts)
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts); sxy = sum(p[0] * p[1] for p in pts)
    d = n * sxx - sx * sx
    if d == 0:
        return None
    a = (n * sxy - sx * sy) / d
    return a, (sy - a * sx) / n


def _at(line: Tuple[float, float], x: float) -> float:
    return line[0] * x + line[1]


def _first_close_beyond(rows: List[Dict[str, Any]], start: int, up: bool, level_at) -> Optional[int]:
    for i in range(start, len(rows)):
        lv = level_at(i)
        cl = float(rows[i]["close"])
        if (up and cl > lv) or ((not up) and cl < lv):
            return i
    return None


def _res(kind: str, side: str, conf: bool, level: float, target: Optional[float], why: str, idx: Optional[int] = None) -> Dict[str, Any]:
    return {"kind": kind, "side": side, "confirmed": conf, "level": round(level, 8), "target": round(target, 8) if target is not None else None, "why": why, "confirm_idx": idx}


def head_shoulders(rows: List[Dict[str, Any]], a: float) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for top in (True, False):
        pts = _sw(rows, "high" if top else "low", low=not top)
        if len(pts) < 3:
            continue
        L, H, R = pts[-3], pts[-2], pts[-1]
        # три екстремуми поспіль: голова найвища (найнижча) з запасом ≥0,5×ATR, плечі приблизно рівні
        sign = 1 if top else -1
        if not (sign * (H[1] - L[1]) >= 0.5 * a and sign * (H[1] - R[1]) >= 0.5 * a):
            continue
        # западини між екстремумами → лінія шиї
        opp = "low" if top else "high"
        t1 = (min if top else max)(range(L[0], H[0] + 1), key=lambda i: float(rows[i][opp]))
        t2 = (min if top else max)(range(H[0], R[0] + 1), key=lambda i: float(rows[i][opp]))
        neck_pts = [(t1, float(rows[t1][opp])), (t2, float(rows[t2][opp]))]
        head_h = sign * (H[1] - (neck_pts[0][1] + neck_pts[1][1]) / 2)
        if head_h <= 0 or abs(L[1] - R[1]) > 0.35 * head_h or abs(neck_pts[0][1] - neck_pts[1][1]) > 0.5 * head_h:
            continue
        neck = _fit(neck_pts)
        if neck is None:
            continue
        idx = _first_close_beyond(rows, R[0] + 1, not top, lambda i: _at(neck, i))
        lvl = _at(neck, len(rows) - 1)
        tgt = _at(neck, idx) - head_h if (idx is not None and top) else (_at(neck, idx) + head_h if idx is not None else None)
        out.append(_res("head_shoulders" if top else "inverse_head_shoulders", "SHORT" if top else "LONG", idx is not None, lvl, tgt,
                        f"голова {H[1]:.6g}, плечі {L[1]:.6g}/{R[1]:.6g}, шия {lvl:.6g}", idx))
    return out


def triangles_rectangle(rows: List[Dict[str, Any]], a: float) -> List[Dict[str, Any]]:
    hi, lo = _sw(rows, "high", False)[-5:], _sw(rows, "low", True)[-5:]
    if len(hi) < 2 or len(lo) < 2:
        return []
    span = max(hi[-1][0], lo[-1][0]) - min(hi[0][0], lo[0][0])
    if span < 8:
        return []
    fh, fl = _fit(hi), _fit(lo)
    if not fh or not fl:
        return []
    slope_tol = 0.05 * a           # «горизонталь»: нахил ≤ 0,05×ATR на свічку
    flat_h, flat_l = abs(fh[0]) <= slope_tol, abs(fl[0]) <= slope_tol
    x0 = min(hi[0][0], lo[0][0])
    start_w = _at(fh, x0) - _at(fl, x0)
    now_x = len(rows) - 1
    xe = max(hi[-1][0], lo[-1][0])   # звуження міряємо на останньому свінгу фігури, а не на поточній (після пробою лінії вже перетнулись)
    conv = start_w > (_at(fh, xe) - _at(fl, xe)) > 0
    out: List[Dict[str, Any]] = []

    def brk(up: bool, line) -> Optional[int]:
        return _first_close_beyond(rows, max(hi[-1][0], lo[-1][0]) + 1, up, lambda i: _at(line, i))

    if flat_h and fl[0] > slope_tol and conv:
        i = brk(True, fh)
        out.append(_res("ascending_triangle", "LONG", i is not None, _at(fh, now_x), (_at(fh, i) + start_w) if i is not None else None, "плоский опір, зростаючі мінімуми", i))
    elif flat_l and fh[0] < -slope_tol and conv:
        i = brk(False, fl)
        out.append(_res("descending_triangle", "SHORT", i is not None, _at(fl, now_x), (_at(fl, i) - start_w) if i is not None else None, "плоска підтримка, спадні максимуми", i))
    elif fh[0] < -slope_tol and fl[0] > slope_tol and conv:
        iu, idn = brk(True, fh), brk(False, fl)
        for up, i, ln in ((True, iu, fh), (False, idn, fl)):
            if i is not None:
                out.append(_res("symmetrical_triangle", "LONG" if up else "SHORT", True, _at(ln, now_x), (_at(ln, i) + start_w) if up else (_at(ln, i) - start_w), "сходяться обидві лінії", i))
                break
        if not out:
            out.append(_res("symmetrical_triangle", "LONG", False, _at(fh, now_x), None, "сходяться обидві лінії (пробою ще немає)"))
    elif flat_h and flat_l and abs(fh[1] - fl[1]) < 20 * a and len(hi) >= 2 and len(lo) >= 2 and start_w >= 1.0 * a:
        iu, idn = brk(True, fh), brk(False, fl)
        if iu is not None or idn is not None:
            up = idn is None or (iu is not None and iu < idn)
            i = iu if up else idn
            out.append(_res("rectangle", "LONG" if up else "SHORT", True, _at(fh if up else fl, now_x), (_at(fh, i) + start_w) if up else (_at(fl, i) - start_w), "горизонтальний коридор, ≥2 торкання", i))
        else:
            out.append(_res("rectangle", "LONG", False, _at(fh, now_x), None, "горизонтальний коридор (пробою ще немає)"))
    elif fh[0] > slope_tol and fl[0] > slope_tol and fl[0] > fh[0] and conv:
        i = brk(False, fl)
        out.append(_res("rising_wedge", "SHORT", i is not None, _at(fl, now_x), (_at(fl, i) - start_w) if i is not None else None, "обидві лінії вгору й сходяться", i))
    elif fh[0] < -slope_tol and fl[0] < -slope_tol and fh[0] < fl[0] and conv:
        i = brk(True, fh)
        out.append(_res("falling_wedge", "LONG", i is not None, _at(fh, now_x), (_at(fh, i) + start_w) if i is not None else None, "обидві лінії вниз і сходяться", i))
    return out


def flags(rows: List[Dict[str, Any]], a: float) -> List[Dict[str, Any]]:
    """Імпульс ≥3×ATR за ≤12 свічок, далі 5–20 свічок корекції проти нього (відкат ≤50% імпульсу); пробій закриттям за межею корекції в бік
    імпульсу. Прапор — приблизно паралельні межі, вимпел — межі сходяться."""
    n = len(rows)
    out: List[Dict[str, Any]] = []
    for up in (True, False):
        found = None
        for e in range(n - 6, 2, -1):
            starts = [s0 for s0 in range(max(0, e - 12), e - 1)
                      if ((float(rows[e]["high"]) - float(rows[s0]["low"])) if up else (float(rows[s0]["high"]) - float(rows[e]["low"]))) >= 3 * a]
            if not starts:
                continue
            s0 = max(starts)                       # найкоротший імпульс, що дає ≥3×ATR
            mv = (float(rows[e]["high"]) - float(rows[s0]["low"])) if up else (float(rows[s0]["high"]) - float(rows[e]["low"]))
            pole = float(rows[e]["high"]) if up else float(rows[e]["low"])
            for L in range(5, 21):
                cons = rows[e + 1:e + 1 + L]
                if len(cons) < 5:
                    break
                retr = (pole - min(float(r["low"]) for r in cons)) if up else (max(float(r["high"]) for r in cons) - pole)
                if retr <= 0 or retr > 0.5 * mv:
                    continue
                hi = _fit([(i, float(r["high"])) for i, r in enumerate(cons)])
                lo = _fit([(i, float(r["low"])) for i, r in enumerate(cons)])
                if not hi or not lo:
                    continue
                converge = hi[0] < -0.04 * a and lo[0] > 0.04 * a and up or (hi[0] < -0.04 * a and lo[0] > 0.04 * a)
                parallel = (up and hi[0] <= 0.02 * a and lo[0] <= 0.02 * a) or ((not up) and hi[0] >= -0.02 * a and lo[0] >= -0.02 * a)
                if not (converge or parallel):
                    continue
                line = hi if up else lo
                after = rows[e + 1 + L:]
                idx = None
                for j, r in enumerate(after):
                    x = L + j
                    if (up and float(r["close"]) > _at(line, x)) or ((not up) and float(r["close"]) < _at(line, x)):
                        idx = e + 1 + L + j
                        break
                if idx is None and after:
                    continue   # після корекції були свічки, але пробою немає — інша форма
                lvl = _at(line, len(rows) - 1 - (e + 1))
                tgt = None
                if idx is not None:
                    base = _at(line, idx - (e + 1))
                    tgt = base + mv if up else base - mv
                found = _res("pennant" if converge else "flag", "LONG" if up else "SHORT", idx is not None, lvl, tgt,
                             f"імпульс {mv:.6g} ≥3×ATR, відкат {retr / mv * 100:.0f}%", idx)
                break
            if found:
                break
        if found:
            out.append(found)
    return out


def detect_all(candles: Any, *, now_ts: Optional[float] = None, lookback: int = 80) -> List[Dict[str, Any]]:
    rows = closed_only([r for r in (candles or []) if isinstance(r, dict)], now_ts)[-lookback:]
    if len(rows) < MIN_BARS:
        return []
    a = _atr(rows)
    if not a:
        return []
    out = head_shoulders(rows, a) + triangles_rectangle(rows, a) + flags(rows, a)
    return out


def confirmed_for(candles: Any, side: str, *, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Підтверджені (закриття за межею) фігури в бік `side` — для картки/журналу. Кожна містить `kind` (тег журналу) і `why`."""
    return [p for p in detect_all(candles, now_ts=now_ts) if p["confirmed"] and p["side"] == str(side).upper()]

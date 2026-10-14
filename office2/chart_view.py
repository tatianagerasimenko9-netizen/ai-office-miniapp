"""Вибір видимого діапазону й таймфрейму графіка READY у Telegram та фактичні структурні позначки.

ЛИШЕ ВІДОБРАЖЕННЯ: торгові правила, рівні, SL/TP і сам READY тут не змінюються. Усе малюється з реальних ЗАКРИТИХ свічок Binance Futures, що були в контексті
рішення (без майбутніх свічок). Позначки (sweep, зсув структури) беруться лише з обчислених полів тези (event / break / level) і перевіряються за свічками.

Параметри читабельності (НЕ торгові правила, ГІПОТЕЗА щодо зручності): мінімум 3 доби історії або подвійна довжина структури, 40–140 свічок на екрані.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

TF_SEC = {"M15": 900, "H1": 3600, "H4": 14400}
MIN_WINDOW_SEC = 3 * 86400
TARGET_BARS, MIN_BARS, MAX_BARS = 90, 40, 140


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def structure_start(th: Dict[str, Any]) -> Optional[float]:
    """Найраніший момент структури сценарію: подія (sweep/origin), імпульс origin, зсув структури."""
    ev = th.get("event") or {}
    ts: List[float] = []
    for v in (ev.get("ts"), ((ev.get("origin") or {}).get("impulse") or {}).get("origin_ts"), (th.get("break") or {}).get("ts")):
        f = _f(v)
        if f:
            ts.append(f)
    return min(ts) if ts else None


def choose(th: Dict[str, Any], now: float) -> Dict[str, Any]:
    """Головний ТФ картки: вікно = max(3 доби, 2×довжина структури); береться ТФ, у якого число свічок найближче до 90 у межах 40–140 (H1 для типових сценаріїв, H4 для довгих структур)."""
    start = structure_start(th)
    span = max(0.0, now - start) if start else 0.0
    window = max(float(MIN_WINDOW_SEC), 2.0 * span)
    best = None
    for tf, step in TF_SEC.items():
        bars = window / step
        if MIN_BARS <= bars <= MAX_BARS:
            score = abs(bars - TARGET_BARS)
            if best is None or score < best[0]:
                best = (score, tf)
    tf = best[1] if best else "H4"
    step = TF_SEC[tf]
    n = int(min(MAX_BARS, max(MIN_BARS, window / step)))
    return {"tf": tf, "step": step, "bars": n, "window_sec": window, "structure_start_ts": start,
            "reason": f"вікно {window / 86400:.1f} доби (структура {span / 3600:.1f} год × 2, мінімум 3 доби) → {n} свічок {tf}"}


def _rows(arr: Dict[str, np.ndarray], idx: List[int], src: str = "binance_futures") -> List[Dict[str, Any]]:
    from datetime import datetime, timezone

    return [{"ts": datetime.fromtimestamp(float(arr["t"][i]), tz=timezone.utc).isoformat(), "open": float(arr["o"][i]), "high": float(arr["h"][i]), "low": float(arr["l"][i]),
             "close": float(arr["c"][i]), "volume": float(arr["v"][i]) if "v" in arr else None, "src": src} for i in idx]


def build_rows(ctx: Dict[str, Any], view: Dict[str, Any], now: float) -> List[Dict[str, Any]]:
    """Свічки вибраного ТФ: лише бари, що закрилися ≤ now, плюс остання (ще не закрита) свічка ТФ, зібрана з уже закритих M15. Нічого з майбутнього."""
    from datetime import datetime, timezone

    tf, step, n = view["tf"], view["step"], int(view["bars"])
    m15 = ctx["m15"]
    if tf == "M15":
        idx = [i for i in range(len(m15["t"])) if float(m15["t"][i]) + 900 <= now + 1e-6][-n:]
        return _rows(m15, idx)
    base = ctx["h1"] if tf == "H1" else ctx["h4"]
    done = [i for i in range(len(base["t"])) if float(base["t"][i]) + step <= now + 1e-6]
    rows = _rows(base, done)
    last_end = float(base["t"][done[-1]]) + step if done else None
    # свічка, що формується: закриті M15 після кінця останнього повного бару ТФ
    f_idx = [i for i in range(len(m15["t"])) if float(m15["t"][i]) + 900 <= now + 1e-6 and (last_end is None or float(m15["t"][i]) >= last_end)]
    if f_idx:
        t0 = (float(m15["t"][f_idx[0]]) // step) * step
        f_idx = [i for i in f_idx if float(m15["t"][i]) >= t0]
        o = float(m15["o"][f_idx[0]])
        rows.append({"ts": datetime.fromtimestamp(t0, tz=timezone.utc).isoformat(), "open": o, "high": float(max(m15["h"][i] for i in f_idx)), "low": float(min(m15["l"][i] for i in f_idx)),
                     "close": float(m15["c"][f_idx[-1]]), "volume": float(sum(m15["v"][i] for i in f_idx)) if "v" in m15 else None, "src": "binance_futures", "forming": True})
    return rows[-n:]


def marks(th: Dict[str, Any], m15_rows: List[Dict[str, Any]], direction: str) -> List[Dict[str, Any]]:
    """Структурні позначки з обчислених полів тези (кожна підтверджена свічками): знятий рівень (sweep) і закриття за структурним рівнем (зсув структури)."""
    from office_patterns import _ts

    long_ = str(direction).upper() != "SHORT"
    by_ts: Dict[int, Dict[str, Any]] = {}
    for r in m15_rows or []:
        t = _ts(r.get("ts"))
        if t is not None:
            by_ts[int(t)] = r
    out: List[Dict[str, Any]] = []
    ev = th.get("event") or {}
    lvl = ev.get("level") or th.get("level") or {}
    t_ev, extreme, lp = _f(ev.get("ts")), _f(ev.get("extreme")), _f(lvl.get("p"))
    if ev.get("src") == "SWEEP" and t_ev and extreme is not None and lp is not None and int(t_ev) in by_ts:
        bar = by_ts[int(t_ev)]
        prior_bars = int((ev.get("prior") or {}).get("bars") or 12)
        out.append({"kind": "sweep", "label": "Sweep", "draw": "sweep", "t0": t_ev - prior_bars * 900, "t_sweep": t_ev, "price": lp, "extreme": extreme,
                    "close": float(bar["close"]), "type": "low" if long_ else "high"})
    br = th.get("break") or {}
    t_br, bl = _f(br.get("ts")), _f(br.get("level"))
    if t_br and bl is not None and int(t_br) in by_ts:
        # структурний свінг, який зламано: останній бар до зламу, чий екстремум дорівнює рівню (реальна точка в даних)
        key = "high" if long_ else "low"
        t0 = None
        for r in reversed([r for r in m15_rows if (_ts(r.get("ts")) or 0) < t_br][-160:]):
            if abs(float(r[key]) - bl) <= abs(bl) * 1e-9:
                t0 = _ts(r.get("ts"))
                break
        if t0 is not None:
            out.append({"kind": "break", "label": "Зсув структури", "draw": "break", "t0": t0, "t_break": t_br, "price": bl, "close": float(by_ts[int(t_br)]["close"])})
    org = ev.get("origin") or {}
    oz = org.get("zone")
    if ev.get("src") == "ORIGIN" and isinstance(oz, (list, tuple)) and len(oz) == 2 and t_ev:
        out.append({"kind": "origin", "label": "Origin-зона", "draw": "band", "t0": t_ev, "lo": min(float(oz[0]), float(oz[1])), "hi": max(float(oz[0]), float(oz[1]))})
    return out


def story(th: Dict[str, Any], entry_zone: Any, entry: Any, fmt) -> str:
    """Один рядок «чому тут сигнал»: лише обчислені факти тези (sweep → зсув структури → ретест зони → READY). Відсутній крок не вигадується — його просто немає в рядку."""
    ev = th.get("event") or {}
    lvl = ev.get("level") or th.get("level") or {}
    parts: List[str] = []
    if ev.get("src") == "SWEEP" and _f(lvl.get("p")) is not None:
        parts.append(f"Sweep {lvl.get('kind') or ''} {fmt(lvl['p'])}".replace("  ", " "))
    elif ev.get("src") == "ORIGIN":
        parts.append("Захист origin-зони")
    br = th.get("break") or {}
    if _f(br.get("level")) is not None:
        parts.append(f"зсув структури {fmt(br['level'])}")
    if isinstance(entry_zone, (list, tuple)) and len(entry_zone) == 2:
        parts.append("ретест зони")
    if entry is not None:
        parts.append(f"READY {fmt(entry)}")
    return " → ".join(parts)

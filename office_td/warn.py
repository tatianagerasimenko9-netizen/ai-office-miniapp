"""TD · ТЕСТ: попередження «слабкий сигнал» на картці. ГІПОТЕЗА (історія 2024-2026, 4 023 сигнали; див. docs/handoff/br-profitability/IMPROVEMENTS_LOG_UA.md): сигнал не блокується, лише позначається.
Причини: (1) стоп < 0,2%; (2) шорт проти сильного росту; (3) лонг після різкого падіння; (4) до найближчого рівня H4 або H1 у бік угоди ≥ 4 стопів.
Рівні: фрактальні максимуми/мінімуми (N=3), підходи = дні/бари, коли ціна дійшла на 0,25 ATR; пробій = закриття за рівнем > 0,25 ATR (мислення Герчика; параметри — ГІПОТЕЗА).
Вхід: закриті H1-бари (останній закритий = попередня година) + ціна входу."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

LIFE = {14400: 300, 3600: 600}
TF_NAME = {14400: "4-годинному", 3600: "годинному"}
N_FRACTAL, TOL = 3, 0.25


def enabled() -> bool:
    return os.getenv("TD_WARN", "1").strip().lower() in ("1", "true", "yes", "on")


def _epoch(x: dict) -> float:
    return datetime.fromisoformat(str(x["ts"]).replace("Z", "+00:00")).timestamp()


def _build(t, h, l, c, per):
    b = (t // per).astype(int); u, st = np.unique(b, return_index=True); en = np.r_[st[1:], len(b)]
    hi = np.array([h[x:y].max() for x, y in zip(st, en)]); lo = np.array([l[x:y].min() for x, y in zip(st, en)]); cl = np.array([c[y - 1] for y in en])
    rng = hi - lo; atr = np.full(len(rng), np.nan)
    for i in range(14, len(rng)): atr[i] = rng[i - 14:i].mean()          # ATR14 з попередніх барів ТФ (як у дослідженні)
    return u, hi, lo, cl, atr


def _levels(hi, lo, cl, atr, life):
    n = len(hi); out = []
    for i in range(N_FRACTAL, n - N_FRACTAL):
        for typ, p, ok in (("H", hi[i], hi[i] > hi[i - N_FRACTAL:i].max() and hi[i] > hi[i + 1:i + N_FRACTAL + 1].max()), ("L", lo[i], lo[i] < lo[i - N_FRACTAL:i].min() and lo[i] < lo[i + 1:i + N_FRACTAL + 1].min())):
            if not ok: continue
            conf = i + N_FRACTAL; eps = []; broke = None; prev = False
            for d in range(conf + 1, min(n, conf + 1 + life)):
                a_ = atr[d]
                if not a_ == a_: prev = False; continue
                if (cl[d] > p + TOL * a_) if typ == "H" else (cl[d] < p - TOL * a_): broke = d; break
                app = (hi[d] >= p - TOL * a_) if typ == "H" else (lo[d] <= p + TOL * a_)
                if app and not prev: eps.append(d)
                prev = app
            out.append((conf, float(p), typ, broke))
    return out


def ahead_stops(bars: List[dict], per: int, now: float, side: int, ent: float, sl: float) -> Optional[float]:
    """Відстань (у стопах) до найближчого ЖИВОГО рівня ТФ per у бік угоди; None, якщо рівня нема."""
    t = np.array([_epoch(x) for x in bars]); g = lambda k: np.array([float(x[k]) for x in bars])
    u, hi, lo, cl, atr = _build(t, g("high"), g("low"), g("close"), per)
    di = int(np.searchsorted(u, int(now // per))); best = None
    for conf, p, typ, broke in _levels(hi, lo, cl, atr, LIFE[per]):
        if conf >= di or di - conf > LIFE[per] or (broke is not None and broke < di): continue
        if (p - ent) * side > 0.0005 * ent:
            d = abs(p - ent)
            if best is None or d < best: best = d
    risk = abs(ent - sl)
    return best / risk if best is not None and risk > 0 else None


def compute(side: int, ent: float, sl: float, h1_closed: List[dict], btc_closed: Optional[List[dict]], now: float) -> List[str]:
    """Список коротких причин «слабкого сигналу» (порожній — картка без попередження). Помилка → порожній список."""
    out: List[str] = []
    try:
        cut = (now // 3600) * 3600          # лише бари, закриті ДО години, у якій було підтвердження (як у дослідженні)
        h1_closed = [x for x in h1_closed if _epoch(x) < cut]; btc_closed = [x for x in (btc_closed or []) if _epoch(x) < cut]
        c = np.array([float(x["close"]) for x in h1_closed])
        sp = abs(ent - sl) / ent * 100
        if sp < 0.2: out.append("дуже тісний стоп (менше 0,2%)")
        if len(c) >= 40:
            r6, r12, r36 = (ent / c[-6] - 1) * 100, (ent / c[-12] - 1) * 100, (ent / c[-35] - 1) * 100
            btc24 = 0.0
            if btc_closed and len(btc_closed) >= 26:
                bc = np.array([float(x["close"]) for x in btc_closed]); btc24 = (bc[-1] / bc[-25] - 1) * 100
            if side < 0 and r36 >= 4 and (r6 >= 2 or r12 >= 2): out.append(f"шорт проти сильного росту (ціна виросла на {r36:.1f}% за 36 год)")
            if side > 0 and (r6 <= -2.4 or r12 <= -2.5 or (r36 <= -3.5 and btc24 < 0)): out.append(f"лонг після різкого падіння (ціна впала на {abs(r36):.1f}% за 36 год)")
        far = []
        for per in (14400, 3600):
            a = ahead_stops(h1_closed, per, now, side, ent, sl)
            if a is not None and a >= 4: far.append((per, a))
        if far:
            tfs = " і ".join(TF_NAME[p] for p, _ in far); dist = min(a for _, a in far)
            out.append(f"немає близького рівня попереду (найближчий на {tfs} графіку — {dist:.0f} стопів)")
    except Exception as exc:  # noqa: BLE001
        print(f"[td] попередження недоступні: {type(exc).__name__}: {exc}", flush=True)
        return []
    return out

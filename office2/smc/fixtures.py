"""Якісні golden-фікстури за 40 навчальними схемами SM Trader: детерміновані синтетичні OHLC, що відтворюють конфігурацію схеми (НЕ реальні ціни).
Реальні OHLCV-приклади — окремо (scripts/smc_replay.py на даних біржі); синтетика не доводить статистичну корисність детектора, лише коректність за визначенням."""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np

from office2.smc.core import Arr

W = 900


def bars(rows: Sequence[Tuple[float, float, float, float]], t0: float = 1_800_000_000.0, width: int = W) -> Arr:
    """rows: (o,h,l,c). t — час відкриття, крок width."""
    a = np.array(rows, dtype=float)
    return {"t": t0 + width * np.arange(len(a), dtype=float), "o": a[:, 0].copy(), "h": a[:, 1].copy(), "l": a[:, 2].copy(), "c": a[:, 3].copy(), "v": np.ones(len(a))}


def zigzag(points: Sequence[float], per_leg: int = 4, wick: float = 0.0, t0: float = 1_800_000_000.0, width: int = W) -> Arr:
    """Ламана через точки розвороту: нога = per_leg свічок рівномірного кроку. Піки/впадини — чіткі swing-и (перша свічка нової ноги відкривається всередині попередньої,
    щоб high/low повороту не збігалися). wick — довжина тіні в одиницях ціни (якщо 0 — береться 6% кроку)."""
    rows: List[Tuple[float, float, float, float]] = []
    for k in range(len(points) - 1):
        a, b = float(points[k]), float(points[k + 1])
        step = (b - a) / per_leg
        w = wick if wick > 0 else abs(step) * 0.06
        up = b > a
        for m in range(per_leg):
            o = a + step * m
            c = a + step * (m + 1)
            if m == 0 and k > 0:
                o = a - step * 0.25                      # відкриття трохи «до» піку/впадини: high нової ноги < піку
            hi = max(o, c) + w
            lo = min(o, c) - w
            if m == per_leg - 1:
                if up:
                    hi = c + 2 * w + abs(step) * 0.1       # пік
                else:
                    lo = c - 2 * w - abs(step) * 0.1       # впадина
            rows.append((o, hi, lo, c))
    return bars(rows, t0, width)


def concat(*parts: Arr) -> Arr:
    t0 = float(parts[0]["t"][0])
    width = int(parts[0]["t"][1] - parts[0]["t"][0]) if len(parts[0]["t"]) > 1 else W
    cols = {k: np.concatenate([p[k] for p in parts]) for k in ("o", "h", "l", "c", "v")}
    cols["t"] = t0 + width * np.arange(len(cols["o"]), dtype=float)
    return cols


# ---- схема 04: Swing (3 позитивні + 1 негативний)
def swing_high_cases() -> List[Tuple[str, Arr, bool]]:
    pos1 = bars([(10, 11, 9.5, 10.8), (10.8, 12.0, 10.5, 11.0), (11.0, 11.4, 10.0, 10.2)])                     # бичача → вища → ведмежа
    pos2 = bars([(10, 11.2, 9.5, 10.5), (10.5, 12.0, 10.4, 10.6), (10.6, 11.0, 9.9, 10.0)])                    # дожі-центр
    pos3 = bars([(10, 10.6, 9.6, 10.2), (10.2, 11.5, 10.1, 11.3), (11.3, 11.5 - 0.05, 10.3, 10.4)])              # права свічка з високим тілом, але нижчим high
    neg = bars([(10, 12.0, 9.5, 11.0), (11.0, 12.0, 10.2, 10.4)])                                              # лише 2 свічки: центру немає
    return [("pos1", pos1, True), ("pos2", pos2, True), ("pos3", pos3, True), ("neg_two_candles", neg, False)]


# ---- схеми 05/06/08: висхідна/низхідна структура + BMS
def uptrend() -> Arr:
    return zigzag([100, 110, 104, 118, 111, 126, 119, 134, 127], per_leg=4)


def downtrend() -> Arr:
    return zigzag([134, 124, 130, 116, 123, 108, 115, 100, 107], per_leg=4)


# ---- схема 09: BMS ×3 → MSS → Confirm
def mss_confirm() -> Arr:
    # вершина 126 дала останній BMS; початок ноги — HL 111; закриття нижче 111 = MSS; відскок 114; закриття нижче 106 (низ ноги MSS) = CONFIRM
    return zigzag([100, 110, 104, 118, 111, 126, 106, 114, 99], per_leg=4)


# ---- схема 10 (праворуч) / 11: злам внутрішнього мінімуму ≠ MSS
def not_mss() -> Arr:
    # вершина 126 (BMS), відкат до 120 (вище захищеного 111), LH 124, злам 120 до 116 — але захищений мінімум 111 цілий → CORRECTION_BREAK, не MSS
    return zigzag([100, 110, 104, 118, 111, 126, 120, 124, 116], per_leg=4)


# ---- схема 07: range з девіацією
def range_with_deviation() -> Arr:
    pts = [100, 110, 102, 109, 101, 110, 103, 108, 102, 112, 104, 105]   # межі ≈110 / ≈101, девіація вище 110 до 112 з поверненням
    return zigzag(pts, per_leg=3)


def reflect(b: Arr, c0: float = 300.0) -> Arr:
    """Дзеркало відносно рівня c0 (ціни лишаються додатними): LONG-сценарій → SHORT."""
    return {"t": b["t"], "o": c0 - b["o"], "h": c0 - b["l"], "l": c0 - b["h"], "c": c0 - b["c"], "v": b["v"]}


def _prefix_range() -> Arr:
    return zigzag([108, 104, 110, 103, 109, 102, 108, 100, 106], per_leg=8)


REV_ROWS = [(105.5, 105.7, 102.0, 102.5), (102.5, 102.8, 100.4, 100.9), (100.9, 101.0, 98.6, 101.6), (101.6, 104.5, 101.5, 104.2), (104.2, 107.5, 104.0, 107.2),
            (107.2, 111.0, 107.0, 110.5), (110.5, 112.5, 110.0, 112.0), (112.0, 112.2, 108.0, 108.5), (108.5, 108.8, 104.5, 104.8), (104.8, 105.0, 101.6, 102.0), (102.0, 103.9, 101.8, 103.7)]


def reversal_long(upto: int = None) -> Arr:
    """Схема 39/40 (Reversal, LONG): SSL-рівень 100 → raid до 98,6 з поверненням → MS вгору (закриття вище 106) → POI (OB) → ретрейс → тригер. upto — скільки рядків сценарію віддати (для WAIT-станів)."""
    p = _prefix_range()
    rows = REV_ROWS if upto is None else REV_ROWS[:upto]
    tail = bars(rows, t0=float(p["t"][-1]) + W)
    return concat(p, tail)


REAL_LEVELS_LONG = [{"p": 112.6, "side": "high", "kind": "M15SW", "strength": 1, "taken_ts": None, "known": 0.0},
                    {"p": 118.0, "side": "high", "kind": "H4SW", "strength": 1, "taken_ts": None, "known": 0.0},
                    {"p": 126.0, "side": "high", "kind": "PDH", "strength": 1, "taken_ts": None, "known": 0.0}]


CONT_ROWS = REV_ROWS[:7] + [(112.0, 112.2, 108.0, 108.4), (108.4, 108.6, 106.2, 106.8), (106.8, 110.5, 106.6, 110.2), (110.2, 114.0, 110.0, 113.6), (113.6, 116.0, 113.4, 115.8),
                            (115.8, 116.0, 112.0, 112.4), (112.4, 112.6, 109.2, 109.6), (109.6, 109.9, 107.0, 107.9), (107.9, 109.7, 107.4, 109.4)]


def continuation_long(upto: int = None) -> Arr:
    p = _prefix_range()
    rows = CONT_ROWS if upto is None else CONT_ROWS[:upto]
    return concat(p, bars(rows, t0=float(p["t"][-1]) + W))


CONT_LEVELS = [{"p": 116.3, "side": "high", "kind": "M15SW", "strength": 1, "taken_ts": None, "known": 0.0}, {"p": 122.0, "side": "high", "kind": "H4SW", "strength": 1, "taken_ts": None, "known": 0.0},
               {"p": 130.0, "side": "high", "kind": "PDH", "strength": 1, "taken_ts": None, "known": 0.0}]


def htf_up() -> Arr:
    return zigzag([100, 110, 104, 118, 111, 126, 119, 134, 127, 142], per_leg=6)


def htf_down() -> Arr:
    return zigzag([142, 130, 136, 122, 129, 114, 121, 106, 113, 98], per_leg=6)

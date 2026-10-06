"""Синтетичні свічки для тестів Office2 LIVE: фон + послідовність «імпульс → відкат (атаки в зону) → стиснення → LH → displacement → утримання» (LONG) і дзеркало (SHORT)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import brain as B  # noqa: E402
from office2 import features as F  # noqa: E402

T0 = 1_790_000_000 // 900 * 900


def _bars_from_closes(closes, wick=0.0006, start_t=T0, base_o=None):
    closes = np.asarray(closes, dtype=np.float64)
    o = np.r_[base_o if base_o is not None else closes[0], closes[:-1]]
    n = len(closes)
    rng = np.random.default_rng(11)
    h = np.maximum(o, closes) * (1 + rng.uniform(0.0003, 0.0016, n))   # різні тіні: без точних рівностей екстремумів (фрактали строгі)
    l = np.minimum(o, closes) * (1 - rng.uniform(0.0003, 0.0016, n))
    return {"t": start_t + 900.0 * np.arange(n), "o": o, "h": h, "l": l, "c": closes, "v": np.full(n, 100.0), "tbv": np.full(n, 50.0)}


def seg(path, a, b, n):
    return list(np.linspace(a, b, n + 1)[1:])


def pattern_closes(sg=1, seed=5):
    """Повертає список закриттів M15 (LONG-координати; для SHORT дзеркалиться відносно 100 у викликаючому коді)."""
    rng = np.random.default_rng(seed)
    base = list(100 + np.cumsum(rng.normal(0, 0.05, 2800)))
    base = [100 + (x - 100) * 1.0 for x in base]
    c = base + seg(None, base[-1], 100.0, 6)
    c += [100.0 + 0.03 * np.sin(i) for i in range(8)]                   # база/origin
    c += seg(None, c[-1], 110.0, 36)                                     # імпульс +10%
    c += seg(None, c[-1], 104.0, 8) + seg(None, 104.0, 105.0, 4)          # перший відкат
    c += seg(None, c[-1], 100.55, 16)                                     # атака 1 (low у зоні origin)
    c += seg(None, c[-1], 103.4, 8)                                       # відскок (lower-high 1)
    c += seg(None, c[-1], 100.75, 10)                                     # атака 2 (слабша: low вищий)
    c += seg(None, c[-1], 102.0, 5)
    c += [102.0 + 0.04 * (-1) ** i for i in range(8)]                    # стиснення
    return c


def build(sg=1, upto_extra=None, seed=5):
    """M15-масив (та контекст) для сценарію; повертає (m15, idx) де idx — словник ключових індексів."""
    c = pattern_closes(sg, seed)
    bars = _bars_from_closes(c)
    n0 = len(c)
    return bars, n0

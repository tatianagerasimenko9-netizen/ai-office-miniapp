"""Порівняння TP vs SL за ознаками, контрфактуальні фільтри з ЦІНОЮ пропущених виграшів, walk-forward.
Правило проходить лише якщо ефект має один знак на навчальному і тестовому відрізках, вибірка ≥ N_MIN, а довірчий інтервал різниці не містить нуль.
Інакше — INSUFFICIENT / NOT_SUPPORTED. Це не фільтри для впровадження, а перевірка гіпотез."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from office2.learning import pnl as P

N_MIN = 10
BOOT = 2000
SEED = 7


def wilson(k: int, n: int, z: float = 1.96) -> Optional[List[float]]:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return [round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)]


def _mean(x):
    return sum(x) / len(x) if x else None


def boot_diff(a: List[float], b: List[float], reps: int = BOOT, seed: int = SEED) -> Optional[List[float]]:
    if len(a) < 2 or len(b) < 2:
        return None
    import numpy as np

    rnd = np.random.default_rng(seed)
    xa, xb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    ma = xa[rnd.integers(0, len(xa), size=(reps, len(xa)))].mean(axis=1)
    mb = xb[rnd.integers(0, len(xb), size=(reps, len(xb)))].mean(axis=1)
    d = np.sort(ma - mb)
    return [round(float(d[int(0.025 * reps)]), 3), round(float(d[int(0.975 * reps) - 1]), 3)]


def resolved(trades: List[Dict[str, Any]], model: str = "A") -> List[Dict[str, Any]]:
    return [t for t in trades if P.net(t, model) is not None]


def contrast(trades: List[Dict[str, Any]], pred: Callable[[Dict[str, Any]], bool], model: str = "A") -> Dict[str, Any]:
    rs = resolved(trades, model)
    with_f = [P.net(t, model) for t in rs if pred(t)]
    without = [P.net(t, model) for t in rs if not pred(t)]
    sl = [t for t in rs if t["first"] == "SL"]
    tp = [t for t in rs if t["first"] == "TP1"]
    out = {"n_with": len(with_f), "n_without": len(without),
           "freq_in_SL": round(sum(1 for t in sl if pred(t)) / len(sl), 3) if sl else None,
           "freq_in_TP": round(sum(1 for t in tp if pred(t)) / len(tp), 3) if tp else None,
           "win_with": wilson(sum(1 for x in with_f if x > 0), len(with_f)), "win_without": wilson(sum(1 for x in without if x > 0), len(without)),
           "mean_r_with": round(_mean(with_f), 3) if with_f else None, "mean_r_without": round(_mean(without), 3) if without else None}
    ci = boot_diff(with_f, without)
    out["diff_ci95"] = ci
    if len(with_f) < N_MIN or len(without) < N_MIN:
        out["verdict"] = "INSUFFICIENT"
    elif ci and (ci[0] > 0 or ci[1] < 0):
        out["verdict"] = "SUPPORTED_BENEFICIAL" if ci[0] > 0 else "SUPPORTED_HARMFUL"
    else:
        out["verdict"] = "NOT_SUPPORTED"
    return out


def filter_effect(trades: List[Dict[str, Any]], skip: Callable[[Dict[str, Any]], bool], model: str = "A") -> Dict[str, Any]:
    """Що буде, якщо ПРОПУСКАТИ угоди з ознакою: скільки збитків уникнемо і скільки виграшів втратимо (ціна фільтра)."""
    rs = resolved(trades, model)
    skipped = [t for t in rs if skip(t)]
    kept = [t for t in rs if not skip(t)]
    lost_wins = [t for t in skipped if P.net(t, model) > 0]
    avoided = [t for t in skipped if P.net(t, model) <= 0]
    before = sum(P.net(t, model) for t in rs)
    after = sum(P.net(t, model) for t in kept)
    return {"trades_before": len(rs), "trades_after": len(kept), "skipped": len(skipped),
            "losses_avoided": len(avoided), "wins_lost": len(lost_wins),
            "sum_r_before": round(before, 2), "sum_r_after": round(after, 2), "delta_r": round(after - before, 2),
            "delta_usd": round((after - before) * P.RISK_USD, 1),
            "mean_r_before": round(before / len(rs), 3) if rs else None, "mean_r_after": round(after / len(kept), 3) if kept else None}


def walk_forward(trades: List[Dict[str, Any]], skip: Callable[[Dict[str, Any]], bool], model: str = "A", train_frac: float = 0.6) -> Dict[str, Any]:
    ts = sorted(trades, key=lambda t: t.get("created_ts") or 0)
    k = int(len(ts) * train_frac)
    a, b = ts[:k], ts[k:]
    ea, eb = filter_effect(a, skip, model), filter_effect(b, skip, model)
    enough = ea["skipped"] >= N_MIN and eb["skipped"] >= N_MIN
    same_sign = ea["delta_r"] * eb["delta_r"] > 0
    if not enough:
        status = "INSUFFICIENT"
    elif same_sign and ea["delta_r"] > 0:
        status = "CONFIRMED_ON_BOTH"
    elif same_sign:
        status = "HARMFUL_ON_BOTH"
    else:
        status = "NOT_STABLE"
    return {"train": ea, "test": eb, "status": status}

"""Робота над помилками на ВСІЙ історії: «ознака → результат» з перевіркою на незалежному (пізнішому) періоді.
Строгі правила, задані наперед: ≥ 60 подій у клітинці; навчальна частина = перші 60 % за часом, тест = останні 40 %; «стійкою» вважається клітинка, якщо знак середнього R однаковий на обох частинах,
|середній R| ≥ 0,10 на кожній, 95 % bootstrap-інтервал на всіх подіях не містить 0 і клітинок перевірено не більше MAX_CELLS (поправка на множинні порівняння: інтервал 99,5 %).
Фільтр-кандидат будується ЛИШЕ на навчальній частині (клітинки з середнім ≤ −0,15 R і n ≥ 40) і оцінюється на тестовій — це єдине чесне свідчення користі правила."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

FEATURES = ("dir", "kind", "ev_class", "retest_not_fresh", "lvl_class", "lvl_strength", "mirror_for", "bulkowski_for", "wyckoff_defined", "pd", "htf_class", "counter_trend",
            "risk_atr", "tp1_r", "cost_heavy", "session", "weekend", "btc_1h", "rs_1h")
MIN_N = 60
MIN_ABS = 0.10
TRAIN_FRAC = 0.6


def _rows(rows: List[Dict[str, Any]], source: str = "BRAIN", variant: str = "V0_current") -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        if r.get("source") != source or not r.get("f"):
            continue
        x = (r.get("variants") or {}).get(variant) or {}
        if x.get("r_net") is None:
            continue
        out.append({"ts": r["ts_bar"], "r": float(x["r_net"]), "tp": x.get("outcome") == "TP1", "sl": x.get("outcome") == "SL", "f": r["f"], "sym": r.get("symbol")})
    out.sort(key=lambda e: e["ts"])
    return out


def _ci(xs: List[float], q: float = 0.025, n: int = 1500, seed: int = 11) -> Optional[Tuple[float, float]]:
    if len(xs) < 10:
        return None
    a = np.array(xs)
    rnd = np.random.default_rng(seed)
    ms = np.sort(rnd.choice(a, size=(n, len(a)), replace=True).mean(axis=1))
    return float(ms[int(q * n)]), float(ms[int((1 - q) * n) - 1])


def cell_table(rs: List[Dict[str, Any]], features=None) -> List[Dict[str, Any]]:
    features = features or FEATURES
    k = int(len(rs) * TRAIN_FRAC)
    tr, te = rs[:k], rs[k:]
    cells: Dict[Tuple[str, str], List[int]] = {}
    for i, e in enumerate(rs):
        for ft in features:
            cells.setdefault((ft, str(e["f"].get(ft))), []).append(i)
    tested = [(key, ix) for key, ix in cells.items() if len(ix) >= MIN_N and len(ix) < len(rs) * 0.97]
    m = max(1, len(tested))
    q = 0.025 / m                                    # поправка Бонферроні на кількість клітинок
    out = []
    for (ft, val), ix in sorted(tested):
        xs = [rs[i]["r"] for i in ix]
        a = [rs[i]["r"] for i in ix if i < k]
        b = [rs[i]["r"] for i in ix if i >= k]
        rest = [rs[i]["r"] for i in range(len(rs)) if i not in set(ix)]
        ci = _ci(xs, q=max(q, 0.0005))
        mean = float(np.mean(xs))
        same = bool(a and b and np.mean(a) * np.mean(b) > 0 and abs(np.mean(a)) >= MIN_ABS and abs(np.mean(b)) >= MIN_ABS)
        stable = bool(same and ci and (ci[0] > 0 or ci[1] < 0))
        out.append({"feature": ft, "value": val, "n": len(ix), "tp": sum(1 for i in ix if rs[i]["tp"]), "sl": sum(1 for i in ix if rs[i]["sl"]), "mean_r": round(mean, 3),
                    "rest_mean_r": round(float(np.mean(rest)), 3) if rest else None, "train_n": len(a), "train_mean": round(float(np.mean(a)), 3) if a else None,
                    "test_n": len(b), "test_mean": round(float(np.mean(b)), 3) if b else None, "ci_bonferroni": [round(ci[0], 3), round(ci[1], 3)] if ci else None,
                    "status": ("STABLE_NEGATIVE" if mean < 0 else "STABLE_POSITIVE") if stable else "NOT_STABLE"})
    return out


def train_test_filter(rs: List[Dict[str, Any]], neg_cut: float = -0.15, min_n: int = 40, features=None) -> Dict[str, Any]:
    features = features or FEATURES
    """Виключення клітинок, що були погані НА НАВЧАННІ, перевіряється на тесті. Повертає базу й відфільтроване на тесті."""
    k = int(len(rs) * TRAIN_FRAC)
    tr, te = rs[:k], rs[k:]
    bad = []
    cells: Dict[Tuple[str, str], List[float]] = {}
    for e in tr:
        for ft in features:
            cells.setdefault((ft, str(e["f"].get(ft))), []).append(e["r"])
    for key, xs in cells.items():
        if len(xs) >= min_n and len(xs) < len(tr) * 0.9 and float(np.mean(xs)) <= neg_cut:
            bad.append(key)

    def keep(e):
        return not any(str(e["f"].get(ft)) == val for ft, val in bad)

    kept = [e for e in te if keep(e)]
    dropped = [e for e in te if not keep(e)]
    f = lambda xs: {"n": len(xs), "mean_r": round(float(np.mean([e["r"] for e in xs])), 3) if xs else None, "sum_r": round(float(sum(e["r"] for e in xs)), 1), "usd_at_10": round(float(sum(e["r"] for e in xs)) * 10, 0)}  # noqa: E731
    return {"excluded_cells_from_train": [f"{a}={b}" for a, b in sorted(bad)], "train": f(tr), "test_all": f(te), "test_kept": f(kept), "test_dropped": f(dropped)}


def study(rows: List[Dict[str, Any]], source: str = "BRAIN") -> Dict[str, Any]:
    rs = _rows(rows, source)
    if len(rs) < 100:
        return {"status": "INSUFFICIENT", "n": len(rs)}
    cells = cell_table(rs)
    stable = [c for c in cells if c["status"] != "NOT_STABLE"]
    return {"status": "OK", "n": len(rs), "span": [rs[0]["ts"], rs[-1]["ts"]], "overall_mean_r": round(float(np.mean([e["r"] for e in rs])), 3),
            "overall_win": round(sum(1 for e in rs if e["tp"]) / max(1, sum(1 for e in rs if e["tp"] or e["sl"])), 3), "cells_tested": len(cells), "stable": stable,
            "worst": sorted(cells, key=lambda c: c["mean_r"])[:8], "best": sorted(cells, key=lambda c: -c["mean_r"])[:8], "all": cells, "oos_filter": train_test_filter(rs)}


def study_rows(rs: List[Dict[str, Any]], features) -> Dict[str, Any]:
    """Те саме для готових рядків {ts,r,tp,sl,f} (старий Лев з ознаками, відновленими зі свічок)."""
    rs = sorted(rs, key=lambda e: e["ts"])
    if len(rs) < 100:
        return {"status": "INSUFFICIENT", "n": len(rs)}
    cells = cell_table(rs, features)
    return {"status": "OK", "n": len(rs), "span": [rs[0]["ts"], rs[-1]["ts"]], "overall_mean_r": round(float(np.mean([e["r"] for e in rs])), 3),
            "overall_win": round(sum(1 for e in rs if e["tp"]) / max(1, sum(1 for e in rs if e["tp"] or e["sl"])), 3), "cells_tested": len(cells),
            "stable": [c for c in cells if c["status"] != "NOT_STABLE"], "all": cells, "oos_filter": train_test_filter(rs, features=features)}

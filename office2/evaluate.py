"""Оцінка кандидатів: first-touch на 1m, геометрична база r/(r+t), надлишок із кластерним бутстрепом (symbol+день), train/test за часом і hold-out символів,
абляція етапів, сіднійний контроль (випадкові входи) і портфельний Risk Manager."""
from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from office2 import pipeline as P
from office2 import sim as S


def evaluate(cands: List[dict], ctxs: Dict[str, Dict[str, Any]], p: P.Params, fee_rt_pct: float = S.FEE_RT_DEFAULT) -> List[dict]:
    out: List[dict] = []
    for c in cands:
        m1 = ctxs[c["symbol"]]["m1"]
        res = S.first_touch(m1, c["i1"], c["dir"], c["entry"], c["sl"], c["tp"], p.horizon_sec)
        if not res["complete"]:
            continue   # немає повного горизонту — не рахуємо (нема даних = не перевірено)
        r = dict(c)
        r.update(res)
        ex = S.excursions(m1, c["i1"], c["dir"], c["entry"], abs(c["entry"] - c["sl"]), p.horizon_sec)
        r["mfe_full_r"], r["mae_full_r"] = ex["mfe_atr"], ex["mae_atr"]      # MFE/MAE за ВЕСЬ горизонт у R (не обрізані TP/SL); лише label
        r["r_net"] = S.net_r(res["r_gross"], c["risk_pct"], fee_rt_pct)
        r["t_exit"] = c["t_entry"] + res["ttr_sec"]
        r["day"] = int(c["t_entry"] // 86400)
        r["base"] = 1.0 / (1.0 + c["rr"])   # r/(r+t) при t = rr·r
        out.append(r)
    return out


def _bootstrap(rows: List[dict], stat: Callable[[List[dict]], float], B: int = 400, seed: int = 11) -> Tuple[float, float]:
    cl: Dict[Tuple[str, int], List[dict]] = defaultdict(list)
    for r in rows:
        cl[(r["symbol"], r["day"])].append(r)
    keys = list(cl)
    if len(keys) < 8:
        return float("nan"), float("nan")
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        samp = [x for k in (rnd.choice(keys) for _ in keys) for x in cl[k]]
        vals.append(stat(samp))
    vals.sort()
    return vals[int(B * 0.025)], vals[int(B * 0.975)]


def _excess(rows: List[dict]) -> float:
    rs = [r for r in rows if r["outcome"] in ("TP", "SL")]
    if not rs:
        return float("nan")
    return sum(1 for r in rs if r["outcome"] == "TP") / len(rs) - sum(r["base"] for r in rs) / len(rs)


def _mean_r(rows: List[dict]) -> float:
    return sum(r["r_net"] for r in rows) / len(rows) if rows else float("nan")


def summarize(rows: List[dict]) -> Dict[str, Any]:
    rs = [r for r in rows if r["outcome"] in ("TP", "SL")]
    n = len(rows)
    out: Dict[str, Any] = {"n": n, "n_res": len(rs), "clusters": len({(r["symbol"], r["day"]) for r in rows}), "symbols": len({r["symbol"] for r in rows})}
    if not rs:
        out.update(hit=float("nan"), base=float("nan"), excess=float("nan"), lo=float("nan"), hi=float("nan"), mean_r=_mean_r(rows), r_lo=float("nan"), r_hi=float("nan"), to=float("nan"))
        return out
    out["hit"] = sum(1 for r in rs if r["outcome"] == "TP") / len(rs)
    out["base"] = sum(r["base"] for r in rs) / len(rs)
    out["excess"] = out["hit"] - out["base"]
    out["lo"], out["hi"] = _bootstrap(rows, _excess)
    out["mean_r"] = _mean_r(rows)
    out["r_lo"], out["r_hi"] = _bootstrap(rows, _mean_r)
    out["to"] = 1 - len(rs) / n
    return out


HOLDOUT_SALT = "office2-holdout-v2"   # v1 «підглянуто» у run №4 (друкувалась колонка hold-out) — сіль змінено до будь-яких висновків


def is_holdout(symbol: str) -> bool:
    """≈1/3 символів — hold-out: у режимі explore НЕ ЗАВАНТАЖУЮТЬСЯ взагалі; відкриваються лише режимом final для зафіксованої версії."""
    return int(hashlib.md5((HOLDOUT_SALT + symbol).encode()).hexdigest(), 16) % 3 == 0


def cut_day(rows: List[dict], train_frac: float = 0.6) -> Optional[int]:
    days = sorted({r["day"] for r in rows})
    return days[int(len(days) * train_frac)] if len(days) > 1 else None


def split(rows: List[dict], train_frac: float = 0.6) -> Dict[str, List[dict]]:
    days = sorted({r["day"] for r in rows})
    if not days:
        return {"all": [], "train": [], "test": []}
    cut = days[int(len(days) * train_frac)] if len(days) > 1 else days[0]
    hold = is_holdout
    train = [r for r in rows if r["day"] < cut]
    test = [r for r in rows if r["day"] >= cut]
    return {"all": rows, "train": train, "test": test}


STAGES: Dict[str, Callable[[dict], bool]] = {
    "S1 HTF (H4 режим не проти)": lambda r: r["htf_ok"],
    "S2 BTC (4 год не проти)": lambda r: r["btc_ok"],
    "S7 потік (taker-дельта у бік)": lambda r: r["flow_ok"],
    "S3 сильний рівень (EQ/D1/PD/PW)": lambda r: r["lvl_strength"] >= 2 or r["lvl_kind"] in ("D1SW", "PDH", "PDL", "PWH", "PWL"),
}


def ablation(rows: List[dict]) -> List[Tuple[str, List[dict]]]:
    """Рядки таблиці: (назва, угоди). База = тригер 'reclaim'; окремо тригер 'choch'; кожен етап окремо; усі етапи разом; комбіновані."""
    base = [r for r in rows if r["trigger"] == "reclaim"]
    ch = [r for r in rows if r["trigger"] == "choch"]
    out: List[Tuple[str, List[dict]]] = [("БАЗА: sweep+reclaim → SL за екстремумом+буфер → TP наступна ліквідність (етапи 3–5, 9–10)", base),
                                         ("+ S6 тригер CHoCH замість reclaim", ch)]
    for name, f in STAGES.items():
        out.append((f"БАЗА + {name}", [r for r in base if f(r)]))
    allf = [r for r in base if all(f(r) for f in (STAGES["S1 HTF (H4 режим не проти)"], STAGES["S2 BTC (4 год не проти)"], STAGES["S7 потік (taker-дельта у бік)"]))]
    out.append(("БАЗА + S1 + S2 + S7", allf))
    out.append(("CHoCH + S1 + S2 + S7", [r for r in ch if r["htf_ok"] and r["btc_ok"] and r["flow_ok"]]))
    out.append(("БАЗА, лише type A (wick-sweep)", [r for r in base if r["etype"] == "A"]))
    out.append(("БАЗА, лише type B (failed breakout)", [r for r in base if r["etype"] == "B"]))
    return out


def random_control(ctxs: Dict[str, Dict[str, Any]], n_per_symbol: int, p: P.Params, seed: int = 5, fee_rt_pct: float = S.FEE_RT_DEFAULT) -> List[dict]:
    """Сіднійний контроль: випадкові моменти й напрямок; SL = 2·ATR15, TP = 3·ATR15 (база r/(r+t) = 0,4). Очікуваний надлишок ≈ 0, інакше симулятор/база зміщені."""
    rnd = random.Random(seed)
    cands: List[dict] = []
    for sym, ctx in ctxs.items():
        m15, m1, atr15 = ctx["m15"], ctx["m1"], ctx["atr15"]
        nb = len(m15["t"])
        for _ in range(n_per_symbol):
            j = rnd.randrange(30, max(31, nb - 100))
            if j >= nb or np.isnan(atr15[j]):
                continue
            t_trig = float(m15["t"][j] + 900)
            ie = P._entry_index(m1, t_trig)
            if ie is None:
                continue
            entry = float(m1["o"][ie])
            a = float(atr15[j])
            if a <= 0 or 2 * a / float(m1["o"][ie]) * 100 < 0.05:
                continue   # виродженний ATR (плоска ціна): без даних, не рахуємо
            d = rnd.choice(["LONG", "SHORT"])
            sg = 1.0 if d == "LONG" else -1.0
            sl, tp = entry - sg * 2 * a, entry + sg * 3 * a
            cands.append({"symbol": sym, "dir": d, "t_entry": t_trig, "i1": ie, "entry": entry, "sl": sl, "tp": tp, "risk_pct": 2 * a / entry * 100, "rr": 1.5, "trigger": "control",
                          "etype": "-", "lvl_kind": "-", "lvl_strength": 0, "htf_ok": True, "btc_ok": True, "flow_ok": True, "reg4": 0, "regd": 0, "btc4": None, "atr_pct": a / entry * 100})
    return cands


def mirror(c: dict) -> dict:
    """H3: дзеркальна угода — той самий вхід, протилежний напрямок, SL/TP дзеркально відносно входу (ті самі відстані r і t; база r/(r+t) та сама)."""
    m = dict(c)
    m["dir"] = "SHORT" if c["dir"] == "LONG" else "LONG"
    m["sl"] = 2 * c["entry"] - c["sl"]
    m["tp"] = 2 * c["entry"] - c["tp"]
    m["trigger"] = "mirror"
    return m


def diff_ci(a: List[dict], b: List[dict], B: int = 400, seed: int = 21) -> Tuple[float, float, float]:
    """Різниця середніх R (a − b) і кластерний бутстреп за (symbol, день) на об'єднаній множині кластерів."""
    if not a or not b:
        return float("nan"), float("nan"), float("nan")
    cl: Dict[Tuple[str, int], Tuple[List[dict], List[dict]]] = {}
    for r in a:
        cl.setdefault((r["symbol"], r["day"]), ([], []))[0].append(r)
    for r in b:
        cl.setdefault((r["symbol"], r["day"]), ([], []))[1].append(r)
    keys = list(cl)
    pt = _mean_r(a) - _mean_r(b)
    if len(keys) < 8:
        return pt, float("nan"), float("nan")
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        sa: List[dict] = []
        sb: List[dict] = []
        for k in (rnd.choice(keys) for _ in keys):
            sa += cl[k][0]
            sb += cl[k][1]
        if sa and sb:
            vals.append(_mean_r(sa) - _mean_r(sb))
    vals.sort()
    return pt, vals[int(len(vals) * 0.025)], vals[int(len(vals) * 0.975)]


def _mm(rows: List[dict]) -> str:
    f = [r["mfe_full_r"] for r in rows if "mfe_full_r" in r]
    a = [r["mae_full_r"] for r in rows if "mae_full_r" in r]
    return f"{float(np.median(f)):.2f} / {float(np.median(a)):.2f}" if f and a else "—"


def fmt(x: float, pct: bool = True, signed: bool = False) -> str:
    if x != x:
        return "—"
    v = x * 100 if pct else x
    return f"{v:+.1f}" if signed else f"{v:.1f}"


def table(title: str, groups: Sequence[Tuple[str, List[dict]]], split_cols: bool = True, train_only: bool = False, cut_day: Optional[int] = None) -> List[str]:
    """train_only: у таблиці лише train-рядки (test ВІДКРИТИЙ НЕ показується) — для гіпотез, що ще не зафіксовані."""
    hdr = "| Варіант | N (кластерів) | TP/SL | таймаут | факт | база | надлишок п.п. (95% ІВ) | R чистий після комісій (95% ІВ) | MFE/MAE R (медіана, весь горизонт) |" + (" train надл. (N) | test надл. (N) |" if not train_only else "")
    L = [f"\n### {title}\n", hdr, "|---|---|---|---|---|---|---|---|---|" + ("---|---|" if not train_only else "")]
    for name, rows in groups:
        if train_only and cut_day is not None:
            rows = [r for r in rows if r["day"] < cut_day]
        s = summarize(rows)
        if not rows:
            L.append(f"| {name} | 0 | — | — | — | — | — | — | — |" + ("" if train_only else " — | — |"))
            continue
        sp = split(rows)
        cells = []
        for k in ("train", "test"):
            ss = summarize(sp[k]) if len(sp[k]) >= 15 else None
            cells.append(f"{fmt(ss['excess'], signed=True)} ({ss['n_res']})" if ss and ss["n_res"] else "—")
        ci = "—" if s["lo"] != s["lo"] else f"{fmt(s['lo'], signed=True)}…{fmt(s['hi'], signed=True)}"
        rci = "—" if s["r_lo"] != s["r_lo"] else f"{s['r_lo']:+.2f}…{s['r_hi']:+.2f}"
        nres = s["n_res"]
        tp = sum(1 for r in rows if r["outcome"] == "TP")
        L.append(f"| {name} | {s['n']} ({s['clusters']}) | {tp}/{nres - tp} | {s['n'] - nres} | {fmt(s['hit'])}% | {fmt(s['base'])}% | {fmt(s['excess'], signed=True)} ({ci}) | {s['mean_r']:+.3f} ({rci}) | {_mm(rows)} |" + ("" if train_only else f" {cells[0]} | {cells[1]} |"))
    return L

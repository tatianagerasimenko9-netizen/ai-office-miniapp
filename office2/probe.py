"""Раунд 3: чи містить інформація ДО входу стабільний торговий сигнал? Probe, а не торговий мозок.

Спостереження: проколи рівнів (A/B1/ACCEPT) і КОНТРОЛЬНІ точки біля рівнів без проколу. Features — лише закриті бари на момент рішення.
Labels — наслідки торгової ситуації (TP-before-SL у пробній геометрії, net R після комісій, MFE/MAE, інвалідація); TRAP — лише мітка результату.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from office2 import features as F
from office2 import sim as S
from office2.pipeline import Params, _btc_ret4h, _entry_index
from office2.scenarios import pierces

G_TP, G_SL = 2.0, 1.0       # пробна геометрія G1 (в ATR15), апріорі; не оптимізується
FEE_RT = 0.10

FEATURES = ["rel4", "reld", "btc_al", "btc_na", "imb", "imb3", "volr", "body", "rng", "depth", "strength", "room", "volreg", "mom1h", "mom4h",
            "asia", "london", "ny", "brk", "k_d1", "k_pd", "k_pw", "b_A", "b_B1", "b_ACC", "is_pierce", "age"]


def _controls(ctx: Dict[str, Any], p: Params) -> List[dict]:
    """Перший бар, де закриття ≤0,3·ATR15 від активного рівня зі «своєї» сторони, а рівень цим баром не проколото. Рівень не споживається."""
    m15, levels, atr = ctx["m15"], ctx["levels"], ctx["atr15"]
    nb = len(m15["t"])
    h, l, c, t = m15["h"], m15["l"], m15["c"], m15["t"]
    out: List[dict] = []
    active: List[dict] = []
    ptr = 0
    for j in range(nb):
        while ptr < len(levels) and levels[ptr]["known"] <= t[j]:
            lv = levels[ptr]
            ptr += 1
            if j > 0 and ((lv["side"] == "high" and c[j - 1] > lv["p"]) or (lv["side"] == "low" and c[j - 1] < lv["p"])):
                continue
            active.append({"lv": lv, "done": False})
        keep = []
        for a in active:
            lv = a["lv"]
            pr = lv["p"]
            high = lv["side"] == "high"
            pierced = h[j] > pr if high else l[j] < pr
            if pierced:
                continue            # рівень проколото: контрольну подію не створюємо, і рівень виходить з пулу
            if not a["done"] and not np.isnan(atr[j]) and abs(c[j] - pr) <= 0.3 * atr[j] and j >= 20:
                a["done"] = True
                out.append({"lv": lv, "d": j, "brk": 1 if high else -1, "behavior": "CTRL", "ext_d": float(c[j])})
            keep.append(a)
        active = keep
    return out


def build_observations(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]], p: Params = Params()) -> List[dict]:
    m15, m1, atr15, levels = ctx["m15"], ctx["m1"], ctx["atr15"], ctx["levels"]
    nb = len(m15["t"])
    evs: List[dict] = []
    for ev in pierces(ctx, p):
        e = dict(ev)
        e["future_trap"] = ev["behavior"] == "TRAP"
        e["behavior"] = "ACCEPT" if ev["behavior"] == "TRAP" else ev["behavior"]   # decision-time поведінка; TRAP лише мітка
        evs.append(e)
    evs.extend(_controls(ctx, p))
    obs: List[dict] = []
    for ev in evs:
        d = ev["d"]
        if d < 100 or d + 1 >= nb or np.isnan(atr15[d]) or atr15[d] <= 0:
            continue
        a = float(atr15[d])
        b = ev["brk"]
        lv = ev["lv"]
        t_d = float(m15["t"][d] + 900)
        k4, kd = F.last_closed(ctx["h4"], 4 * 3600, t_d), F.last_closed(ctx["d1"], F.DAY, t_d)
        reg4 = int(ctx["reg4"][k4]) if k4 >= 0 else 0
        regd = int(ctx["regd"][kd]) if kd >= 0 else 0
        btc4 = _btc_ret4h(btc, float(m15["t"][d])) if symbol != "BTCUSDT" else None
        v = m15["v"]
        vol_prev = float(v[d - 20:d].mean()) or 1.0
        imb = (2 * m15["tbv"][d] - v[d]) / max(v[d], 1e-12) * b
        imb3 = float(np.mean((2 * m15["tbv"][d - 2:d + 1] - v[d - 2:d + 1]) / np.maximum(v[d - 2:d + 1], 1e-12))) * b
        room = 20.0
        for L2 in levels:
            if L2["known"] > t_d:
                break
            if (b > 0 and L2["side"] == "high" and L2["p"] > lv["p"] + 0.05 * a) or (b < 0 and L2["side"] == "low" and L2["p"] < lv["p"] - 0.05 * a):
                room = min(room, abs(L2["p"] - lv["p"]) / a)
        hour = int(t_d % 86400 // 3600)
        f = {"rel4": reg4 * b, "reld": regd * b, "btc_al": float(np.clip((btc4 or 0.0) * b, -3, 3)), "btc_na": 1.0 if btc4 is None else 0.0,
             "imb": float(imb), "imb3": imb3, "volr": float(np.log(max(v[d] / vol_prev, 1e-3))), "body": float((m15["c"][d] - m15["o"][d]) * b / a),
             "rng": float((m15["h"][d] - m15["l"][d]) / a), "depth": float((ev["ext_d"] - lv["p"]) * b / a) if ev["behavior"] != "CTRL" else float((m15["c"][d] - lv["p"]) * b / a),
             "strength": float(lv["strength"]), "room": float(room),
             "volreg": float(np.log(max(a / float(np.nanmean(atr15[d - 96:d])), 1e-3))) if d >= 96 else 0.0,
             "mom1h": float((m15["c"][d] - m15["c"][d - 4]) * b / a), "mom4h": float((m15["c"][d] - m15["c"][d - 16]) * b / a),
             "asia": 1.0 if hour < 8 else 0.0, "london": 1.0 if 8 <= hour < 13 else 0.0, "ny": 1.0 if 13 <= hour < 21 else 0.0, "brk": float(b),
             "k_d1": 1.0 if lv["kind"] == "D1SW" else 0.0, "k_pd": 1.0 if lv["kind"] in ("PDH", "PDL") else 0.0, "k_pw": 1.0 if lv["kind"] in ("PWH", "PWL") else 0.0,
             "b_A": 1.0 if ev["behavior"] == "A" else 0.0, "b_B1": 1.0 if ev["behavior"] == "B1" else 0.0, "b_ACC": 1.0 if ev["behavior"] == "ACCEPT" else 0.0,
             "is_pierce": 0.0 if ev["behavior"] == "CTRL" else 1.0, "age": float(np.log1p(max(t_d - lv["known"], 0.0) / 3600.0))}
        ie = _entry_index(m1, t_d)
        if ie is None:
            continue
        entry = float(m1["o"][ie])
        row: Dict[str, Any] = {"symbol": symbol, "day": int(t_d // 86400), "t": t_d, "behavior": ev["behavior"], "future_trap": bool(ev.get("future_trap", False)), "f": f, "brk": b}
        okk = True
        for nm, direction in (("cont", "LONG" if b > 0 else "SHORT"), ("rev", "SHORT" if b > 0 else "LONG")):
            sgn = 1.0 if direction == "LONG" else -1.0
            sl, tp = entry - sgn * G_SL * a, entry + sgn * G_TP * a
            r = S.first_touch(m1, ie, direction, entry, sl, tp, 24 * 3600)
            if not r["complete"]:
                okk = False
                break
            risk_pct = G_SL * a / entry * 100.0
            row[f"{nm}_tp"] = 1.0 if r["outcome"] == "TP" else 0.0
            row[f"{nm}_sl"] = 1.0 if r["outcome"] == "SL" else 0.0
            row[f"{nm}_netr"] = float(S.net_r(r["r_gross"], risk_pct, FEE_RT))
            ex = S.excursions(m1, ie, direction, entry, a, 24 * 3600)
            row[f"{nm}_mfe"], row[f"{nm}_mae"], row[f"{nm}_tmfe"], row[f"{nm}_tmae"] = ex["mfe_atr"], ex["mae_atr"], ex["t_mfe_min"], ex["t_mae_min"]
        if not okk:
            continue
        # інвалідація продовження: закриття назад за рівень протягом 4 барів після рішення (лише label)
        inv = 0.0
        for m in range(d + 1, min(nb, d + 5)):
            if (b > 0 and m15["c"][m] < lv["p"]) or (b < 0 and m15["c"][m] > lv["p"]):
                inv = 1.0
                break
        row["inval"] = inv
        obs.append(row)
    return obs


# ---------------------------------------------------------------- математика probe (numpy)
def _avg_rank(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ranks = np.empty(len(x))
    i = 0
    n = len(x)
    while i < n:
        j = i
        while j + 1 < n and xs[j + 1] == xs[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def auc(score: np.ndarray, y: np.ndarray) -> float:
    pos = y > 0.5
    n1, n0 = int(pos.sum()), int((~pos).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = _avg_rank(score)
    return float((r[pos].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 5 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(_avg_rank(x), _avg_rank(y))[0, 1])


def matrix(obs: List[dict]) -> np.ndarray:
    return np.array([[o["f"][k] for k in FEATURES] for o in obs], dtype=float)


def ridge_fit(X: np.ndarray, y: np.ndarray, lam: float = 10.0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    Z = (X - mu) / sd
    A = Z.T @ Z + lam * np.eye(Z.shape[1])
    w = np.linalg.solve(A, Z.T @ (y - y.mean()))
    return w, mu, sd


def ridge_score(X: np.ndarray, model: Tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    w, mu, sd = model
    return ((X - mu) / sd) @ w


def cluster_ci(obs: List[dict], fn, B: int = 300, seed: int = 5) -> Tuple[float, float]:
    cl: Dict[Tuple[str, int], List[int]] = {}
    for i, o in enumerate(obs):
        cl.setdefault((o["symbol"], o["day"]), []).append(i)
    keys = list(cl)
    if len(keys) < 8:
        return float("nan"), float("nan")
    import random
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        idx = [i for k in (rnd.choice(keys) for _ in keys) for i in cl[k]]
        v = fn(idx)
        if v == v:
            vals.append(v)
    vals.sort()
    return (vals[int(len(vals) * 0.025)], vals[int(len(vals) * 0.975)]) if vals else (float("nan"), float("nan"))


# ---------------------------------------------------------------- звіт
def _fmt(x: float, n: int = 3) -> str:
    return "—" if x != x else f"{x:+.{n}f}"


def report(obs: List[dict], cut: Optional[int], open_test: bool) -> List[str]:
    L: List[str] = ["\n## Раунд 3: чи містить інформація ДО входу стабільний торговий сигнал? (probe; HYPOTHESES.md, раунд 3)\n"]
    if cut is None or not obs:
        return L + ["Недостатньо спостережень — НЕ ПЕРЕВІРЕНО.\n"]
    tr = [o for o in obs if o["day"] < cut]
    te = [o for o in obs if o["day"] >= cut]
    L.append(f"Спостережень: {len(obs)} (train {len(tr)}, test {len(te)}); проколи {sum(1 for o in obs if o['behavior'] != 'CTRL')}, контроль {sum(1 for o in obs if o['behavior'] == 'CTRL')}. "
             f"Пробна геометрія G1: TP +{G_TP:g} ATR15 / SL −{G_SL:g} ATR15, 24 год; комісія {FEE_RT:.2f}% кола (net R = R − комісія/ризик%). Майбутні дані — лише labels; TRAP — мітка результату.\n")
    Xtr = matrix(tr)

    def col(rows: List[dict], k: str) -> np.ndarray:
        return np.array([o[k] for o in rows], dtype=float)
    # 1) базові ставки на TRAIN: проколи (за поведінкою) проти контролю
    L.append("### TRAIN: що буває після події (labels у БІК пробою = «продовження», ПРОТИ = «розворот»; пробна геометрія G1, база TP-before-SL при RR 2 ≈ 33%)\n")
    L.append("| Подія | N | продовження: TP/SL | net R | MFE / MAE (ATR15) | розворот: TP/SL | net R | MFE / MAE | інвалідація продовження ≤4 бари |\n|---|---|---|---|---|---|---|---|---|")
    for name, f in (("A (wick-reclaim)", lambda o: o["behavior"] == "A"), ("B1", lambda o: o["behavior"] == "B1"), ("ACCEPT", lambda o: o["behavior"] == "ACCEPT"), ("  з них TRAP (мітка постфактум)", lambda o: o["future_trap"]),
                    ("КОНТРОЛЬ: біля рівня без проколу", lambda o: o["behavior"] == "CTRL")):
        g = [o for o in tr if f(o)]
        if len(g) < 30:
            continue
        c = lambda k: float(np.mean(col(g, k)))
        L.append(f"| {name} | {len(g)} | {c('cont_tp') * 100:.0f}% / {c('cont_sl') * 100:.0f}% | {_fmt(c('cont_netr'))} | {c('cont_mfe'):.2f} / {c('cont_mae'):.2f} | {c('rev_tp') * 100:.0f}% / {c('rev_sl') * 100:.0f}% | {_fmt(c('rev_netr'))} | {c('rev_mfe'):.2f} / {c('rev_mae'):.2f} | {c('inval') * 100:.0f}% |")
    # 2) одновимірно на TRAIN
    L.append("\n### TRAIN: зв'язок кожної ознаки з наслідками (AUC проти TP-before-SL; Spearman із MFE, MAE, net R продовження)\n")
    L.append("| Ознака | AUC→cont TP | AUC→rev TP | ρ з MFE (прод.) | ρ з MAE (прод.) | ρ з net R (прод.) | ρ з net R (розв.) |\n|---|---|---|---|---|---|---|")
    ycont, yrev = col(tr, "cont_tp"), col(tr, "rev_tp")
    for j, k in enumerate(FEATURES):
        x = Xtr[:, j]
        if np.std(x) == 0:
            continue
        L.append(f"| {k} | {auc(x, ycont):.3f} | {auc(x, yrev):.3f} | {_fmt(spearman(x, col(tr, 'cont_mfe')), 2)} | {_fmt(spearman(x, col(tr, 'cont_mae')), 2)} | {_fmt(spearman(x, col(tr, 'cont_netr')), 2)} | {_fmt(spearman(x, col(tr, 'rev_netr')), 2)} |")
    L.append("\nAUC 0,5 = немає зв'язку. Ознак багато (≈27) × 2 labels — випадково «значущі» значення очікувані; рішення приймаємо лише за ЗАМОРОЖЕНОЮ моделлю на test.\n")
    # 3) модель-probe (train fit), оцінка in-sample; test лише з --open-test
    models = {nm: ridge_fit(Xtr, col(tr, f"{nm}_tp")) for nm in ("cont", "rev")}
    L.append("### Probe (ridge, λ=10): AUC на train (in-sample)\n")
    L.append("| Ціль | AUC train |\n|---|---|")
    for nm in ("cont", "rev"):
        L.append(f"| TP-before-SL «{'продовження' if nm == 'cont' else 'розворот'}» | {auc(ridge_score(Xtr, models[nm]), col(tr, f'{nm}_tp')):.3f} |")
    if not open_test:
        L.append("\n_Test probe НЕ відкрито (--open-test лише для замороженої моделі)._\n")
        return L
    Xte = matrix(te)
    L.append("\n### Probe на TEST (відкрито один раз; модель і ознаки заморожені в HYPOTHESES.md)\n")
    L.append("| Модель | AUC test (кластерний 95% ІВ) | середній net R: усі test | верхній квінтиль прогнозу (ІВ) | нижній квінтиль |\n|---|---|---|---|---|")
    for nm, lab in (("cont", "HD1c: продовження"), ("rev", "HD1r: розворот")):
        sc = ridge_score(Xte, models[nm])
        y = col(te, f"{nm}_tp")
        netr = col(te, f"{nm}_netr")
        a0 = auc(sc, y)
        alo, ahi = cluster_ci(te, lambda idx: auc(sc[idx], y[idx]))
        q_hi = sc >= np.quantile(sc, 0.8)
        q_lo = sc <= np.quantile(sc, 0.2)
        top = float(netr[q_hi].mean())
        tlo, thi = cluster_ci(te, lambda idx: float(netr[idx][q_hi[idx]].mean()) if q_hi[idx].any() else float("nan"))
        L.append(f"| {lab} | {a0:.3f} ({alo:.3f}…{ahi:.3f}) | {_fmt(float(netr.mean()))} | {_fmt(top)} ({_fmt(tlo)}…{_fmt(thi)}) | {_fmt(float(netr[q_lo].mean()))} |")
    L.append("\n### HD2: чи прокол додає інформацію порівняно з контролем (TEST): різниця середнього net R продовження «проколи − контроль»\n")
    isp = np.array([o["behavior"] != "CTRL" for o in te])
    nr = col(te, "cont_netr")
    diff = float(nr[isp].mean() - nr[~isp].mean()) if isp.any() and (~isp).any() else float("nan")
    dlo, dhi = cluster_ci(te, lambda idx: float(nr[idx][isp[idx]].mean() - nr[idx][~isp[idx]].mean()) if isp[idx].any() and (~isp[idx]).any() else float("nan"))
    L.append(f"проколи N={int(isp.sum())}, контроль N={int((~isp).sum())}; різниця = {_fmt(diff)} (кластерний ІВ {_fmt(dlo)}…{_fmt(dhi)}); середній net R: проколи {_fmt(float(nr[isp].mean()))}, контроль {_fmt(float(nr[~isp].mean()))}.\n")
    return L

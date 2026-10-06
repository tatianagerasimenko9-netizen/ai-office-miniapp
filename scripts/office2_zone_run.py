#!/usr/bin/env python3
"""N2 — поведінка ціни в зоні origin/demand (research-only; production не торкається).
Режими: train-only (за замовчуванням) і --open-test (одноразово, лише для замороженої версії, docs/office2/N2_FROZEN.md). Hold-out символи не завантажуються (explore)."""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from office2 import data as D  # noqa: E402
from office2 import evaluate as E  # noqa: E402
from office2 import pipeline as P  # noqa: E402
from office2 import probe as PR  # noqa: E402
from office2 import zone as Z  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from office2_shadow_run import DEFAULT_SYMBOLS  # noqa: E402


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def boot_mean(vals: List[tuple], B: int = 500, seed: int = 3) -> tuple:
    """vals: [(cluster, value)] → (mean, lo, hi) кластерний bootstrap 95%."""
    cl: Dict[tuple, List[float]] = {}
    for k, v in vals:
        cl.setdefault(k, []).append(v)
    allv = [v for _, v in vals]
    if not allv:
        return float("nan"), float("nan"), float("nan")
    m = sum(allv) / len(allv)
    keys = list(cl)
    if len(keys) < 8:
        return m, float("nan"), float("nan")
    rr = random.Random(seed)
    ms = []
    for _ in range(B):
        samp = [x for k in (rr.choice(keys) for _ in keys) for x in cl[k]]
        ms.append(sum(samp) / len(samp))
    ms.sort()
    return m, ms[int(B * 0.025)], ms[int(B * 0.975) - 1]


METRICS = (
    ("+0,5R раніше −1R", lambda r: 1.0 if r["order_0.5"] == "up" else 0.0, True),
    ("+1R раніше −1R", lambda r: 1.0 if r["order_1.0"] == "up" else 0.0, True),
    ("+1,5R раніше −1R", lambda r: 1.0 if r["order_1.5"] == "up" else 0.0, True),
    ("+2R раніше −1R", lambda r: 1.0 if r["order_2.0"] == "up" else 0.0, True),
    ("інвалідація (SL) ≤48 год", lambda r: 0.0 if r["inval_min"] is None else 1.0, True),
    ("MFE48, R", lambda r: r["mfe_r_48"], False),
    ("MAE48, R", lambda r: r["mae_r_48"], False),
    ("MFE48−MAE48, % ціни (артефакт ширини стопу)", lambda r: r["mfe_pct_48"] - r["mae_pct_48"], False),
    ("MFE24−MAE24, ATR", lambda r: r["mfe_atr_24"] - r["mae_atr_24"], False),
    ("чистий R після комісій+slippage (G2: TP +2R / SL −1R)", lambda r: r["r_net_g2"], False),
)


def paired(evs: List[dict], cts: Dict[str, dict]) -> List[tuple]:
    return [(e, cts[e["pair"]]) for e in evs if e.get("pair") in cts]


def cmp_table(title: str, groups, ct_by_pair: Dict[str, dict], L: List[str]) -> None:
    L.append(f"\n#### {title}\n")
    L.append("| Група | події N | з парою (coverage) | " + " | ".join(m[0] for m in METRICS[:4]) + " | інвалідація | MFE−MAE % | чистий R G2 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for name, evs in groups:
        pr = paired(evs, ct_by_pair)
        if not evs:
            L.append(f"| {name} | 0 | — | | | | | | | |")
            continue
        cells = []
        for mname, fn, pct in METRICS:
            if mname.startswith(("MFE48, R", "MAE48, R", "MFE24")):
                continue
            d = [((e["symbol"], e["day"]), fn(e) - fn(c)) for e, c in pr]
            m, lo, hi = boot_mean(d)
            ev_m = (sum(fn(e) for e, _ in pr) / len(pr)) if pr else float("nan")
            ct_m = (sum(fn(c) for _, c in pr) / len(pr)) if pr else float("nan")
            f = (lambda v: f"{v * 100:.0f}%") if pct else (lambda v: f"{v:+.2f}")
            fd = (lambda v: f"{v * 100:+.0f}") if pct else (lambda v: f"{v:+.2f}")
            cells.append(f"{f(ev_m)} vs {f(ct_m)}: **{fd(m)}** ({fd(lo)}…{fd(hi)})")
        L.append(f"| {name} | {len(evs)} | {len(pr)} ({len(pr) / len(evs) * 100:.0f}%) | " + " | ".join(cells) + " |")
    L.append("\nФормат клітинки: подія vs matched: **різниця по парах** (кластерний 95% ІВ); для часток — п.п.; MFE−MAE у % ціни, чистий R у R.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d0", required=True)
    ap.add_argument("--d1", required=True)
    ap.add_argument("--cache", default="/tmp/o2cache")
    ap.add_argument("--md", default="")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--open-test", action="store_true", help="одноразово, лише для замороженої версії (docs/office2/N2_FROZEN.md)")
    a = ap.parse_args()
    all_syms = [s for s in (a.symbols.split(",") if a.symbols else DEFAULT_SYMBOLS) if s]
    syms = [s for s in all_syms if (not E.is_holdout(s)) or s == "BTCUSDT"]
    p = Z.ZParams()
    d0, d1 = _dt(a.d0), _dt(a.d1)
    cache = Path(a.cache)
    t0 = time.time()
    btc_m1, _ = D.load_symbol("BTCUSDT", d0, d1, cache, a.offline)
    if btc_m1 is None:
        print("BTCUSDT: немає даних")
        return 1
    btc_ctx = P.build_context(btc_m1)
    ev: List[dict] = []
    ct: List[dict] = []
    rnd: List[dict] = []
    st: Dict[str, int] = {}
    skipped: List[str] = []
    for i, sym in enumerate(syms):
        m1, missing = (btc_m1, []) if sym == "BTCUSDT" else D.load_symbol(sym, d0, d1, cache, a.offline)
        if m1 is None or len(m1["t"]) < 10 * 1440:
            skipped.append(sym)
            continue
        ctx = btc_ctx if sym == "BTCUSDT" else P.build_context(m1)
        out = Z.build_records(sym, ctx, btc_ctx, p, st)
        ev += out["events"]
        ct += out["matched"]
        rnd += out["random"]
        print(f"[{i + 1}/{len(syms)}] {sym}: події {len(out['events'])}, пар {len(out['matched'])}, {time.time() - t0:.0f} с", flush=True)
    cut = E.cut_day(ev)
    tr_only = not a.open_test
    L: List[str] = [f"# N2 — поведінка ціни в зоні origin/demand: {a.d0} … {a.d1} UTC ({'TRAIN-ONLY' if tr_only else 'TRAIN + TEST (відкрито один раз)'})", ""]
    L.append(f"Символи (hold-out не завантажувався): {len(syms) - len(skipped)}; пропущено: {', '.join(skipped) or '—'}. Межа train/test: день {cut} ({datetime.fromtimestamp((cut or 0) * 86400, timezone.utc):%Y-%m-%d}).\n")
    L.append("Воронка: імпульсів ≥3 ATR: {imp}; атак зони (EXIT): {att}; подій EXIT: {ex}; BOS після захисту: {bos}; зона провалена: {zf}; без outcome: {no}.\n".format(
        imp=st.get("impulses", 0), att=st.get("attacks", 0), ex=st.get("events_EXIT", 0), bos=st.get("events_BOS", 0), zf=st.get("zone_failed", 0), no=st.get("ev_no_outcome", 0)))
    sel = (lambda rs: [r for r in rs if cut is None or r["day"] < cut]) if tr_only else (lambda rs: rs)
    ev_s, ct_s, rnd_s = sel(ev), sel(ct), sel(rnd)
    exit_ev = [e for e in ev_s if e["etype"] == "EXIT"]
    L.append("### Автоматична перевірка змінності ознак (EXIT; константа/майже константа = НЕПРИДАТНА)\n")
    L.append("| Ознака | N | std | частка найчастішого значення | статус |\n|---|---|---|---|---|")
    for r in Z.variance_report(exit_ev):
        L.append(f"| {r['feature']} | {r['n']} | {r['std']:.3g} | {r['top_share'] * 100:.0f}% | {'OK' if r['usable'] else 'НЕПРИДАТНА: ' + r['why']} |")
    ct_by = {c["pair"]: c for c in ct_s}
    for etype, title in (("EXIT", "ОСНОВНА: EXIT (атаку зони відбито закриттям над зоною) проти matched-стану БЕЗ атаки"), ("BOS", "EXPLORATORY: BOS після захисту зони проти matched BOS без атаки зони")):
        es = [e for e in ev_s if e["etype"] == etype]
        cmp_table(title, [("усі", es), ("  k=1 (перша атака)", [e for e in es if e["k"] == 1]), ("  k≥2 (повторні атаки)", [e for e in es if e["k"] >= 2]),
                          ("  LONG", [e for e in es if e["dir"] == "LONG"]), ("  SHORT", [e for e in es if e["dir"] == "SHORT"])], ct_by, L)
    L.append("\n#### Допоміжний контроль: випадкові години (НЕ основний; нестабільний між періодами)\n")
    if rnd_s:
        row = []
        for mname, fn, pct in METRICS:
            vals = [fn(r) for r in rnd_s]
            row.append(f"{mname}: {(sum(vals) / len(vals)) * (100 if pct else 1):.2f}{'%' if pct else ''}")
        L.append(f"N={len(rnd_s)}; " + "; ".join(row))
    # coverage за k та напрямом
    L.append("\n#### Coverage matching (частка подій, для яких знайдено контроль у caliper): не узагальнювати результат на непокриту частину\n")
    L.append("| Тип | усі | k=1 | k≥2 | LONG | SHORT |\n|---|---|---|---|---|---|")
    for etype in ("EXIT", "BOS"):
        es = [e for e in ev_s if e["etype"] == etype]
        f = lambda g: f"{sum(1 for e in g if e['matched'])}/{len(g)} ({(sum(1 for e in g if e['matched']) / len(g) * 100) if g else 0:.0f}%)"
        L.append(f"| {etype} | {f(es)} | {f([e for e in es if e['k'] == 1])} | {f([e for e in es if e['k'] >= 2])} | {f([e for e in es if e['dir'] == 'LONG'])} | {f([e for e in es if e['dir'] == 'SHORT'])} |")
    # діагностика ознак (train-only; exploratory; рішень не приймаємо)
    dec = [e for e in exit_ev if e["order_1.0"] in ("up", "down")]
    if len(dec) >= 100:
        L.append("\n#### Діагностика (EXPLORATORY, не правила): зв'язок ознак EXIT із «+1R раніше −1R» (AUC) і з чистим R (Spearman); ознаки багато — випадкові «значущі» значення очікувані\n")
        L.append("| Ознака | AUC→+1R | ρ з чистим R G2 |\n|---|---|---|")
        y = np.array([1.0 if e["order_1.0"] == "up" else 0.0 for e in dec])
        rn = np.array([e["r_net_g2"] for e in dec])
        for r in Z.variance_report(exit_ev):
            if not r["usable"]:
                continue
            x = np.array([e["feat"][r["feature"]] for e in dec], dtype=float)
            L.append(f"| {r['feature']} | {PR.auc(x, y):.3f} | {PR._fmt(PR.spearman(x, rn), 2)} |")
    if a.open_test:
        L += frozen_verdict(ev, ct, cut)
    text = "\n".join(L) + "\n"
    if a.md:
        Path(a.md).write_text(text)
    print(text)
    return 0


def frozen_verdict(ev: List[dict], ct: List[dict], cut: int) -> List[str]:
    """PASS/FAIL за критеріями, зафіксованими в docs/office2/N2_FROZEN.md ДО test."""
    L = ["\n## N2: ВЕРДИКТ за зафіксованими критеріями (EXIT, test, пари; train — для довідки)\n"]
    ct_by = {c["pair"]: c for c in ct}
    for lab, f in (("train", lambda r: r["day"] < cut), ("test", lambda r: r["day"] >= cut)):
        es = [e for e in ev if e["etype"] == "EXIT" and f(e)]
        pr = paired(es, ct_by)
        cov = len(pr) / len(es) if es else 0.0
        d1 = [((e["symbol"], e["day"]), (1.0 if e["order_1.0"] == "up" else 0.0) - (1.0 if c["order_1.0"] == "up" else 0.0)) for e, c in pr]
        d2 = [((e["symbol"], e["day"]), e["r_net_g2"] - c["r_net_g2"]) for e, c in pr]
        d5 = [((e["symbol"], e["day"]), (e["mfe_pct_48"] - e["mae_pct_48"]) - (c["mfe_pct_48"] - c["mae_pct_48"])) for e, c in pr]
        m1_, lo1, hi1 = boot_mean(d1)
        m2_, lo2, hi2 = boot_mean(d2)
        m5_, _, _ = boot_mean(d5)
        L.append(f"**{lab}**: подій EXIT {len(es)}, пар {len(pr)} (coverage {cov * 100:.0f}%); Δ P(+1R раніше −1R) = {m1_ * 100:+.1f} п.п. ({lo1 * 100:+.1f}…{hi1 * 100:+.1f}); Δ чистий R G2 = {m2_:+.3f} ({lo2:+.3f}…{hi2:+.3f}); Δ (MFE−MAE)% = {m5_:+.2f}")
        if lab == "test":
            dirs = {}
            for dname in ("LONG", "SHORT"):
                sub = [(k, v) for (e, c), (k, v) in zip(pr, d1) if e["dir"] == dname]
                dirs[dname] = boot_mean(sub)[0] if sub else float("nan")
            days = sorted({e["day"] for e, _ in pr})
            mid = days[len(days) // 2] if days else 0
            halves = [boot_mean([(k, v) for (e, c), (k, v) in zip(pr, d1) if (e["day"] < mid) == (h == 0)])[0] for h in (0, 1)]
            checks = [
                ("C0 coverage ≥ 50% подій test", cov >= 0.5),
                ("C1 Δ P(+1R раніше −1R): нижня межа ІВ > 0", lo1 > 0),
                ("C2 Δ чистий R G2: нижня межа ІВ > 0", lo2 > 0),
                ("C3 точкова Δ(+1R) ≥ 0 і для LONG, і для SHORT", dirs["LONG"] >= 0 and dirs["SHORT"] >= 0),
                ("C4 точкова Δ(+1R) ≥ 0 в обох половинах test", all(h >= 0 for h in halves if h == h)),
                ("C5 артефакт ширини стопу: Δ(MFE−MAE)% > 0", m5_ > 0),
            ]
            L.append("\n| Критерій (зафіксовано) | результат |\n|---|---|")
            for name, ok in checks:
                L.append(f"| {name} | {'✓' if ok else '✗'} |")
            ok_all = all(ok for _, ok in checks)
            L.append(f"\n**ВЕРДИКТ N2: {'PASS' if ok_all else 'FAIL'}**" + ("" if checks[0][1] else " (coverage <50%: результат не узагальнюється на клас, лише на matched-підмножину)"))
            L.append(f"LONG Δ(+1R) = {dirs['LONG'] * 100:+.1f} п.п.; SHORT = {dirs['SHORT'] * 100:+.1f} п.п.; половини: {halves[0] * 100:+.1f} / {halves[1] * 100:+.1f} п.п.")
    return L


if __name__ == "__main__":
    raise SystemExit(main())

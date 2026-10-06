#!/usr/bin/env python3
"""FLOW-1: чи додають джерела грошового потоку (taker-потік зі свічок, OI, positioning/funding, taker-ratio) інформацію понад OHLCV
на двох популяціях рішень: ZONE-EXIT (N2) і DISPLACEMENT. Дизайн і критерії: docs/office2/FLOW1_FROZEN.md. Research-only.
--phase dev: підгонка/оцінка ВСЕРЕДИНІ train (60/40 за часом); --phase test: підгонка на всьому train, ОДНЕ оцінювання на test."""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from office2 import data as D  # noqa: E402
from office2 import disp as DS  # noqa: E402
from office2 import evaluate as E  # noqa: E402
from office2 import flowdata as FD  # noqa: E402
from office2 import pipeline as P  # noqa: E402
from office2 import probe as PR  # noqa: E402
from office2 import zone as Z  # noqa: E402
from office2_shadow_run import DEFAULT_SYMBOLS  # noqa: E402

TBV = ("tdelta_bar", "tdelta_3", "cvd6", "tdelta_prior6")
TBV_ZONE = TBV + ("tdelta_last_run", "tdelta_first_run", "tdelta_change")
BLOCKS = ("TBV", "OI", "POS", "TAKER5")
B = 400


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def zone_extra(rec: dict, ctx: dict) -> Dict[str, float]:
    h1, atr = ctx["h1"], ctx["atr1h"]
    sg = 1.0 if rec["dir"] == "LONG" else -1.0
    j = rec["j"]
    v, tbv = h1["v"], h1["tbv"]
    rd = lambda a, b: float(sg * np.sum(2 * tbv[a:b + 1] - v[a:b + 1]) / max(np.sum(v[a:b + 1]), 1e-12))
    runs = rec["runs"]
    last, first = runs[-1], runs[0]
    out = DS.candle_flow(h1, j, sg)
    out["tdelta_last_run"], out["tdelta_first_run"] = rd(*last), rd(*first)
    out["tdelta_change"] = out["tdelta_last_run"] - out["tdelta_first_run"] if len(runs) >= 2 else 0.0
    out["r4_rel"] = float(sg * (h1["c"][j] - h1["c"][j - 4]) / atr[j])
    return out


def feature_sets(pop: str, rows: List[dict]) -> Dict[str, List[str]]:
    ohlcv = list(Z.EVENT_FEATURES) if pop == "ZONE" else list(DS.DISP_OHLCV)
    blocks = {"TBV": list(TBV_ZONE if pop == "ZONE" else TBV), "OI": list(FD.FLOW_BLOCKS["OI"]), "POS": list(FD.FLOW_BLOCKS["POS"]), "TAKER5": list(FD.FLOW_BLOCKS["TAKER5"])}
    return {"OHLCV": ohlcv, **blocks}


def usable(rows: List[dict], names: List[str]) -> List[str]:
    out = []
    for k in names:
        x = np.array([r["X"][k] for r in rows], dtype=float)
        vals, cnt = np.unique(np.round(x, 6), return_counts=True)
        if x.std() > 1e-9 and cnt.max() / len(x) < 0.95:
            out.append(k)
    return out


def boot_idx(rows: List[dict], seed: int = 7):
    cl: Dict[tuple, List[int]] = {}
    for i, r in enumerate(rows):
        cl.setdefault((r["symbol"], r["day"]), []).append(i)
    keys = list(cl)
    rr = random.Random(seed)
    return [np.array([i for k in (rr.choice(keys) for _ in keys) for i in cl[k]]) for _ in range(B)]


def ci(vals: List[float], level: float = 0.95) -> tuple:
    a = np.array([v for v in vals if v == v])
    if len(a) < 20:
        return float("nan"), float("nan")
    lo, hi = (1 - level) / 2, 1 - (1 - level) / 2
    return float(np.quantile(a, lo)), float(np.quantile(a, hi))


def evaluate_pop(pop: str, rows: List[dict], cut: int, phase: str, L: List[str]) -> Dict[str, bool]:
    fs = feature_sets(pop, rows)
    allf = sorted({k for v in fs.values() for k in v})
    cc = [r for r in rows if all(r["X"].get(k, float("nan")) == r["X"].get(k, float("nan")) for k in allf)]
    L.append(f"\n### Популяція {pop}: подій {len(rows)}, повних (усі ознаки, включно з потоком) {len(cc)} ({len(cc) / max(len(rows), 1) * 100:.0f}%)\n")
    miss = {k: sum(1 for r in rows if r["X"].get(k, float("nan")) != r["X"].get(k, float("nan"))) / max(len(rows), 1) for k in allf}
    bad = sorted(((v, k) for k, v in miss.items() if v > 0.005), reverse=True)
    L.append("Частка відсутніх значень за ознаками (>0,5%): " + (", ".join(f"{k} {v * 100:.0f}%" for v, k in bad) or "немає") + "\n")
    bymon: Dict[str, List[int]] = {}
    for r in rows:
        if "t_dec" not in r:
            continue
        mo = datetime.fromtimestamp(r["t_dec"], timezone.utc).strftime("%Y-%m")
        x = r["X"].get("oi_chg_1h_z", float("nan"))
        bymon.setdefault(mo, []).append(1 if x != x else 0)
    if bymon:
        L.append("Відсутність oi_chg_1h_z за місяцями: " + ", ".join(f"{k} {sum(v) / len(v) * 100:.0f}%" for k, v in sorted(bymon.items())) + "\n")
    bysym: Dict[str, List[int]] = {}
    for r in rows:
        ok = all(r["X"].get(k, float("nan")) == r["X"].get(k, float("nan")) for k in allf)
        bysym.setdefault(r["symbol"], []).append(0 if ok else 1)
    worst = sorted(((sum(v) / len(v), k) for k, v in bysym.items()), reverse=True)[:6]
    L.append("Найгірше покриття за символами (частка неповних): " + ", ".join(f"{k} {v * 100:.0f}%" for v, k in worst) + "\n")
    if phase == "dev":
        days = sorted({r["day"] for r in cc if r["day"] < cut})
        cut2 = days[int(len(days) * 0.6)] if len(days) > 10 else cut
        fit = [r for r in cc if r["day"] < cut2]
        ev = [r for r in cc if cut2 <= r["day"] < cut]
        L.append(f"_DEV (всередині train): підгонка до дня {cut2}, оцінка {cut2}…{cut}; рішень не приймаємо._")
    else:
        fit = [r for r in cc if r["day"] < cut]
        ev = [r for r in cc if r["day"] >= cut]
        L.append("_TEST: підгонка на всьому train, одне оцінювання на test._")
    if len(fit) < 300 or len(ev) < 200:
        L.append(f"Замало даних: fit {len(fit)}, eval {len(ev)}.")
        return {}
    ohl = usable(fit, fs["OHLCV"])
    models = {"M0: OHLCV": ohl}
    for b in BLOCKS:
        ub = usable(fit, fs[b])
        if ub:
            models[f"M+{b}"] = ohl + ub
    allb = sum((usable(fit, fs[b]) for b in BLOCKS), [])
    models["M+УСІ потоки"] = ohl + allb
    yf = np.array([1.0 if r["order_1.0"] == "up" else 0.0 for r in fit])
    decf = np.array([r["order_1.0"] != "none" for r in fit])
    ye = np.array([1.0 if r["order_1.0"] == "up" else 0.0 for r in ev])
    dece = np.array([r["order_1.0"] != "none" for r in ev])
    nr = np.array([r["r_net_g2"] for r in ev])
    L.append(f"fit N={len(fit)}, eval N={len(ev)}; P(+1R раніше −1R | вирішено) eval = {ye[dece].mean() * 100:.1f}%; чистий R G2 eval (середнє) = {nr.mean():+.3f}.\n")
    scores = {}
    for name, feats in models.items():
        Xf = np.array([[r["X"][k] for k in feats] for r in fit], dtype=float)
        Xe = np.array([[r["X"][k] for k in feats] for r in ev], dtype=float)
        scores[name] = PR.ridge_score(Xe, PR.ridge_fit(Xf[decf], yf[decf], 10.0))
    bidx = boot_idx(ev)
    def auc_of(sc, idx):
        d = dece[idx]
        return PR.auc(sc[idx][d], ye[idx][d]) if d.sum() > 20 and 0 < ye[idx][d].sum() < d.sum() else float("nan")
    base_auc = {i: auc_of(scores["M0: OHLCV"], b_) for i, b_ in enumerate(bidx)}
    top = {name: sc >= np.quantile(sc, 0.8) for name, sc in scores.items()}
    L.append("| Модель | #ознак | AUC (95% ІВ) | ΔAUC проти OHLCV (99% ІВ) | топ-20%: N | топ-20%: чистий R G2 (95% ІВ) | топ-20% − усі (95% ІВ) | топ-20%: P(+1R раніше −1R) |")
    L.append("|---|---|---|---|---|---|---|---|")
    verdict: Dict[str, bool] = {}
    full_idx = np.arange(len(ev))
    for name, sc in scores.items():
        a0 = auc_of(sc, full_idx)
        aucs = [auc_of(sc, b_) for b_ in bidx]
        lo, hi = ci(aucs)
        dl = [x - base_auc[i] for i, x in enumerate(aucs)]
        dlo, dhi = ci(dl, 0.99)
        tp = top[name]
        tr = [nr[b_][tp[b_]].mean() if tp[b_].sum() > 10 else float("nan") for b_ in bidx]
        tlo, thi = ci(tr)
        dd = [(nr[b_][tp[b_]].mean() - nr[b_].mean()) if tp[b_].sum() > 10 else float("nan") for b_ in bidx]
        dlo2, dhi2 = ci(dd)
        tdec = tp & dece
        L.append(f"| {name} | {len(models[name])} | {a0:.3f} ({lo:.3f}…{hi:.3f}) | {a0 - auc_of(scores['M0: OHLCV'], full_idx):+.3f} ({dlo:+.3f}…{dhi:+.3f}) | {int(tp.sum())} | {nr[tp].mean():+.3f} ({tlo:+.3f}…{thi:+.3f}) | {nr[tp].mean() - nr.mean():+.3f} ({dlo2:+.3f}…{dhi2:+.3f}) | {(ye[tdec].mean() * 100 if tdec.sum() else float('nan')):.1f}% |")
        if name != "M0: OHLCV":
            verdict[name] = bool(dlo > 0 and tlo > 0)
    return verdict


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d0", required=True)
    ap.add_argument("--d1", required=True)
    ap.add_argument("--cache", default="/tmp/o2cache")
    ap.add_argument("--md", default="")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--phase", choices=("dev", "test"), default="dev")
    a = ap.parse_args()
    syms = [s for s in (a.symbols.split(",") if a.symbols else DEFAULT_SYMBOLS) if s and ((not E.is_holdout(s)) or s == "BTCUSDT")]
    d0, d1 = _dt(a.d0), _dt(a.d1)
    cache = Path(a.cache)
    t0 = time.time()
    btc_m1, _ = D.load_symbol("BTCUSDT", d0, d1, cache, a.offline)
    btc_ctx = P.build_context(btc_m1)
    zone_rows: List[dict] = []
    disp_rows: List[dict] = []
    st: Dict[str, int] = {}
    skipped: List[str] = []
    health: List[str] = []
    for i, sym in enumerate(syms):
        m1, _ = (btc_m1, []) if sym == "BTCUSDT" else D.load_symbol(sym, d0, d1, cache, a.offline)
        fl = FD.load_flow(sym, d0, d1, cache, a.offline)
        if m1 is None or len(m1["t"]) < 10 * 1440 or fl is None:
            skipped.append(sym)
            continue
        if i < 2:
            tt = fl["t"]
            dts = np.diff(tt)
            hl = lambda k: float(np.mean(~np.isnan(fl[k])) * 100)
            health.append(f"{sym}: знімків {len(tt)}, крок медіана {np.median(dts):.0f} с / p99 {np.percentile(dts, 99):.0f} с / макс {dts.max():.0f} с; oi_chg_1h валідних {hl('oi_chg_1'):.0f}%, oi_std_1h валідних {hl('oi_std_1'):.0f}%, oi_chg_4h {hl('oi_chg_4'):.0f}%; "
                          f"[по місяцях: частка нульових oi_chg_1h / std oi_chg_1h / std_1h у кінці місяця] " + "; ".join(
                              f"{mo}: {np.mean(fl['oi_chg_1'][mm] == 0) * 100:.0f}% / {np.nanstd(fl['oi_chg_1'][mm]):.2e} / {np.nanmean(fl['oi_std_1'][mm][-50:]):.2e}"
                              for mo, mm in ((m_, np.array([datetime.fromtimestamp(x, timezone.utc).strftime('%Y-%m') == m_ for x in tt[::1]])) for m_ in sorted({datetime.fromtimestamp(x, timezone.utc).strftime('%Y-%m') for x in tt[::2000]}))
                              if mm.sum() > 100) + " | "
                          f"перший знімок {datetime.fromtimestamp(tt[0], timezone.utc):%Y-%m-%d %H:%M}, останній {datetime.fromtimestamp(tt[-1], timezone.utc):%Y-%m-%d %H:%M}; funding прінтів {len(fl['fund_t'])}")
        ctx = btc_ctx if sym == "BTCUSDT" else P.build_context(m1)
        zr = [r for r in Z.build_records(sym, ctx, btc_ctx, Z.ZParams(), st, with_controls=False)["events"] if r["etype"] == "EXIT"]
        dr = DS.build_records(sym, ctx, btc_ctx, DS.DParams(), st)
        for r in zr:
            ex = zone_extra(r, ctx)
            sg = 1.0 if r["dir"] == "LONG" else -1.0
            r["X"] = {**r["feat"], **ex, **FD.features(fl, r["t_dec"], sg, ex["r4_rel"])}
        for r in dr:
            sg = 1.0 if r["dir"] == "LONG" else -1.0
            r["X"] = {**r["feat"], **FD.features(fl, r["t_dec"], sg, r["r4_rel"])}
        zone_rows += zr
        disp_rows += dr
        print(f"[{i + 1}/{len(syms)}] {sym}: ZONE {len(zr)}, DISP {len(dr)}, {time.time() - t0:.0f} с", flush=True)
    cut = E.cut_day(zone_rows + disp_rows)
    L = [f"# FLOW-1: інкрементальна цінність джерел потоку понад OHLCV — {a.d0} … {a.d1} UTC, фаза {a.phase.upper()}", "",
         f"Символи: {len(syms) - len(skipped)} (пропущено без даних потоку/свічок: {', '.join(skipped) or '—'}). Межа train/test: день {cut} ({datetime.fromtimestamp((cut or 0) * 86400, timezone.utc):%Y-%m-%d}). Hold-out символи не завантажувались."]
    L.append("\nЗдоров'я даних потоку (перші символи): " + " | ".join(health) + "\n")
    res = {}
    for pop, rows in (("ZONE", zone_rows), ("DISP", disp_rows)):
        res[pop] = evaluate_pop(pop, rows, cut, a.phase, L)
    if a.phase == "test":
        L.append("\n## FLOW-1: ВЕРДИКТ за зафіксованими критеріями\n")
        L.append("Блок «додає цінність» у популяції, лише якщо ОДНОЧАСНО: нижня межа 99% ІВ ΔAUC проти OHLCV > 0 І нижня межа 95% ІВ чистого R G2 топ-20% (за скором моделі) > 0.\n")
        L.append("| Популяція | модель | додає цінність |\n|---|---|---|")
        for pop, v in res.items():
            for name, ok in v.items():
                L.append(f"| {pop} | {name} | {'✓' if ok else '✗'} |")
        L.append(f"\n**ВЕРДИКТ FLOW-1: {'є джерело з доведеною цінністю' if any(ok for v in res.values() for ok in v.values()) else 'FAIL — жодне джерело не додає цінності поза вибіркою'}**")
    text = "\n".join(L) + "\n"
    if a.md:
        Path(a.md).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

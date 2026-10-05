#!/usr/bin/env python3
"""Дослідження Stop Engine на replay (лише дослідження; production-логіку, ATR/RR/SL/TP/ризик НЕ змінює).

Питання:
 1) що відбувається ПІСЛЯ SL: ціна продовжує проти сценарію чи лише збирає стоп і йде до TP1 (MFE/MAE, overshoot, reclaim);
 2) чи залежність «тісний стоп → мало TP1» — дефект Stop Engine чи наслідок геометрії (порівняння з блуканням без зносу при тих самих відстанях);
 3) альтернативні стопи (ширші; N×ATR15; структурний фрактал 15m + люфт у ATR) при НЕЗМІННОМУ ризику в $: розмір позиції = ризик$/відстань до стопу,
    тому результат у R: TP1 = (відстань до TP1)/(відстань до стопу) − комісія/(відстань до стопу); SL = −1R − комісія/відстань.
Без lookahead: ATR і свінги — лише зі свічок, закритих ДО моменту READY. Немає даних = не перевірено (плани без повного горизонту виключені, а не рахуються нулями).
Вибір «кращого» варіанта — лише на 1-й половині часу (train), оцінка — на 2-й (test).

Використання: python scripts/ready_stop_research.py --plans data/research/ready_plans_2026-10-01_04.json [--cache /tmp/ready_cache] [--offline] [--md out.md]
"""
from __future__ import annotations

import argparse
import bisect
import json
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ready_replay_strict as rr  # noqa: E402

FEE = 0.001            # комісія круга з gate.fee_round_trip_pct = 0,1% від номіналу
H = 24 * 3600.0
POST = 24 * 3600.0
K_FRACTAL = 2


def bars15(rows: List[List[float]], times: List[float], ct: float, n: int = 96) -> List[Tuple[float, float, float, float, float]]:
    """Закриті ДО ct 15m-бари (open_time, o, h, l, c) із 1m; бар неповний (<10 хв даних) → список обривається."""
    last_open = ((int(ct) - 900) // 900) * 900
    out = []
    for k in range(n):
        b0 = last_open - 900 * k
        i0 = bisect.bisect_left(times, b0)
        i1 = bisect.bisect_left(times, b0 + 900)
        if i1 - i0 < 10:
            break
        seg = rows[i0:i1]
        out.append((float(b0), seg[0][1], max(x[2] for x in seg), min(x[3] for x in seg), seg[-1][4]))
    out.reverse()
    return out


def atr_of(bars: List[Tuple[float, float, float, float, float]], n: int = 14) -> Optional[float]:
    if len(bars) < n + 1:
        return None
    b = bars[-(n + 1):]
    trs = [max(b[k][2] - b[k][3], abs(b[k][2] - b[k - 1][4]), abs(b[k][3] - b[k - 1][4])) for k in range(1, len(b))]
    return sum(trs) / len(trs)


def fractals(bars: List[Tuple[float, float, float, float, float]]) -> List[Tuple[int, str, float]]:
    """Фрактал K=2: high/low строго вище/нижче K сусідів з кожного боку; останні K барів фракталами бути не можуть (потрібне підтвердження справа)."""
    out = []
    for i in range(K_FRACTAL, len(bars) - K_FRACTAL):
        h, l = bars[i][2], bars[i][3]
        if all(h > bars[j][2] for j in range(i - K_FRACTAL, i + K_FRACTAL + 1) if j != i):
            out.append((i, "H", h))
        if all(l < bars[j][3] for j in range(i - K_FRACTAL, i + K_FRACTAL + 1) if j != i):
            out.append((i, "L", l))
    return out


def h1_levels(rows: List[List[float]], times: List[float], ct: float, lookback: float = 72 * 3600.0) -> List[Tuple[str, float]]:
    """Рівні ліквідності ДО ct: фрактали H1 (K=2) за lookback + максимум/мінімум попередньої UTC-доби (PDH/PDL). Без lookahead: лише закриті години."""
    last_open = (int(ct) // 3600) * 3600 - 3600   # остання повністю закрита година
    nb = int(lookback // 3600)
    bars: List[Tuple[float, float, float]] = []
    for k in range(nb):
        b0 = last_open - 3600 * k
        i0 = bisect.bisect_left(times, b0)
        i1 = bisect.bisect_left(times, b0 + 3600)
        if i1 - i0 < 40:
            continue
        seg = rows[i0:i1]
        bars.append((b0, max(x[2] for x in seg), min(x[3] for x in seg)))
    bars.reverse()
    out: List[Tuple[str, float]] = []
    for i in range(K_FRACTAL, len(bars) - K_FRACTAL):
        if all(bars[i][1] > bars[j][1] for j in range(i - K_FRACTAL, i + K_FRACTAL + 1) if j != i):
            out.append(("H1-high", bars[i][1]))
        if all(bars[i][2] < bars[j][2] for j in range(i - K_FRACTAL, i + K_FRACTAL + 1) if j != i):
            out.append(("H1-low", bars[i][2]))
    d0 = (int(ct) // 86400) * 86400
    i0 = bisect.bisect_left(times, d0 - 86400)
    i1 = bisect.bisect_left(times, d0)
    if i1 - i0 > 600:
        seg = rows[i0:i1]
        out.append(("PDH", max(x[2] for x in seg)))
        out.append(("PDL", min(x[3] for x in seg)))
    return out


def walk(rows: List[List[float]], times: List[float], ct: float, vt: float, entry: float, sl: float, tp1: float, long_: bool, horizon: float = H) -> Dict[str, Any]:
    """Як у lifecycle (simulate на 1m): вхід — перша хвилина з t0 ≥ ct, що торкається ціни входу; у хвилині входу цілі не зараховуються, а стоп так;
    далі стоп перевіряється раніше за ціль (одна хвилина зі стопом і ціллю = стоп). Горизонт ≥ horizon; нема даних до горизонту = NO_DATA."""
    end_t = ct + horizon
    if not rows or rows[-1][0] + 60.0 < end_t:
        return {"status": "NO_DATA"}
    j = bisect.bisect_left(times, ct)
    n = len(rows)
    filled = False
    t_fill = None
    mfe = mae = 0.0
    while j < n and rows[j][0] < end_t:
        t, _o, hi, lo, cl = rows[j][0], rows[j][1], rows[j][2], rows[j][3], rows[j][4]
        if not filled:
            if t >= vt:
                return {"status": "NOT_FILLED"}
            if lo <= entry <= hi:
                filled = True
                t_fill = t
                mfe = max(mfe, (hi - entry) if long_ else (entry - lo))
                mae = max(mae, (entry - lo) if long_ else (hi - entry))
                if (lo <= sl) if long_ else (hi >= sl):
                    return {"status": "SL", "t_fill": t_fill, "t_exit": t, "exit_px": sl, "mfe": mfe, "mae": mae, "j_exit": j}
            j += 1
            continue
        mfe = max(mfe, (hi - entry) if long_ else (entry - lo))
        mae = max(mae, (entry - lo) if long_ else (hi - entry))
        if (lo <= sl) if long_ else (hi >= sl):
            return {"status": "SL", "t_fill": t_fill, "t_exit": t, "exit_px": sl, "mfe": mfe, "mae": mae, "j_exit": j}
        if (hi >= tp1) if long_ else (lo <= tp1):
            return {"status": "TP1", "t_fill": t_fill, "t_exit": t, "exit_px": tp1, "mfe": mfe, "mae": mae, "j_exit": j}
        j += 1
    if not filled:
        return {"status": "NOT_FILLED"}
    last = rows[min(j, n) - 1]
    return {"status": "NONE", "t_fill": t_fill, "t_exit": last[0], "exit_px": last[4], "mfe": mfe, "mae": mae, "j_exit": min(j, n) - 1}


def r_multiple(res: Dict[str, Any], entry: float, sl: float, tp1: float, long_: bool) -> Optional[float]:
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    fee_r = FEE * entry / risk
    st = res.get("status")
    if st == "TP1":
        return abs(tp1 - entry) / risk - fee_r
    if st == "SL":
        return -1.0 - fee_r
    if st == "NONE":
        return ((res["exit_px"] - entry) if long_ else (entry - res["exit_px"])) / risk - fee_r
    return None


def stop_variants(entry: float, sl: float, long_: bool, atr: Optional[float], fr: List[Tuple[int, str, float]]) -> Dict[str, float]:
    sg = 1.0 if long_ else -1.0   # LONG: стоп нижче входу
    r = abs(entry - sl)
    v: Dict[str, float] = {"поточний": sl}
    for m in (1.25, 1.5, 2.0):
        v[f"поточний×{m}"] = entry - sg * r * m
    if atr:
        for k in (2, 3, 4):
            v[f"{k}×ATR15"] = entry - sg * k * atr
        lv = [p for (_i, t, p) in fr if (t == "L" and p < entry)] if long_ else [p for (_i, t, p) in fr if (t == "H" and p > entry)]
        if lv:
            s = max(lv) if long_ else min(lv)   # найближчий структурний екстремум 15m (до 24 год) за входом
            for b in (0.0, 0.25, 0.5, 1.0):
                v[f"фрактал15m+{b}ATR"] = s - sg * b * atr
    return v


def block_ci(vals: List[Tuple[int, float]], iters: int = 600, seed: int = 7) -> Tuple[float, float, float]:
    """Середнє і 95% інтервал блоковим бутстрепом за кластерами (хвилина видачі): READY у пачках залежні."""
    if not vals:
        return (0.0, 0.0, 0.0)
    cl: Dict[int, List[float]] = defaultdict(list)
    for k, v in vals:
        cl[k].append(v)
    keys = list(cl)
    rnd = random.Random(seed)
    means = []
    for _ in range(iters):
        s = c = 0.0
        for _k in range(len(keys)):
            g = cl[keys[rnd.randrange(len(keys))]]
            s += sum(g)
            c += len(g)
        means.append(s / c if c else 0.0)
    means.sort()
    allv = [v for _k, v in vals]
    return (sum(allv) / len(allv), means[int(iters * 0.025)], means[int(iters * 0.975)])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", required=True)
    ap.add_argument("--cache", default="/tmp/ready_cache")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--md", default="")
    ap.add_argument("--max-symbols", type=int, default=0)
    a = ap.parse_args()
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    plans = json.load(open(a.plans))
    now = time.time()
    by_sym: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in plans:
        by_sym[p["symbol"]].append(p)
    ct_min = min(float(p["ct"]) for p in plans)
    ct_max = max(float(p["ct"]) for p in plans)
    d_last = rr._day(min(now, ct_max + H + POST + 3600))
    btc_rows, _m = rr.load_symbol("BTCUSDT", rr._day(ct_min - 86400), d_last, cache, a.offline)
    btc_times = [r[0] for r in btc_rows]
    recs: List[Dict[str, Any]] = []
    syms = sorted(by_sym)[: a.max_symbols or None]
    for si, sym in enumerate(syms, 1):
        ps = by_sym[sym]
        rows, _missing = rr.load_symbol(sym, rr._day(min(float(p["ct"]) for p in ps) - 4 * 86400), rr._day(min(now, max(float(p["ct"]) for p in ps) + H + POST + 3600)), cache, a.offline)
        if not rows:
            continue
        times = [r[0] for r in rows]
        for p in ps:
            ct, vt = float(p["ct"]), float(p["vt"])
            entry, sl, tp1 = float(p["entry"]), float(p["sl"]), float(p["tp1"])
            long_ = str(p["direction"]).upper() != "SHORT"
            bars = bars15(rows, times, ct)
            atr = atr_of(bars)
            fr = fractals(bars)
            base = walk(rows, times, ct, vt, entry, sl, tp1, long_)
            if base["status"] in ("NO_DATA", "NOT_FILLED"):
                continue
            rec: Dict[str, Any] = {"mid": p["mid"], "ct": ct, "dir": "LONG" if long_ else "SHORT", "sym": sym, "regime": p.get("regime"), "risk_pct": abs(entry - sl) / entry * 100, "tp1_pct": abs(tp1 - entry) / entry * 100,
                                   "atr_pct": (atr / entry * 100) if atr else None, "btc4h": rr.ret_pct(btc_rows, btc_times, ct, 4 * 3600), "hr": datetime.fromtimestamp(ct, tz=timezone.utc).hour,
                                   "var": {}, "base": base}
            lv = h1_levels(rows, times, ct)
            adv = [x for _n, x in lv if (x < entry if long_ else x > entry)]
            if adv:
                nl = max(adv) if long_ else min(adv)
                dl = abs(entry - nl)
                rec["lvl_q"] = abs(entry - sl) / dl if dl > 0 else None   # <1: стоп ПЕРЕД найближчим рівнем; >1: за ним
                rec["lvl_dist_atr"] = (dl / atr) if atr else None
                rec["lvl_pct"] = dl / entry * 100
            for name, slv in stop_variants(entry, sl, long_, atr, fr).items():
                res = base if name == "поточний" else walk(rows, times, ct, vt, entry, slv, tp1, long_)
                if res["status"] in ("NO_DATA", "NOT_FILLED"):
                    continue
                rec["var"][name] = {"res": res["status"], "R": r_multiple(res, entry, slv, tp1, long_), "risk_pct": abs(entry - slv) / entry * 100}
            # після SL: що далі за POST (лише якщо даних вистачає)
            if base["status"] == "SL" and rows[-1][0] + 60.0 >= base["t_exit"] + POST:
                r0 = abs(entry - sl)
                j = base["j_exit"] + 1
                end = base["t_exit"] + POST
                adverse = 0.0
                tp_hit = reclaimed = False
                t_tp = t_rc = None
                two_first = None   # TP1 раніше, ніж ще 1R проти (в бік від стопу) — для порівняння з блуканням
                while j < len(rows) and rows[j][0] < end:
                    t, hi, lo = rows[j][0], rows[j][2], rows[j][3]
                    adverse = max(adverse, ((sl - lo) if long_ else (hi - sl)) / r0)
                    if not reclaimed and ((hi >= entry) if long_ else (lo <= entry)):
                        reclaimed, t_rc = True, t - base["t_exit"]
                    if two_first is None:
                        up = (hi >= tp1) if long_ else (lo <= tp1)
                        dn = ((sl - lo) if long_ else (hi - sl)) >= r0
                        if up and not dn:
                            two_first = True
                        elif dn and not up:
                            two_first = False
                    if not tp_hit and ((hi >= tp1) if long_ else (lo <= tp1)):
                        tp_hit, t_tp = True, t - base["t_exit"]
                    j += 1
                tp1d = abs(tp1 - entry)
                rec["after"] = {"adverse_R": adverse, "tp1": tp_hit, "t_tp": t_tp, "reclaim": reclaimed, "t_rc": t_rc, "two_first": two_first, "rw_two_first": r0 / (r0 + r0 + tp1d), "mfe_R": base["mfe"] / r0, "mae_R": base["mae"] / r0}
            recs.append(rec)
        if si % 25 == 0:
            print(f"[stop] {si}/{len(syms)}", file=sys.stderr, flush=True)
    L: List[str] = []
    P = L.append
    P("# Stop Engine: дослідження на replay (1m Binance архів; лише дослідження)\n")
    P(f"Плани з повним горизонтом {int(H / 3600)} год і виконаним входом: **N={len(recs)}** (із {len(plans)}). Комісія кола {FEE * 100:.1f}% від номіналу; результат у R при незмінному ризику в $ (розмір позиції = ризик$ / відстань до стопу).\n")
    if not recs:
        P("НЕМАЄ ДАНИХ — НЕ ПЕРЕВІРЕНО.")
        print("\n".join(L))
        return 1
    # ---- 1) після SL
    af = [r for r in recs if "after" in r]
    P(f"## 1. Що відбувається ПІСЛЯ поточного SL (N={len(af)} стопів із даними ще {int(POST / 3600)} год)\n")
    if af:
        n = len(af)
        adv = sorted(r["after"]["adverse_R"] for r in af)
        P("| Показник | Значення |\n|---|---|")
        P(f"| Ціна пішла ще далі проти сценарію ≥1R за {int(POST / 3600)} год | {sum(1 for x in adv if x >= 1) / n * 100:.0f}% |")
        P(f"| Додатковий рух проти сценарію після стопу (p50 / p75 / p90), R | {adv[n // 2]:.2f} / {adv[3 * n // 4]:.2f} / {adv[int(n * .9)]:.2f} |")
        P(f"| Ціна повернулась до точки входу (reclaim) | {sum(1 for r in af if r['after']['reclaim']) / n * 100:.0f}% (p50 часу {sorted(r['after']['t_rc'] for r in af if r['after']['t_rc'] is not None)[len([1 for r in af if r['after']['t_rc'] is not None]) // 2] / 60 if any(r['after']['t_rc'] is not None for r in af) else 0:.0f} хв) |")
        P(f"| Згодом досягла TP1 (протягом {int(POST / 3600)} год після стопу) | {sum(1 for r in af if r['after']['tp1']) / n * 100:.0f}% |")
        tf = [r for r in af if r["after"]["two_first"] is not None]
        if tf:
            P(f"| TP1 раніше, ніж ще 1R проти (після стопу) — факт | {sum(1 for r in tf if r['after']['two_first']) / len(tf) * 100:.0f}% (N={len(tf)}) |")
            P(f"| те саме для випадкової ціни без зносу (r/(2r+TP1)) | {sum(r['after']['rw_two_first'] for r in tf) / len(tf) * 100:.0f}% |")
        mf = sorted(r["after"]["mfe_R"] for r in af)
        ma = sorted(r["after"]["mae_R"] for r in af)
        P(f"| До стопу: MFE p50, R | {mf[n // 2]:.2f} |")
        P(f"| До стопу: MAE p50, R | {ma[n // 2]:.2f} |")
        P("\nТлумачення без вигадок: якщо частка «TP1 після стопу» ≈ базису випадкової ціни, стоп НЕ був просто збором ліквідності перед рухом; якщо вона помітно вища — стоп стояв у зоні overshoot.")
    # ---- 2) геометрія
    P("\n## 2. Залежність від геометрії: факт проти «блукання без зносу» (ті самі відстані)\n")
    P("Серед вирішених (TP1 або SL за горизонт). RW = середнє r/(r+TP1) по планах групи, де r — відстань до стопу, TP1 — відстань до цілі. Якщо факт ≈ RW у кожній групі, залежність — **наслідок геометрії**, а не окремий дефект стопу.\n")

    def geo(title: str, keyf: Callable[[Dict[str, Any]], str]) -> None:
        g: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in recs:
            g[keyf(r)].append(r)
        P(f"\n### {title}\n")
        P("| Група | N | TP1 | SL | нічого | TP1/(TP1+SL) факт | RW | різниця |\n|---|---|---|---|---|---|---|---|")
        for k in sorted(g):
            xs = g[k]
            st = [r["base"]["status"] for r in xs]
            t1, s1, nn = st.count("TP1"), st.count("SL"), st.count("NONE")
            res = t1 + s1
            rw = [r["risk_pct"] / (r["risk_pct"] + r["tp1_pct"]) for r in xs if r["base"]["status"] in ("TP1", "SL")]
            if res:
                P(f"| {k} | {len(xs)} | {t1 / len(xs) * 100:.0f}% | {s1 / len(xs) * 100:.0f}% | {nn / len(xs) * 100:.0f}% | {t1 / res * 100:.1f}% | {sum(rw) / len(rw) * 100:.1f}% | {(t1 / res - sum(rw) / len(rw)) * 100:+.1f} п.п. |")

    def q4(vals: List[float]) -> List[float]:
        s = sorted(vals)
        return [s[len(s) // 4], s[len(s) // 2], s[3 * len(s) // 4]]
    qr = q4([r["risk_pct"] for r in recs])
    geo("Відстань до стопу (%)", lambda r: "<%.2f" % qr[0] if r["risk_pct"] < qr[0] else ("%.2f–%.2f" % (qr[0], qr[1]) if r["risk_pct"] < qr[1] else ("%.2f–%.2f" % (qr[1], qr[2]) if r["risk_pct"] < qr[2] else "≥%.2f" % qr[2])))
    rr_ = [r["tp1_pct"] / r["risk_pct"] for r in recs]
    qq = q4(rr_)
    geo("TP1 / стоп", lambda r: ("<%.1f" % qq[0] if r["tp1_pct"] / r["risk_pct"] < qq[0] else ("%.1f–%.1f" % (qq[0], qq[1]) if r["tp1_pct"] / r["risk_pct"] < qq[1] else ("%.1f–%.1f" % (qq[1], qq[2]) if r["tp1_pct"] / r["risk_pct"] < qq[2] else "≥%.1f" % qq[2]))))
    ra = [r["risk_pct"] / r["atr_pct"] for r in recs if r["atr_pct"]]
    if ra:
        qa = q4(ra)
        geo("Стоп у ATR(15m)", lambda r: "н/д" if not r["atr_pct"] else ("<%.2f" % qa[0] if r["risk_pct"] / r["atr_pct"] < qa[0] else ("%.2f–%.2f" % (qa[0], qa[1]) if r["risk_pct"] / r["atr_pct"] < qa[1] else ("%.2f–%.2f" % (qa[1], qa[2]) if r["risk_pct"] / r["atr_pct"] < qa[2] else "≥%.2f" % qa[2]))))
    # ---- 3) варіанти стопу
    P("\n## 3. Альтернативні стопи при незмінному ризику в $ (середнє R на план, 24 год, комісія враховано)\n")
    names = sorted({k for r in recs for k in r["var"]}, key=lambda s: (s != "поточний", s))
    t_mid = sorted(r["ct"] for r in recs)[len(recs) // 2]
    P("Парне порівняння з поточним на ТІЙ САМІЙ підмножині планів. Інтервал — блоковий бутстреп за хвилиною видачі.\n")
    P("| Варіант | N | медіана стопу, % | TP1 | SL | нічого | середнє R | Δ до поточного (95% ІВ) | train ΔR | test ΔR |\n|---|---|---|---|---|---|---|---|---|---|")
    summary: Dict[str, Tuple[float, float]] = {}
    for nm in names:
        xs = [r for r in recs if nm in r["var"] and r["var"][nm]["R"] is not None and "поточний" in r["var"] and r["var"]["поточний"]["R"] is not None]
        if not xs:
            continue
        st = [r["var"][nm]["res"] for r in xs]
        d = [(int(r["ct"] // 60), r["var"][nm]["R"] - r["var"]["поточний"]["R"]) for r in xs]
        m, lo, hi = block_ci(d)
        dtr = [v for (k, v), r in zip(d, xs) if r["ct"] < t_mid]
        dte = [v for (k, v), r in zip(d, xs) if r["ct"] >= t_mid]
        mr = sum(r["var"][nm]["R"] for r in xs) / len(xs)
        rp = sorted(r["var"][nm]["risk_pct"] for r in xs)
        P(f"| {nm} | {len(xs)} | {rp[len(rp) // 2]:.2f} | {st.count('TP1') / len(xs) * 100:.0f}% | {st.count('SL') / len(xs) * 100:.0f}% | {st.count('NONE') / len(xs) * 100:.0f}% | {mr:+.3f} | {m:+.3f} ({lo:+.3f}…{hi:+.3f}) | {(sum(dtr) / len(dtr) if dtr else 0):+.3f} | {(sum(dte) / len(dte) if dte else 0):+.3f} |")
        summary[nm] = (sum(dtr) / len(dtr) if dtr else -9, sum(dte) / len(dte) if dte else -9)
    cand = {k: v for k, v in summary.items() if k != "поточний"}
    if cand:
        best = max(cand, key=lambda k: cand[k][0])
        P(f"\nВибір на train (1-ша половина часу): **{best}** (train ΔR {cand[best][0]:+.3f}) → на test (2-га половина) ΔR **{cand[best][1]:+.3f}**. Якщо test ≤ 0 або інтервал у таблиці містить 0 — переваги не доведено.")
        # ---- 4) зрізи для поточного і вибраного
        P("\n## 4. Зрізи (середнє R: поточний → вибраний на train)\n")
        P("| Зріз | N | TP1/SL поточного | R поточний | R вибраний |\n|---|---|---|---|---|")

        def cut(title: str, keyf: Callable[[Dict[str, Any]], str]) -> None:
            g: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for r in recs:
                if best in r["var"] and r["var"][best]["R"] is not None and r["var"]["поточний"]["R"] is not None:
                    g[keyf(r)].append(r)
            for k in sorted(g):
                xs = g[k]
                st = [r["var"]["поточний"]["res"] for r in xs]
                P(f"| {title}: {k} | {len(xs)} | {st.count('TP1') / len(xs) * 100:.0f}% / {st.count('SL') / len(xs) * 100:.0f}% | {sum(r['var']['поточний']['R'] for r in xs) / len(xs):+.3f} | {sum(r['var'][best]['R'] for r in xs) / len(xs):+.3f} |")
        cut("напрям", lambda r: r["dir"])
        cut("BTC 4 год", lambda r: "н/д" if r["btc4h"] is None else ("за напрямом" if r["btc4h"] * (1 if r["dir"] == "LONG" else -1) > 0.3 else "проти напряму" if r["btc4h"] * (1 if r["dir"] == "LONG" else -1) < -0.3 else "нейтрально"))
        cut("сесія", lambda r: "Азія" if r["hr"] < 8 else "Лондон" if r["hr"] < 13 else "NY" if r["hr"] < 21 else "пізній")
        cut("режим (thesis)", lambda r: str(r.get("regime")))
    # ---- 5) стоп відносно найближчого рівня ліквідності
    P("\n## 5. Де поточний стоп відносно найближчого рівня (H1-фрактал за 72 год або PDH/PDL) — без параметрів\n")
    P("q = відстань до стопу / відстань до найближчого рівня за входом у бік стопу. q<1: стоп стоїть ПЕРЕД рівнем (рівень далі за стоп); q>1: стоп ЗА рівнем (рівень «захищає» стоп). Групи розбиті за q, порогів не підбираю.\n")
    gq: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        q = r.get("lvl_q")
        if q is None:
            gq["рівня немає"].append(r)
        elif q < 0.5:
            gq["a) q<0,5 (рівень далеко за стопом)"].append(r)
        elif q < 1.0:
            gq["b) 0,5–1,0 (стоп перед рівнем)"].append(r)
        elif q < 1.5:
            gq["c) 1,0–1,5 (стоп трохи за рівнем)"].append(r)
        else:
            gq["d) ≥1,5 (стоп далеко за рівнем)"].append(r)
    P("| Група | N | TP1 | SL | нічого | середнє R (поточний) | R (3×ATR15) | R (4×ATR15) |\n|---|---|---|---|---|---|---|---|")
    for k in sorted(gq):
        xs = gq[k]
        st = [r["var"]["поточний"]["res"] for r in xs if "поточний" in r["var"]]
        if not st:
            continue
        def mr(nm: str, xs=xs) -> str:
            v = [r["var"][nm]["R"] for r in xs if nm in r["var"] and r["var"][nm]["R"] is not None]
            return f"{sum(v) / len(v):+.3f}" if v else "—"
        P(f"| {k} | {len(xs)} | {st.count('TP1') / len(st) * 100:.0f}% | {st.count('SL') / len(st) * 100:.0f}% | {st.count('NONE') / len(st) * 100:.0f}% | {mr('поточний')} | {mr('3×ATR15')} | {mr('4×ATR15')} |")
    dd = sorted(r["lvl_dist_atr"] for r in recs if r.get("lvl_dist_atr") is not None)
    if dd:
        P(f"\nВідстань від входу до найближчого рівня за стопом: p25 / p50 / p75 = {dd[len(dd) // 4]:.1f} / {dd[len(dd) // 2]:.1f} / {dd[3 * len(dd) // 4]:.1f} ATR15.")
    out = "\n".join(L)
    print(out)
    if a.md:
        Path(a.md).write_text(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

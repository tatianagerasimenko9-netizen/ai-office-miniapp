#!/usr/bin/env python3
"""Зведення replay Brain v2.1 по ВСІХ вікнах (A–G, ~3 місяці): валовий/чистий E[R], вплив витрат, розріз за ризиком (cost_r), напрямом, контекстом BTC, сесіями.
Протокол без підгонки: кандидати формулюються за механізмом (витрати) і вибираються за вікнами A–C (DISCOVERY); перевірка — на D–G (HOLDOUT), які при виборі не використовувались.
Вхід: каталог з підкаталогами replay-<ПЕРІОД>-<СИМВОЛ>/out_*.json. Використання: python scripts/replay_pooled_study.py <каталог> [OUT.json]"""
import json
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import binance_vision_fetch as BV  # noqa: E402

COST_PCT = 0.15
SEED = 20261012
WIN = {"A": ("2026-09-25", 14), "B": ("2026-10-09", 14), "C": ("2026-10-11", 2), "D": ("2026-08-28", 14), "E": ("2026-08-14", 14), "F": ("2026-07-31", 14), "G": ("2026-07-17", 14)}
DISCOVERY, HOLDOUT = ("A", "B", "C"), ("D", "E", "F", "G")


def load(root):
    rows = []
    for d in sorted(Path(root).glob("replay-*")):
        per = d.name.split("-")[1]
        for p in d.glob("**/*.json"):
            j = json.loads(p.read_text())
            if j.get("error"):
                continue
            for r in j.get("counterfactual_rows", []):
                if r["source"] != "BRAIN":
                    continue
                v = r["variants"]["V0_current"]
                if v.get("r_net") is None or not r.get("risk_pct"):
                    continue
                cr = COST_PCT / float(r["risk_pct"])
                vv = r["variants"]
                rows.append({"v9": (vv.get("V9_be_after_1R") or {}).get("r_net"), "v10": (vv.get("V10_be_after_0.5R") or {}).get("r_net"), "per": per, "sym": r.get("symbol") or j["symbol"], "dir": r["dir"], "ts": float(r["ts_bar"]), "net": float(v["r_net"]), "gross": float(v["r_net"]) + cr, "cost_r": cr,
                             "risk_pct": float(r["risk_pct"]), "out": v.get("outcome"), "session": r.get("session"), "late": bool(r.get("late")), "r_tp1": r.get("r_tp1")})
    return rows


def ci(vals_by_cluster, B=1500):
    cl = list(vals_by_cluster.values())
    if len(cl) < 5:
        return None
    rng = random.Random(SEED)
    ms = []
    for _ in range(B):
        s = [rng.choice(cl) for _ in cl]
        n = sum(len(x) for x in s)
        ms.append(sum(sum(x) for x in s) / n)
    ms.sort()
    return ms[int(0.025 * B)], ms[int(0.975 * B)]


def st(rows, key="net", label=""):
    if not rows:
        return f"{label:<40} n=0"
    by = defaultdict(list)
    for r in rows:
        by[(r["per"], r["ts"])].append(r[key])
    v = [r[key] for r in rows]
    c = ci(by)
    return f"{label:<40} n={len(rows):<5} кл.={len(by):<5} E[R]={statistics.mean(v):+.3f}" + (f" CI[{c[0]:+.2f};{c[1]:+.2f}]" if c else "")


def main(root, out="replay_pooled.json"):
    rows = load(root)
    L = []
    P = L.append
    P(f"# Replay Brain v2.1 (сирий, без live-гейтів) · вікна A–G · подій: {len(rows)} · витрати кола {COST_PCT}%")
    P("\n## 1. По вікнах: чистий/валовий E[R], середня частка витрат")
    P("вікно | подій | E[R] net | E[R] gross | cost_r сер. | LONG net | SHORT net | BTC дрейф вікна")
    btc_cache = {}
    for per in sorted(WIN):
        rr = [r for r in rows if r["per"] == per]
        if not rr:
            continue
        e, dd = WIN[per]
        end_d = date.fromisoformat(e)
        try:
            b = BV.fetch("BTCUSDT", "15m", end_d - timedelta(days=dd + 8), end_d + timedelta(days=1))
            btc_cache[per] = b
            t0 = (end_d - timedelta(days=dd)).toordinal() * 86400.0 - 62135596800.0
            t1 = end_d.toordinal() * 86400.0 - 62135596800.0
            i0, i1 = int(np.searchsorted(b["t"], t0)), int(np.searchsorted(b["t"], t1)) - 1
            drift = f"{(b['c'][i1] / b['c'][i0] - 1) * 100:+.1f}%"
        except Exception:  # noqa: BLE001
            drift = "н/д"
        lg, sh = [r["net"] for r in rr if r["dir"] == "LONG"], [r["net"] for r in rr if r["dir"] == "SHORT"]
        P(f"{per} ({'DISC' if per in DISCOVERY else 'HOLD'}) | {len(rr)} | {statistics.mean(r['net'] for r in rr):+.3f} | {statistics.mean(r['gross'] for r in rr):+.3f} | {statistics.mean(r['cost_r'] for r in rr):.3f} | "
          f"{(statistics.mean(lg) if lg else float('nan')):+.3f} (n={len(lg)}) | {(statistics.mean(sh) if sh else float('nan')):+.3f} (n={len(sh)}) | {drift}")
    P("")
    P(st(rows, "net", "ВСІ вікна · net"))
    P(st(rows, "gross", "ВСІ вікна · gross (до витрат)"))
    P(st([r for r in rows if r["per"] in DISCOVERY], "net", "DISCOVERY A–C · net"))
    P(st([r for r in rows if r["per"] in HOLDOUT], "net", "HOLDOUT D–G · net"))
    P(st([r for r in rows if r["per"] in HOLDOUT], "gross", "HOLDOUT D–G · gross"))
    P("\n## 2. Витрати в R (механізм): розріз за ризиком угоди, % ціни (cost_r = 0,15/risk)")
    buckets = [(0, 0.5), (0.5, 0.75), (0.75, 1.0), (1.0, 1.5), (1.5, 99)]
    for lo, hi in buckets:
        for nm, grp in (("A–C", DISCOVERY), ("D–G", HOLDOUT)):
            sub = [r for r in rows if r["per"] in grp and lo <= r["risk_pct"] < hi]
            P(st(sub, "net", f"ризик {lo}–{hi}% · {nm} · net") + ("  gross=%+.3f" % statistics.mean(r["gross"] for r in sub) if sub else ""))
    P("\n## 3. Кандидат-правило за механізмом (формулюється на A–C, перевіряється на D–G): мінімальний ризик угоди (мін. відстань SL, % ціни)")
    for thr in (0.5, 0.75, 1.0, 1.25):
        d = [r for r in rows if r["per"] in DISCOVERY]
        h = [r for r in rows if r["per"] in HOLDOUT]
        P(f"поріг ризику ≥{thr}% · A–C: лишилось {sum(1 for r in d if r['risk_pct'] >= thr)}/{len(d)}, E[R]={statistics.mean([r['net'] for r in d if r['risk_pct'] >= thr] or [float('nan')]):+.3f}; "
          f"D–G: лишилось {sum(1 for r in h if r['risk_pct'] >= thr)}/{len(h)}, E[R]={statistics.mean([r['net'] for r in h if r['risk_pct'] >= thr] or [float('nan')]):+.3f} (без фільтра {statistics.mean(r['net'] for r in h):+.3f})")
    P("\n## 4. Напрям (усі вікна) та за вікнами")
    for dname in ("LONG", "SHORT"):
        P(st([r for r in rows if r["dir"] == dname], "net", f"{dname} · усі"))
        P(st([r for r in rows if r["dir"] == dname and r["per"] in HOLDOUT], "net", f"{dname} · HOLDOUT"))
    P("\n## 5. Контекст BTC 24h: ЗА напрямом / ПРОТИ (усі вікна)")
    w_by, a_by = defaultdict(list), defaultdict(list)
    wl, al = [], []
    for r in rows:
        b = btc_cache.get(r["per"])
        if b is None:
            continue
        m = b["t"] + 900 <= r["ts"]
        c = b["c"][m]
        if len(c) < 100:
            continue
        up = c[-1] / c[-97] - 1 > 0
        (wl if up == (r["dir"] == "LONG") else al).append(r)
    for lab, grp in (("ЗА напрямом BTC 24h", wl), ("ПРОТИ напряму BTC 24h", al)):
        P(st(grp, "net", lab))
    if wl and al:
        rng = random.Random(SEED)
        keys = sorted({(r["per"], r["ts"]) for r in wl + al})
        wb, ab = defaultdict(list), defaultdict(list)
        for r in wl:
            wb[(r["per"], r["ts"])].append(r["net"])
        for r in al:
            ab[(r["per"], r["ts"])].append(r["net"])
        ds = []
        for _ in range(1500):
            ks = [rng.choice(keys) for _ in keys]
            xa = [v for k in ks for v in wb.get(k, [])]
            xb = [v for k in ks for v in ab.get(k, [])]
            if xa and xb:
                ds.append(statistics.mean(xa) - statistics.mean(xb))
        ds.sort()
        P(f"Δ(за − проти) = {statistics.mean(r['net'] for r in wl) - statistics.mean(r['net'] for r in al):+.3f}  95% CI [{ds[int(0.025 * len(ds))]:+.3f}; {ds[int(0.975 * len(ds))]:+.3f}]")
        per_sign = []
        for per in sorted(WIN):
            x = [r["net"] for r in wl if r["per"] == per]
            y = [r["net"] for r in al if r["per"] == per]
            if x and y:
                per_sign.append((per, round(statistics.mean(x) - statistics.mean(y), 3)))
        P("Δ за вікнами: " + ", ".join(f"{a}:{b:+.3f}" for a, b in per_sign))
    P("\n## 6. Сесії (усі вікна / HOLDOUT)")
    for s in sorted({r["session"] for r in rows if r["session"]}):
        P(st([r for r in rows if r["session"] == s], "net", f"{s} · усі") + "   | " + st([r for r in rows if r["session"] == s and r["per"] in HOLDOUT], "net", "HOLD"))
    P("\n## 7. LATE_SWEEP (рівень уже приймався) vs решта")
    P(st([r for r in rows if r["late"]], "net", "late=True"))
    P(st([r for r in rows if not r["late"]], "net", "late=False"))
    P("\n## 8. Супровід (shadow): беззбитковість після +1R / +0,5R проти V0 на ТИХ САМИХ подіях (парна різниця)")
    for key, lab in (("v9", "V9 BE після +1R"), ("v10", "V10 BE після +0,5R")):
        sub = [r for r in rows if r.get(key) is not None]
        if not sub:
            P(f"{lab}: даних немає (артефакти без цього варіанту)")
            continue
        for nm, grp in (("усі", None), ("A–C", DISCOVERY), ("D–G", HOLDOUT)):
            g = [r for r in sub if grp is None or r["per"] in grp]
            by = defaultdict(list)
            for r in g:
                by[(r["per"], r["ts"])].append(r[key] - r["net"])
            d = [r[key] - r["net"] for r in g]
            c = ci(by)
            P(f"{lab} · {nm}: n={len(g)} E[R] варіанта={statistics.mean(r[key] for r in g):+.3f} V0={statistics.mean(r['net'] for r in g):+.3f} Δ={statistics.mean(d):+.3f}" + (f" CI[{c[0]:+.3f};{c[1]:+.3f}]" if c else ""))
        P("  Δ за вікнами: " + ", ".join(f"{per}:{statistics.mean([r[key] - r['net'] for r in sub if r['per'] == per]):+.3f}" for per in sorted(WIN) if any(r['per'] == per for r in sub)))
    txt = "\n".join(L)
    print(txt)
    Path(out).write_text(json.dumps({"report": txt}, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "replay_pooled.json")

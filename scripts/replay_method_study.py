#!/usr/bin/env python3
"""Methodology SHADOW on the historical Brain v2.1 replay (Binance Futures, closed bars only).

Input: directory with replay-<PERIOD>-<SYMBOL>/out_*.json (counterfactual_rows carry `mt`: rule -> P/F/U).
Output: coverage, baseline (all READY), per-rule PASS vs FAIL slices with cluster-bootstrap CI of the
difference in net R, DISCOVERY (A-C) vs HOLDOUT (D-G) consistency, LONG/SHORT, sessions, entry delay,
a multiple-comparison check and an explicit limitations section. Read-only report: no gate is changed.
Usage: python scripts/replay_method_study.py <dir> [OUT.json]
"""
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay_pooled_study as P  # noqa: E402

MIN_N = 20


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
                vv = r["variants"]
                mt = r.get("mt") or {}
                rows.append({"per": per, "sym": r.get("symbol") or j["symbol"], "dir": r["dir"], "ts": float(r["ts_bar"]),
                             "net": float(v["r_net"]), "out": v.get("outcome"), "session": r.get("session"),
                             "d15": (vv.get("V1_delay_15m") or {}).get("r_net"), "d30": (vv.get("V2_delay_30m") or {}).get("r_net"),
                             "d60": (vv.get("V3_delay_60m") or {}).get("r_net"),
                             "s": mt.get("s") or {}, "hyp": set(mt.get("hyp") or []), "mt_err": mt.get("error"), "has_mt": "s" in mt})
    return rows


def diff_ci(a, b, B=1500):
    """Cluster bootstrap (cluster = period+bar) of mean(a) - mean(b)."""
    ca, cb = defaultdict(list), defaultdict(list)
    for r in a:
        ca[(r["per"], r["ts"])].append(r["net"])
    for r in b:
        cb[(r["per"], r["ts"])].append(r["net"])
    keys = sorted(set(ca) | set(cb))
    if len(keys) < 10:
        return None
    rng = random.Random(P.SEED)
    out = []
    for _ in range(B):
        pick = [rng.choice(keys) for _ in keys]
        xa = [v for k in pick for v in ca.get(k, ())]
        xb = [v for k in pick for v in cb.get(k, ())]
        if xa and xb:
            out.append(statistics.mean(xa) - statistics.mean(xb))
    if len(out) < B * 0.8:
        return None
    out.sort()
    return out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def mean(rs, key="net"):
    v = [r[key] for r in rs if r.get(key) is not None]
    return statistics.mean(v) if v else None


def main(root, out="replay_method.json"):
    rows = load(root)
    L, p = [], None
    L_append = L.append
    p = L_append
    ok = [r for r in rows if r["has_mt"]]
    p(f"# Методологія SHADOW на replay Brain v2.1 · READY: {len(rows)} · з методологічним trace: {len(ok)} · помилки trace: {sum(1 for r in rows if r['mt_err'])} · витрати {P.COST_PCT}%")
    if not ok:
        txt = "\n".join(L + ["Немає даних з `mt` — replay потрібно запускати з поточним кодом."])
        print(txt)
        Path(out).write_text(json.dumps({"n": len(rows), "report": txt}, ensure_ascii=False))
        return
    cnt = Counter(len(r["s"]) for r in ok)
    p(f"правил з входами на один READY (replay, без equity/журналу/календаря/SMC): середнє {statistics.mean(len(r['s']) for r in ok):.1f}, мін {min(cnt)}, макс {max(cnt)}")
    p("\n## 1. База: усі READY")
    p(P.st(ok, "net", "усі"))
    for d in ("LONG", "SHORT"):
        sub = [r for r in ok if r["dir"] == d]
        p(P.st(sub, "net", d) + f"  TP1={sum(1 for r in sub if r['out']=='TP1')} SL={sum(1 for r in sub if r['out']=='SL')} інше={sum(1 for r in sub if r['out'] not in ('TP1','SL'))}")
    p("затримка входу (середній net R): V0 {:+.3f} · +15хв {} · +30хв {} · +60хв {}".format(
        mean(ok), *(f"{mean(ok, k):+.3f}" if mean(ok, k) is not None else "—" for k in ("d15", "d30", "d60"))))
    p("\n## 2. По кожному правилу: PASS проти FAIL (net R; Δ = PASS − FAIL, CI кластерний bootstrap)")
    rules = sorted({k for r in ok for k in r["s"]})
    sig = 0
    tested = 0
    table = []
    for rid in rules:
        a = [r for r in ok if r["s"].get(rid) == "P"]
        b = [r for r in ok if r["s"].get(rid) == "F"]
        hyp = any(rid in r["hyp"] for r in ok)
        if len(a) < MIN_N or len(b) < MIN_N:
            table.append((rid, f"{rid:<34} PASS n={len(a):<4} FAIL n={len(b):<4} — замало (<{MIN_N}) для порівняння{' [ГІПОТЕЗА]' if hyp else ''}"))
            continue
        tested += 1
        c = diff_ci(a, b)
        d = mean(a) - mean(b)
        cons = []
        for nm, grp in (("A–C", P.DISCOVERY), ("D–G", P.HOLDOUT)):
            xa = [r for r in a if r["per"] in grp]
            xb = [r for r in b if r["per"] in grp]
            cons.append(f"{nm} Δ={mean(xa) - mean(xb):+.3f}" if xa and xb else f"{nm} —")
        excl = bool(c and (c[0] > 0 or c[1] < 0))
        sig += excl
        table.append((rid, f"{rid:<34} PASS n={len(a):<4} E={mean(a):+.3f} · FAIL n={len(b):<4} E={mean(b):+.3f} · Δ={d:+.3f}"
                      + (f" CI[{c[0]:+.2f};{c[1]:+.2f}]" if c else "") + f" · {'; '.join(cons)}{' [ГІПОТЕЗА]' if hyp else ''}{' ◀ CI без нуля' if excl else ''}"))
    for _, line in table:
        p(line)
    p(f"\nПорівнянь із достатнім n: {tested}; CI без нуля: {sig}. Очікувано лише випадково при 95% CI: ≈{tested * 0.05:.1f}. Без поправки на множинні порівняння це НЕ доказ переваги.")
    p("\n## 3. Кількість FAIL серед правил із входами (композит, лише мітка)")
    by = defaultdict(list)
    for r in ok:
        by[min(sum(1 for v in r["s"].values() if v == "F"), 6)].append(r)
    for k in sorted(by):
        p(P.st(by[k], "net", f"FAIL-правил={k}{'+' if k == 6 else ''}"))
    p("\n## 4. Сесії (база)")
    bs = defaultdict(list)
    for r in ok:
        bs[r["session"] or "?"].append(r)
    for k in sorted(bs):
        p(P.st(bs[k], "net", f"сесія={k}"))
    p("\n## Обмеження")
    p("- Replay: 7 вікон × 29 символів, лише читання Binance Futures; результат — мітки, а не торговий фільтр. Gate не змінюється.")
    p("- READY у вікні сильно корелюють (кластери за часом/ринком); n малий; CI кластерні, поправки на множинні порівняння немає.")
    p("- У replay відсутні equity, paper-журнал, календар новин і SMC → правила ризику/сесій/SMC тут не оцінюються (UNKNOWN), їх перевіряє тільки live SHADOW.")
    p("- Правила з ГІПОТЕЗА-основою (форма M5/M1, TF підтвердження, пороги SMC) не є підтвердженням джерела.")
    p("- Відсутність різниці = методологія не доведена як фільтр; активувати її як бойовий gate на цих даних не можна.")
    txt = "\n".join(L)
    print(txt)
    Path(out).write_text(json.dumps({"n": len(rows), "with_mt": len(ok), "tested": tested, "ci_excl_zero": sig, "report": txt}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3]))

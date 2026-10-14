#!/usr/bin/env python3
"""Ринковий контекст READY на replay Brain v2.1: сесія, напрям BTC, відносна сила, кількість одночасних однонапрямних сигналів.
Вхід: каталог replay-<ПЕРІОД>-<СИМВОЛ>/out_*.json (counterfactual_rows: f.session/btc_1h/rs_1h, variants.V0_current = READY «як є», комісія+прослизання, лише закриті бари).
«Одночасні» (conc_prior) = скільки ІНШИХ монет вже мали READY того ж напряму в попередні WINDOW_H годин ТОГО Ж періоду (відомо на момент рішення, без look-ahead).
Правила-кандидати задано ДО перегляду цифр (див. RULES), підбір порогів не робиться. Висновок «правило допустиме для shadow» лише якщо знак ефекту
однаковий у DISCOVERY (A–C) і HOLDOUT (D–G) і кластерний 95% CI різниці (знятих − залишених) у HOLDOUT не містить 0.
Нічого не змінює в production. Використання: python scripts/replay_market_context_study.py <dir> [OUT.json]"""
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

DISCOVERY, HOLDOUT = ("A", "B", "C"), ("D", "E", "F", "G")
WINDOW_H = 4.0
MIN_N = 30
SEED = 20261014

# Кандидати правил (прапор «зняти» = пропустити вхід). Це ГІПОТЕЗИ для перевірки, не правила Brain.
RULES = {
    "R1_conc>=1": lambda r: r["conc_prior"] >= 1,
    "R2_conc>=2": lambda r: r["conc_prior"] >= 2,
    "R3_btc_against": lambda r: r["btc"] == "AGAINST",
    "R4_beta_only(btc_with & rs_not_with)": lambda r: r["btc"] == "WITH" and r["rs"] != "WITH",
    "R5_rs_against": lambda r: r["rs"] == "AGAINST",
    "R6_retest_not_fresh(повторний тест прийнятого рівня / LATE_SWEEP)": lambda r: r["late"],
    "R7_risk_gt_3_atr15": lambda r: r["risk_atr"] == "≥3.0",
}


def load(root):
    rows = []
    for d in sorted(Path(root).glob("replay-*")):
        per = d.name.split("-")[1]
        for p in d.glob("**/*.json"):
            j = json.loads(p.read_text())
            if j.get("error"):
                continue
            for r in j.get("counterfactual_rows", []):
                if r.get("source") != "BRAIN":
                    continue
                v0 = (r.get("variants") or {}).get("V0_current") or {}
                if v0.get("r_net") is None:
                    continue
                f = r.get("f") or {}
                rows.append({"per": per, "sym": r.get("symbol") or j.get("symbol"), "ts": float(r["ts_bar"]), "dir": r["dir"], "sess": f.get("session") or r.get("session") or "NA",
                             "btc": f.get("btc_1h", "NA"), "rs": f.get("rs_1h", "NA"), "evc": f.get("ev_class", "NA"), "lvc": f.get("lvl_class", "NA"), "late": bool(f.get("retest_not_fresh")),
                             "risk_atr": f.get("risk_atr", "NA"), "tp1_r": f.get("tp1_r", "NA"), "out": v0.get("outcome"), "r": float(v0["r_net"])})
    return rows


def add_concurrency(rows):
    by = defaultdict(list)
    for r in rows:
        by[(r["per"], r["dir"])].append(r)
    for g in by.values():
        g.sort(key=lambda x: x["ts"])
        for i, r in enumerate(g):
            r["conc_prior"] = len({o["sym"] for o in g[:i] if o["sym"] != r["sym"] and 0 < r["ts"] - o["ts"] <= WINDOW_H * 3600})
    return rows


def ci_mean(rows, f, B=1500):
    cl = defaultdict(list)
    for r in rows:
        cl[(r["per"], r["ts"])].append(f(r))
    keys = sorted(cl)
    if len(keys) < 10:
        return None
    rng = random.Random(SEED)
    out = []
    for _ in range(B):
        flat = [v for k in [rng.choice(keys) for _ in keys] for v in cl[k]]
        if flat:
            out.append(statistics.mean(flat))
    out.sort()
    return (round(out[int(0.025 * len(out))], 3), round(out[int(0.975 * len(out)) - 1], 3)) if len(out) > 100 else None


def ci_diff(a, b, B=1500):
    ca, cb = defaultdict(list), defaultdict(list)
    for r in a:
        ca[(r["per"], r["ts"])].append(r["r"])
    for r in b:
        cb[(r["per"], r["ts"])].append(r["r"])
    keys = sorted(set(ca) | set(cb))
    if len(keys) < 10 or not a or not b:
        return None
    rng = random.Random(SEED)
    out = []
    for _ in range(B):
        pk = [rng.choice(keys) for _ in keys]
        xa = [v for k in pk for v in ca.get(k, [])]
        xb = [v for k in pk for v in cb.get(k, [])]
        if xa and xb:
            out.append(statistics.mean(xa) - statistics.mean(xb))
    out.sort()
    return (round(out[int(0.025 * len(out))], 3), round(out[int(0.975 * len(out)) - 1], 3)) if len(out) > 100 else None


def stat(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    sl = sum(1 for r in rows if r["out"] == "SL")
    tp = sum(1 for r in rows if r["out"] == "TP1")
    return {"n": n, "sl_pct": round(100 * sl / n, 1), "tp1_pct": round(100 * tp / n, 1), "mean_r": round(statistics.mean(r["r"] for r in rows), 3), "ci": ci_mean(rows, lambda r: r["r"]) if n >= MIN_N else None}


def table(rows, key, title):
    keys = sorted({key(r) for r in rows}, key=str)
    print(f"\n{title}")
    print(f"{'група':<28}{'період':<11}{'n':>6}{'SL%':>7}{'TP1%':>7}{'середній R':>12}  95% CI")
    out = {}
    for k in keys:
        for name, pers in (("DISCOVERY", DISCOVERY), ("HOLDOUT", HOLDOUT)):
            g = [r for r in rows if key(r) == k and r["per"] in pers]
            s = stat(g)
            out[f"{k}|{name}"] = s
            if s["n"]:
                print(f"{str(k):<28}{name:<11}{s['n']:>6}{s['sl_pct']:>7}{s['tp1_pct']:>7}{s['mean_r']:>12}  {s['ci'] if s['ci'] else 'n<' + str(MIN_N)}")
    return out


def rules(rows):
    print("\nПравила-кандидати: знятих (пропущений вхід) проти залишених; різниця = середній R знятих − залишених (від’ємна = зняття корисне)")
    res = {}
    for name, fn in RULES.items():
        line = {}
        for pn, pers in (("DISCOVERY", DISCOVERY), ("HOLDOUT", HOLDOUT)):
            g = [r for r in rows if r["per"] in pers]
            cut, kept = [r for r in g if fn(r)], [r for r in g if not fn(r)]
            d = (statistics.mean(r["r"] for r in cut) - statistics.mean(r["r"] for r in kept)) if cut and kept else None
            line[pn] = {"cut_n": len(cut), "kept_n": len(kept), "cut_mean": round(statistics.mean(r["r"] for r in cut), 3) if cut else None,
                        "kept_mean": round(statistics.mean(r["r"] for r in kept), 3) if kept else None, "diff": round(d, 3) if d is not None else None, "diff_ci": ci_diff(cut, kept) if len(cut) >= MIN_N else None,
                        "sum_r_all": round(sum(r["r"] for r in g), 1), "sum_r_after_cut": round(sum(r["r"] for r in kept), 1)}
        dd, hh = line["DISCOVERY"], line["HOLDOUT"]
        ok = (dd["diff"] is not None and hh["diff"] is not None and dd["diff"] < 0 and hh["diff"] < 0 and hh["diff_ci"] is not None and hh["diff_ci"][1] < 0)
        line["verdict"] = "ДОПУСТИМО ДЛЯ SHADOW (знак збігся, CI HOLDOUT <0)" if ok else "НЕ ПІДТВЕРДЖЕНО"
        res[name] = line
        print(f"\n{name}: {line['verdict']}")
        for pn in ("DISCOVERY", "HOLDOUT"):
            x = line[pn]
            print(f"  {pn:<10} знято {x['cut_n']:>5} (R {x['cut_mean']}) · залишено {x['kept_n']:>5} (R {x['kept_mean']}) · різниця {x['diff']} CI {x['diff_ci']} · Σ R: усі {x['sum_r_all']} → після зняття {x['sum_r_after_cut']}")
    return res


def main():
    root = sys.argv[1]
    rows = add_concurrency(load(root))
    print(f"Подій Brain READY (replay, V0 як видано): {len(rows)}; періоди: {sorted({r['per'] for r in rows})}; монет: {len({r['sym'] for r in rows})}")
    print(f"Сумарно: DISCOVERY {stat([r for r in rows if r['per'] in DISCOVERY])}\n         HOLDOUT   {stat([r for r in rows if r['per'] in HOLDOUT])}")
    out = {"n": len(rows)}
    out["session"] = table(rows, lambda r: r["sess"], "1. Сесія (за Лондоном/Нью-Йорком/Азією з DST)")
    out["btc"] = table(rows, lambda r: r["btc"], "2. Напрям BTC за 1 год відносно напряму угоди (WITH/AGAINST/FLAT)")
    out["rs"] = table(rows, lambda r: r["rs"], "3. Відносна сила монети проти BTC за 1 год відносно напряму угоди")
    out["btc_x_rs"] = table(rows, lambda r: f"btc={r['btc']}|rs={r['rs']}", "4. BTC × відносна сила")
    out["conc"] = table(rows, lambda r: min(r["conc_prior"], 3), f"5. Скільки інших монет вже мали READY того ж напряму за попередні {WINDOW_H:g} год (3 = 3 і більше)")
    out["event_class"] = table(rows, lambda r: r["evc"], "6. Клас події (SWEEP / LATE_SWEEP / …)")
    out["level_class"] = table(rows, lambda r: r["lvc"], "7. Клас рівня події (сесійний / свінг / добовий …)")
    out["risk_atr"] = table(rows, lambda r: r["risk_atr"], "8. Ризик до SL у ATR(M15)")
    out["rules"] = rules(rows)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

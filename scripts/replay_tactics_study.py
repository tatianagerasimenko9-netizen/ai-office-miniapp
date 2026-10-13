#!/usr/bin/env python3
"""Тактики відносно перешкоди на replay Brain v2.1 (Binance Futures, лише закриті бари, комісія+прослизання, SL перед TP в одному барі).

Вхід: каталог replay-<ПЕРІОД>-<СИМВОЛ>/out_*.json (counterfactual_rows[].tactics, .bucket). Усі варіанти рахуються на ТИХ САМИХ READY-подіях.
Пропущений вхід (MISSED) у тактиці = 0R для події (втрата виграшу видна у різниці з T0).
Розділ 1 — база; 2 — кожна тактика проти T0 (усі / по корзинах перешкоди; DISCOVERY A–C, HOLDOUT D–G); 3 — жорсткий фільтр «перешкода <1R» як контрафакт;
4 — адаптивний вибір (таблиця корзина→тактика, навчена на одній половині, перевірена на іншій, і навпаки); 5 — контролі C1/C2; 6 — висновок.
Нічого не змінює в production. Використання: python scripts/replay_tactics_study.py <dir> [OUT.json]"""
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import tactic as TC  # noqa: E402

DISCOVERY, HOLDOUT = ("A", "B", "C"), ("D", "E", "F", "G")
MIN_N = 30
SEED = 20261013
VARS = TC.TACTICS


def load(root):
    rows = []
    for d in sorted(Path(root).glob("replay-*")):
        per = d.name.split("-")[1]
        for p in d.glob("**/*.json"):
            j = json.loads(p.read_text())
            if j.get("error"):
                continue
            for r in j.get("counterfactual_rows", []):
                if r.get("source") != "BRAIN" or not r.get("tactics") or not r.get("risk_pct"):
                    continue
                t = r["tactics"]
                if t["T0_enter_now"].get("r_net") is None:
                    continue
                rows.append({"per": per, "sym": r.get("symbol") or j.get("symbol"), "ts": float(r["ts_bar"]), "bucket": r.get("bucket"), "dir": r["dir"],
                             "v": {k: (x.get("r_net") if x.get("r_net") is not None else 0.0) for k, x in t.items()},
                             "missed": {k: x.get("r_net") is None for k, x in t.items()}})
                vv = r.get("variants") or {}
                for k in ("V9_be_after_1R", "V10_be_after_0.5R"):
                    x = vv.get(k) or {}
                    rows[-1]["v"][k] = x.get("r_net") if x.get("r_net") is not None else 0.0
    return rows


def mean(x):
    return statistics.mean(x) if x else None


def ci(rows, f, B=1500):
    """Кластерний bootstrap середнього f(row) (кластер = період+бар)."""
    cl = defaultdict(list)
    for r in rows:
        cl[(r["per"], r["ts"])].append(f(r))
    keys = sorted(cl)
    if len(keys) < 10:
        return None
    rng = random.Random(SEED)
    out = []
    for _ in range(B):
        pick = [cl[rng.choice(keys)] for _ in keys]
        flat = [v for g in pick for v in g]
        if flat:
            out.append(statistics.mean(flat))
    out.sort()
    return (round(out[int(0.025 * len(out))], 3), round(out[int(0.975 * len(out)) - 1], 3)) if len(out) > 100 else None


def delta(rows, v):
    return (lambda r: r["v"][v] - r["v"]["T0_enter_now"])


def fmt(rows, f, label):
    if not rows:
        return f"{label:<44} n=0"
    m = mean([f(r) for r in rows]); c = ci(rows, f)
    return f"{label:<44} n={len(rows):<5} {m:+.3f}R" + (f"  CI[{c[0]:+.3f};{c[1]:+.3f}]" if c else "") + ("  ◀ CI без нуля" if c and (c[0] > 0 or c[1] < 0) else "")


def learn_table(train):
    table, detail = {}, {}
    for b in TC.BUCKETS:
        sub = [r for r in train if r["bucket"] == b]
        best, best_d = "T0_enter_now", 0.0
        ds = {}
        for v in VARS[1:]:
            if len(sub) >= MIN_N:
                ds[v] = round(mean([r["v"][v] - r["v"]["T0_enter_now"] for r in sub]), 3)
                if ds[v] > best_d:
                    best, best_d = v, ds[v]
        table[b] = best
        detail[b] = {"n": len(sub), "mean_delta_vs_T0": ds}
    return table, detail


def adaptive(rows, table):
    return lambda r: r["v"][table.get(r["bucket"], "T0_enter_now")] - r["v"]["T0_enter_now"]


def main(root, out="replay_tactics.json"):
    rows = load(root)
    L = []; p = L.append
    disc = [r for r in rows if r["per"] in DISCOVERY]; hold = [r for r in rows if r["per"] in HOLDOUT]
    p(f"# Тактики відносно перешкоди · READY (Brain v2.1, replay): {len(rows)} · discovery A–C {len(disc)} · holdout D–G {len(hold)} · витрати {TC.FEE_RT_PCT}% + {TC.SLIP_BPS} б.п.")
    if len(rows) < 100:
        p("Замало подій (<100) — висновків не робимо.")
        txt = "\n".join(L); print(txt); Path(out).write_text(json.dumps({"n": len(rows), "report": txt}, ensure_ascii=False)); return
    p("\n## 1. База T0 (старий Brain: вхід за ціною READY)")
    T0 = lambda r: r["v"]["T0_enter_now"]   # noqa: E731
    p(fmt(rows, T0, "усі")); p(fmt(disc, T0, "discovery A–C")); p(fmt(hold, T0, "holdout D–G"))
    for b in TC.BUCKETS:
        p(fmt([r for r in rows if r["bucket"] == b], T0, f"корзина {b}"))
    share = {b: round(sum(1 for r in rows if r["bucket"] == b) / len(rows), 3) for b in TC.BUCKETS}
    p(f"частки корзин: {share}  (частка 'перешкода <1R' = {share['OBST_LT_0.5R'] + share['OBST_0.5_1R']:.1%})")
    p("\n## 2. Кожна тактика проти T0 (різниця в R на тих самих подіях; пропуск = 0R)")
    res2 = {}
    for v in VARS[1:]:
        p(f"\n### {v}  (пропущено входів: {sum(1 for r in rows if r['missed'][v])}/{len(rows)})")
        res2[v] = {}
        for lab, sub in (("усі", rows), ("discovery", disc), ("holdout", hold)):
            p("  " + fmt(sub, delta(rows, v), f"{lab}"))
        for b in TC.BUCKETS:
            sub = [r for r in rows if r["bucket"] == b]
            if len(sub) >= MIN_N:
                p("  " + fmt(sub, delta(rows, v), f"  {b}"))
                res2[v][b] = {"n": len(sub), "d": round(mean([delta(rows, v)(r) for r in sub]), 3), "ci": ci(sub, delta(rows, v)),
                              "disc": round(mean([delta(rows, v)(r) for r in sub if r["per"] in DISCOVERY]) or 0, 3), "hold": round(mean([delta(rows, v)(r) for r in sub if r["per"] in HOLDOUT]) or 0, 3)}
    p("\n## 3. Жорсткий фільтр «перешкода до TP1 ближче 1R → пропустити» (контрафакт; Δ = −результат T0 пропущених)")
    close = [r for r in rows if r["bucket"] in ("OBST_LT_0.5R", "OBST_0.5_1R")]
    gate = lambda r: -r["v"]["T0_enter_now"] if r["bucket"] in ("OBST_LT_0.5R", "OBST_0.5_1R") else 0.0   # noqa: E731
    p(f"пропущено б {len(close)} з {len(rows)} ({len(close) / len(rows):.1%}); T0 пропущених: " + fmt(close, T0, "") .strip())
    p(fmt(rows, gate, "Δ на всі події (жорсткий фільтр − T0)")); p(fmt(disc, gate, "  discovery")); p(fmt(hold, gate, "  holdout"))
    p("\n## 4. Адаптивний вибір тактики (таблиця корзина → тактика)")
    tA, dA = learn_table(disc); tB, dB = learn_table(hold)
    p(f"навчено на A–C: {tA}"); p(f"навчено на D–G: {tB}")
    r1 = fmt(hold, adaptive(rows, tA), "A–C → тест на D–G: Δ vs T0"); r2 = fmt(disc, adaptive(rows, tB), "D–G → тест на A–C: Δ vs T0")
    p(r1); p(r2)
    cA, cB = ci(hold, adaptive(rows, tA)), ci(disc, adaptive(rows, tB))
    ok = bool(cA and cA[0] > 0 and cB and cB[0] > 0)
    p("\n## 5. Контролі (абсолютний net R на тих самих подіях; MISSED/NO_DATA = 0R)")
    for k in ("T0_enter_now", "C1_mirror_direction", "C2_momentum_1atr"):
        p(fmt(rows, lambda r, k=k: r["v"][k], k))
    p("\n## 5b. Супровід: перенесення SL на вхід після +0.5R / +1R (V10/V9; рекомендація, не автоматика) проти T0")
    for k in ("V10_be_after_0.5R", "V9_be_after_1R"):
        if all(k in r["v"] for r in rows):
            f = (lambda r, k=k: r["v"][k] - r["v"]["T0_enter_now"])
            p(fmt(rows, f, f"{k} Δ усі")); p(fmt(disc, f, "  discovery")); p(fmt(hold, f, "  holdout"))
            for b in TC.BUCKETS:
                sub = [r for r in rows if r["bucket"] == b]
                if len(sub) >= MIN_N:
                    p(fmt(sub, f, f"  {b}"))
    p("\n## 6. Висновок")
    verdict = "ADOPT_TABLE" if ok else "NOT_PROVEN_KEEP_T0"
    p(f"Адаптивна таблиця: {'ПЕРЕВАГА ПІДТВЕРДЖЕНА в обох напрямах навчання/тесту → можна вмикати як рекомендацію' if ok else 'перевага НЕ підтверджена (CI тесту містить 0 хоча б в одному напрямі) → тактика лишається рекомендацією, T0 за замовчуванням'}.")
    p("Жорсткий фільтр за перешкодою не вмикається як блокувальний, якщо Δ вище не має CI > 0 на всіх подіях і на holdout.")
    p("\n## Обмеження")
    p("- READY у вікні корелюють (кластери за часом/ринком); n обмежений; поправки на множинні порівняння немає (≈3 тактики × 4 корзини).")
    p("- WAIT_BREAK_BARS/LIMIT_BARS/середина зони — ГІПОТЕЗИ (горизонти зафіксовані наперед), не правила з джерел.")
    p("- Replay не моделює реальне виконання (ліміт може не заповнитись інакше, ніж за дотиком); T3 оптимістичний щодо fill.")
    txt = "\n".join(L); print(txt)
    Path(out).write_text(json.dumps({"n": len(rows), "verdict": verdict, "table_A_C": tA, "table_D_G": tB, "detail_A_C": dA, "detail_D_G": dB, "per_tactic": res2,
                                     "ci_A_C_to_D_G": cA, "ci_D_G_to_A_C": cB, "report": txt}, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3]))

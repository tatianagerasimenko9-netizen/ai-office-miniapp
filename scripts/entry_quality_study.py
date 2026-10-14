#!/usr/bin/env python3
"""Якість входів і стопів на replay Brain v2.1 (Binance Futures, лише закриті бари, комісія+прослизання у net R, SL перед TP в одному барі).
Вхід: каталог eq-<ПЕРІОД>-<СИМВОЛ>/*.json з counterfactual_rows[].q (office2/entry_quality.py). DISCOVERY A–C / HOLDOUT D–G.
Питання: (1) як часто після SL ціна все ж досягає початкового TP1; (2) чим пояснюються SL (передчасний вхід / вибито тінню / хибний напрям / без продовження) і яка частка SL — спільний розворот;
(3) чи покращують net R альтернативи входу/стопа на ТИХ САМИХ подіях (пропущений вхід = 0R). Вердикт «ДОПУСТИМО ДЛЯ SHADOW» лише якщо Δ>0 в обох половинах і CI HOLDOUT >0.
Нічого не змінює в production. Використання: python scripts/entry_quality_study.py <dir> [OUT.json]"""
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

DISCOVERY, HOLDOUT = ("A", "B", "C"), ("D", "E", "F", "G")
SEED = 20261014
CLASSES = ("PREMATURE_ENTRY", "STOP_WICK", "WRONG_DIRECTION", "NO_FOLLOWTHROUGH", "NO_DATA")
CLUSTER_H = 2.0


def load(root):
    rows = []
    for d in sorted(Path(root).glob("eq-*")):
        per = d.name.split("-")[1]
        for p in d.glob("**/*.json"):
            j = json.loads(p.read_text())
            if j.get("error"):
                continue
            for r in j.get("counterfactual_rows", []):
                q = r.get("q")
                if r.get("source") != "BRAIN" or not q or q.get("error") or q.get("r") is None:
                    continue
                f = r.get("f") or {}
                t3 = ((r.get("tactics") or {}).get("T3_limit_zone_mid") or {}).get("r_net")
                alt = {k: (v.get("r") if v.get("r") is not None else 0.0) for k, v in (q.get("alt") or {}).items()}
                alt["E1"] = t3 if t3 is not None else 0.0
                rows.append({"per": per, "sym": r.get("symbol") or j.get("symbol"), "ts": float(r["ts_bar"]), "dir": r["dir"], "r0": float(q["r"]), "o": q["o"], "q": q, "alt": alt,
                             "missed": {k: (v.get("r") is None) for k, v in (q.get("alt") or {}).items()},
                             "late": bool(f.get("retest_not_fresh")), "lvc": f.get("lvl_class", "NA"), "sess": f.get("session", "NA")})
    return rows


def ci(rows, fn, B=1500):
    cl = defaultdict(list)
    for r in rows:
        cl[(r["per"], r["ts"])].append(fn(r))
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


def share(rows, pred):
    n = len(rows)
    return (round(100.0 * sum(1 for r in rows if pred(r)) / n, 1) if n else None, n)


def main():
    rows = load(sys.argv[1])
    out = {}
    half = lambda name: [r for r in rows if r["per"] in (DISCOVERY if name == "DISCOVERY" else HOLDOUT)]
    print(f"Подій Brain READY з виміром якості входу: {len(rows)} · періоди {sorted({r['per'] for r in rows})} · монет {len({r['sym'] for r in rows})}")
    for nm in ("DISCOVERY", "HOLDOUT"):
        g = half(nm)
        print(f"{nm}: n={len(g)} · T0 середній net R {round(statistics.mean(r['r0'] for r in g), 3) if g else None} · CI {ci(g, lambda r: r['r0']) if g else None}")

    sl = [r for r in rows if r["o"] == "SL"]
    print(f"\n1. Рекавері після SL (початковий TP1 пізніше). Подій із SL: {len(sl)} із {len(rows)} ({100 * len(sl) / max(1, len(rows)):.1f}%)")
    for nm in ("DISCOVERY", "HOLDOUT", "ВСІ"):
        g = [r for r in (sl if nm == "ВСІ" else [x for x in sl if x in half(nm)]) if r["q"].get("cls") != "NO_DATA"]
        a24, n = share(g, lambda r: r["q"].get("tp1_24h")); a72, _ = share(g, lambda r: r["q"].get("tp1_72h"))
        print(f"  {nm:<10} SL з даними {n:>5}: TP1 досягнуто за 24 год — {a24}% · за 72 год — {a72}%")
    out["recovery"] = {"n_sl": len(sl)}

    print("\n2. Причини SL (правила класифікації — у office2/entry_quality.py, задано наперед)")
    print(f"{'група':<26}{'n SL':>6}" + "".join(f"{c[:16]:>18}" for c in CLASSES[:4]))
    def cls_row(name, g):
        c = Counter(r["q"].get("cls") for r in g if r["q"].get("cls") != "NO_DATA")
        n = sum(c.values())
        print(f"{name:<26}{n:>6}" + "".join(f"{(100 * c[k] / n if n else 0):>17.1f}%" for k in CLASSES[:4]))
        return {k: c[k] for k in CLASSES[:4]}
    out["classes"] = {"all": cls_row("усі SL", sl), "discovery": cls_row("DISCOVERY", [r for r in sl if r in half("DISCOVERY")]), "holdout": cls_row("HOLDOUT", [r for r in sl if r in half("HOLDOUT")]),
                      "late": cls_row("повторний тест рівня", [r for r in sl if r["late"]]), "not_late": cls_row("свіжий sweep/інше", [r for r in sl if not r["late"]]),
                      "session_level": cls_row("рівень = сесійний", [r for r in sl if r["lvc"] == "SESSION"]), "other_level": cls_row("рівень ≠ сесійний", [r for r in sl if r["lvc"] != "SESSION"])}
    ents = [r for r in sl if r["q"].get("deeper") is not None]
    print(f"  Серед SL ціна заходила до дальнього краю зони ДО стопа: {share(ents, lambda r: r['q'].get('deeper'))[0]}% (n={len(ents)})")

    print(f"\n3. Спільний ринковий розворот: SL одного напрямку різних монет у вікні {CLUSTER_H:g} год (того ж періоду)")
    buckets = defaultdict(set)
    for r in sl:
        t = r["q"].get("ts_sl")
        if t is not None:
            buckets[(r["per"], r["dir"], int(t // (CLUSTER_H * 3600)))].add(r["sym"])
    sizes = Counter()
    for r in sl:
        t = r["q"].get("ts_sl")
        if t is not None:
            sizes[min(len(buckets[(r["per"], r["dir"], int(t // (CLUSTER_H * 3600)))]), 5)] += 1
    tot = sum(sizes.values())
    print("  кількість різних монет зі SL у тому ж вікні → частка SL: " + ", ".join(f"{k}{'+' if k == 5 else ''}: {100 * v / max(1, tot):.1f}%" for k, v in sorted(sizes.items())))
    print(f"  SL у кластері з ≥3 монет: {100 * sum(v for k, v in sizes.items() if k >= 3) / max(1, tot):.1f}%  (описово; поріг 3 не є правилом)")
    out["cluster"] = dict(sizes)

    print("\n4. Альтернативи входу/стопа на тих самих подіях: середній net R (пропущений вхід = 0R); Δ = альтернатива − T0")
    names = {"E1": "E1 лімітний вхід у середині зони (T3)", "E2": "E2 лімітний вхід на дальньому краї зони", "SG": "SG SL=екстремум−20% стопа (Герчик-подібний)", "SA": "SA SL=екстремум−1×ATR(M15)"}
    res = {}
    for k, label in names.items():
        line = {}
        for nm in ("DISCOVERY", "HOLDOUT"):
            g = [r for r in half(nm) if k in r["alt"]]
            if not g:
                continue
            d = [r["alt"][k] - r["r0"] for r in g]
            miss = 100 * sum(1 for r in g if r["missed"].get(k, k == "E1" and r["alt"][k] == 0.0)) / len(g)
            line[nm] = {"n": len(g), "alt": round(statistics.mean(r["alt"][k] for r in g), 3), "t0": round(statistics.mean(r["r0"] for r in g), 3), "delta": round(statistics.mean(d), 3),
                        "ci": ci(g, lambda r, k=k: r["alt"][k] - r["r0"]), "missed_pct": round(miss, 1)}
        ok = bool(line.get("DISCOVERY") and line.get("HOLDOUT") and line["DISCOVERY"]["delta"] > 0 and line["HOLDOUT"]["delta"] > 0 and line["HOLDOUT"]["ci"] and line["HOLDOUT"]["ci"][0] > 0)
        line["verdict"] = "ДОПУСТИМО ДЛЯ SHADOW" if ok else "НЕ ПІДТВЕРДЖЕНО"
        res[k] = line
        print(f"\n  {label}: {line['verdict']}")
        for nm in ("DISCOVERY", "HOLDOUT"):
            x = line.get(nm)
            if x:
                print(f"    {nm:<10} n={x['n']:>5} · T0 {x['t0']:>7} → альтернатива {x['alt']:>7} · Δ {x['delta']:>7} CI {x['ci']} · пропущено входів {x['missed_pct']}%")
    out["alternatives"] = res
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

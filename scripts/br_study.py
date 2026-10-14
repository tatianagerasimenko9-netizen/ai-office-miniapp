#!/usr/bin/env python3
"""Зведення B&R · TEST replay: DISCOVERY A–C / HOLDOUT D–G, середній net R з кластерним bootstrap (кластер = період + день), контроль NR, частка SL/TP1.
Усі пороги B&R — ГІПОТЕЗИ; вердикт «НЕ ПІДТВЕРДЖЕНО», якщо знак не збігається в обох половинах або CI HOLDOUT містить 0."""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

DISC, HOLD = "ABC", "DEFG"


def load(root):
    rows = []
    for f in sorted(Path(root).rglob("*.json")):
        j = json.loads(f.read_text())
        if "periods" not in j:
            continue
        for pid, p in j["periods"].items():
            for kind in ("signals", "control_nr"):
                for r in p.get(kind, []) or []:
                    if r.get("r") is not None:
                        rows.append(dict(r, sym=j["symbol"], period=pid, kind=kind, cluster=f"{pid}|{int(r['ts'] // 86400)}"))
    return rows


def mean_ci(rows, B=1500, seed=7):
    if not rows:
        return None
    rnd = random.Random(seed)
    cl = {}
    for r in rows:
        cl.setdefault(r["cluster"], []).append(r["r"])
    keys = list(cl)
    m = sum(r["r"] for r in rows) / len(rows)
    bs = []
    for _ in range(B):
        pick = [cl[rnd.choice(keys)] for _ in keys]
        v = [x for g in pick for x in g]
        bs.append(sum(v) / len(v))
    bs.sort()
    return {"n": len(rows), "mean_r": round(m, 3), "ci": [round(bs[int(B * 0.025)], 3), round(bs[int(B * 0.975)], 3)]}


def main(root, out):
    rows = load(root)
    res = {}
    for kind in ("signals", "control_nr"):
        for name, per in (("DISCOVERY", DISC), ("HOLDOUT", HOLD), ("ALL", DISC + HOLD)):
            sub = [r for r in rows if r["kind"] == kind and r["period"] in per]
            res[f"{kind}|{name}"] = mean_ci(sub)
            if sub:
                res[f"{kind}|{name}"]["sl_share"] = round(sum(1 for r in sub if r["status"] == "SL") / len(sub), 3)
                res[f"{kind}|{name}"]["tp1_share"] = round(sum(1 for r in sub if r["status"] == "TP1") / len(sub), 3)
    d, h = res.get("signals|DISCOVERY"), res.get("signals|HOLDOUT")
    verdict = "НЕ ПІДТВЕРДЖЕНО"
    if d and h and d["mean_r"] > 0 and h["mean_r"] > 0 and h["ci"][0] > 0:
        verdict = "кандидат для подальшого SHADOW (потрібні нові дані)"
    res["verdict"] = verdict
    lines = ["# B&R · TEST replay (ГІПОТЕЗИ порогів; net R після комісії 0,10% і прослизання 5 б.п.)", "", "| Вибірка | n | середній net R | 95% CI | SL | TP1 |", "|---|---|---|---|---|---|"]
    for k, v in res.items():
        if isinstance(v, dict):
            lines.append(f"| {k} | {v['n']} | {v['mean_r']} | {v['ci']} | {v.get('sl_share')} | {v.get('tp1_share')} |")
    lines += ["", f"**Вердикт:** {verdict}", "", "Порівняння з Brain v2.1 лише орієнтовне: інша модель виходу (тут TP1/SL). База Brain у replay-entry-quality: −0,186 R (DISCOVERY), −0,218 R (HOLDOUT)."]
    Path(out).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

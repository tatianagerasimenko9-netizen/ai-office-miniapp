#!/usr/bin/env python3
"""Контекст BTC для подій replay Brain v2.1 (незалежна перевірка гіпотез із живого вікна 10–11.10).
Гіпотези зафіксовано ДО перегляду цих даних (H1: угоди ПРОТИ напряму BTC за 24 год мають нижчий E[R] ніж ЗА напрямом; H2: те саме для 4 год).
Вхід: каталог з out_*.json (scripts/learning_binance_replay.py). Контекст BTC — з закритих 15m-барів до ts_bar (без майбутнього).
Використання: python scripts/replay_context_study.py <каталог> <END YYYY-MM-DD> <DAYS> [OUT.json]"""
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

SEED = 20261012


def load_rows(src):
    rows = []
    for p in sorted(Path(src).glob("**/*.json")):
        j = json.loads(p.read_text())
        if j.get("error"):
            continue
        for r in j.get("counterfactual_rows", []):
            v = r["variants"]["V0_current"]
            if v.get("r_net") is None:
                continue
            rows.append({"sym": r.get("symbol") or j["symbol"], "src": r["source"], "dir": r["dir"], "ts": float(r["ts_bar"]), "R": float(v["r_net"]), "out": v.get("outcome"),
                         "session": r.get("session"), "model": r.get("model"), "late": r.get("late"), "risk_pct": r.get("risk_pct")})
    return rows


def btc_ctx(btc, ts):
    m = btc["t"] + 900 <= ts
    c = btc["c"][m]
    if len(c) < 120:
        return None
    return {"b1": c[-1] / c[-5] - 1, "b4": c[-1] / c[-17] - 1, "b24": c[-1] / c[-97] - 1}


def cboot(by_cl, B=2000, seed=SEED):
    rng = random.Random(seed)
    cl = list(by_cl.values())
    if len(cl) < 4:
        return None
    ms = []
    for _ in range(B):
        s = [rng.choice(cl) for _ in cl]
        n = sum(len(x) for x in s)
        ms.append(sum(sum(x) for x in s) / n if n else 0.0)
    ms.sort()
    return round(ms[int(0.025 * B)], 3), round(ms[int(0.975 * B)], 3)


def diff_boot(a_by, b_by, B=2000, seed=SEED):
    """Різниця E[R] (a − b) кластерним bootstrap за ts_bar."""
    rng = random.Random(seed)
    keys = sorted(set(a_by) | set(b_by))
    if len(keys) < 6:
        return None
    ds = []
    for _ in range(B):
        ks = [rng.choice(keys) for _ in keys]
        xa = [v for k in ks for v in a_by.get(k, [])]
        xb = [v for k in ks for v in b_by.get(k, [])]
        if xa and xb:
            ds.append(statistics.mean(xa) - statistics.mean(xb))
    ds.sort()
    return (round(ds[int(0.025 * len(ds))], 3), round(ds[int(0.975 * len(ds))], 3)) if len(ds) > 100 else None


def line(rows, label):
    if not rows:
        return f"{label:<46} n=0"
    by = defaultdict(list)
    for r in rows:
        by[r["ts"]].append(r["R"])
    rs = [r["R"] for r in rows]
    tp = sum(1 for r in rows if r["out"] == "TP1")
    sl = sum(1 for r in rows if r["out"] == "SL")
    ci = cboot(by)
    return f"{label:<46} n={len(rows):<5} кл.={len(by):<4} TP1={tp:<4} SL={sl:<4} E[R]={statistics.mean(rs):+.3f}" + (f" CI[{ci[0]:+.2f};{ci[1]:+.2f}]" if ci else "")


def main(src, end, days, out="replay_context.json"):
    end_d = date.fromisoformat(end)
    btc = BV.fetch("BTCUSDT", "15m", end_d - timedelta(days=days + 8), end_d + timedelta(days=2))
    rows = [r for r in load_rows(src) if r["src"] == "BRAIN"]
    for r in rows:
        r["ctx"] = btc_ctx(btc, r["ts"])
    rows = [r for r in rows if r["ctx"]]
    L = [f"# Replay Brain v2.1 · вікно рішень {end_d - timedelta(days=days)}…{end_d} · подій з контекстом BTC: {len(rows)}"]
    P = L.append
    P(line(rows, "усі"))
    for d in ("LONG", "SHORT"):
        P(line([r for r in rows if r["dir"] == d], d))
    res = {}
    for key, lab in (("b24", "BTC 24h"), ("b4", "BTC 4h"), ("b1", "BTC 1h")):
        w = [r for r in rows if (r["ctx"][key] > 0) == (r["dir"] == "LONG")]
        a = [r for r in rows if (r["ctx"][key] > 0) != (r["dir"] == "LONG")]
        P(line(w, f"ЗА напрямом {lab}"))
        P(line(a, f"ПРОТИ напряму {lab}"))
        wb, ab = defaultdict(list), defaultdict(list)
        for r in w:
            wb[r["ts"]].append(r["R"])
        for r in a:
            ab[r["ts"]].append(r["R"])
        db = diff_boot(wb, ab)
        dm = (statistics.mean(r["R"] for r in w) - statistics.mean(r["R"] for r in a)) if w and a else None
        # стабільність у хронологічних половинах
        srt = sorted(rows, key=lambda r: r["ts"])
        half = srt[len(srt) // 2]["ts"]
        halves = []
        for part in ([r for r in rows if r["ts"] < half], [r for r in rows if r["ts"] >= half]):
            ww = [r["R"] for r in part if (r["ctx"][key] > 0) == (r["dir"] == "LONG")]
            aa = [r["R"] for r in part if (r["ctx"][key] > 0) != (r["dir"] == "LONG")]
            halves.append(round(statistics.mean(ww) - statistics.mean(aa), 3) if ww and aa else None)
        P(f"  Δ(за − проти) {lab}: {dm:+.3f} CI{db} половини={halves}" if dm is not None else f"  Δ {lab}: н/д")
        res[key] = {"delta": dm, "ci": db, "halves": halves}
    P("")
    for key, lab in (("b24", "BTC 24h"),):
        for d in ("LONG", "SHORT"):
            for tag, cond in (("за", lambda r, d=d, key=key: (r["ctx"][key] > 0) == (d == "LONG")), ("проти", lambda r, d=d, key=key: (r["ctx"][key] > 0) != (d == "LONG"))):
                P(line([r for r in rows if r["dir"] == d and cond(r)], f"{d} / {lab} {tag}"))
    P("")
    P("Режим BTC у вікні: " + ", ".join(f"{k}: {v}" for k, v in {"BTC 24h>0 подій": sum(1 for r in rows if r['ctx']['b24'] > 0), "BTC 24h<=0 подій": sum(1 for r in rows if r['ctx']['b24'] <= 0)}.items()))
    P("Сесії (V0):")
    for s in sorted({r["session"] for r in rows if r["session"]}):
        P(line([r for r in rows if r["session"] == s], "  " + str(s)))
    txt = "\n".join(L)
    print(txt)
    Path(out).write_text(json.dumps({"report": txt, "summary": res}, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else "replay_context.json")

#!/usr/bin/env python3
"""Replay дедуп-правила на таблиці READY з аудиту (psv): скільки READY було б заблоковано як дубль незавершеної ідеї.
Без lookahead: рішення по рядку N використовує лише рядки до N і їхні цифри (результат розв'язання в таблиці без часу, тому
ідея вважається незавершеною протягом 24 год — це ВЕРХНЯ межа блокування). Використання: replay_dedup_table.py <файл.psv>."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_ready_core as RC  # noqa: E402


def f(x):
    try:
        return float(x)
    except ValueError:
        return None


def run(path: str):
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        c = ln.split("|")
        mm, hh = c[0].split()
        mo, dd = mm.split("-")
        t = ((int(mo) * 31 + int(dd)) * 24 + int(hh[:2])) * 3600 + int(hh[3:]) * 60
        rows.append({"t": t, "symbol": c[2], "direction": "LONG" if c[3] == "L" else "SHORT", "entry": f(c[4]), "sl": f(c[5]), "tp1": f(c[6]),
                     "tp2": f(c[7]), "tp3": f(c[8]), "outcome": c[11]})
    rows.sort(key=lambda r: r["t"])
    kept, blocked = [], []
    open_by = defaultdict(list)
    for r in rows:
        dup = next((p for p in open_by[(r["symbol"], r["direction"])] if r["t"] - p["t"] <= 24 * 3600 and RC.same_idea(p, symbol=r["symbol"], direction=r["direction"], entry=r["entry"])), None)
        if dup:
            blocked.append((r, dup))
        else:
            kept.append(r)
            open_by[(r["symbol"], r["direction"])].append(r)
    return rows, kept, blocked


if __name__ == "__main__":
    rows, kept, blocked = run(sys.argv[1])
    print(f"READY усього {len(rows)}; унікальних ідей після правила {len(kept)}; заблоковано дублів {len(blocked)} (верхня межа)")
    for r, d in blocked[:15]:
        print(f"  блок {r['symbol']} {r['direction']} вх {r['entry']} ← уже було вх {d['entry']}")
    from collections import Counter
    print("outcome (унікальні):", dict(Counter(r["outcome"] for r in kept)))
    print("outcome (заблоковані):", dict(Counter(r["outcome"] for r, _ in blocked)))

#!/usr/bin/env python3
"""Top-down (M5/M1) на історичному replay Brain v2.1: розріз READY за статусом ltf-підтвердження і типом сценарію (continuation/reversal/range).
Рішення приймались на барах, закритих до now; M5/M1 обрізані так само (див. test_replay_ltf_nofuture). Це ЗВІТ про мітки, не зміна правил: жодного блокування.
Вхід: каталог replay-<ПЕРІОД>-<СИМВОЛ>/out_*.json, зібраних з REPLAY_LTF=1. Використання: python scripts/replay_topdown_study.py <каталог> [OUT.json]"""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay_pooled_study as P  # noqa: E402


def load(root):
    rows = []
    for d in sorted(Path(root).glob("replay-*")):
        per = d.name.split("-")[1]
        for p in d.glob("**/*.json"):
            j = json.loads(p.read_text())
            if j.get("error"):
                continue
            q = j.get("data_quality") or {}
            for r in j.get("counterfactual_rows", []):
                if r["source"] != "BRAIN":
                    continue
                v = r["variants"]["V0_current"]
                if v.get("r_net") is None or not r.get("risk_pct"):
                    continue
                cr = P.COST_PCT / float(r["risk_pct"])
                td = r.get("td") or {}
                rows.append({"per": per, "sym": r.get("symbol") or j["symbol"], "dir": r["dir"], "ts": float(r["ts_bar"]), "net": float(v["r_net"]), "gross": float(v["r_net"]) + cr,
                             "out": v.get("outcome"), "ltf": td.get("ltf") or "NO_TD", "type": td.get("type") or "NO_TD", "warn": int(td.get("conflicts_warn") or 0),
                             "td_err": td.get("error"), "ltf_data": bool(q.get("m5_bars")) and bool(q.get("m1_bars"))})
    return rows


def main(root, out="replay_topdown.json"):
    rows = load(root)
    L = []
    p = L.append
    p(f"# Top-down M5/M1 на replay Brain v2.1 · READY: {len(rows)} · витрати {P.COST_PCT}% кола · лише мітки (READY не змінюються)")
    p(f"з M5+M1 даними: {sum(1 for r in rows if r['ltf_data'])}; помилки top-down: {sum(1 for r in rows if r['td_err'])}")
    p("\n## 1. За статусом M5/M1 (форма STRUCT_BREAK_V0 — ГІПОТЕЗА)")
    for k, n in Counter(r["ltf"] for r in rows).most_common():
        sub = [r for r in rows if r["ltf"] == k]
        p(P.st(sub, "net", f"ltf={k} · net") + f"  gross={statistics.mean(r['gross'] for r in sub):+.3f}  TP1={sum(1 for r in sub if r['out'] == 'TP1')} SL={sum(1 for r in sub if r['out'] == 'SL')}")
    p("\n## 2. За типом сценарію")
    for k, n in Counter(r["type"] for r in rows).most_common():
        sub = [r for r in rows if r["type"] == k]
        p(P.st(sub, "net", f"тип={k} · net") + f"  gross={statistics.mean(r['gross'] for r in sub):+.3f}")
    p("\n## 3. Тип × ltf")
    for t in sorted({r["type"] for r in rows}):
        for k in sorted({r["ltf"] for r in rows}):
            sub = [r for r in rows if r["type"] == t and r["ltf"] == k]
            if len(sub) >= 5:
                p(P.st(sub, "net", f"{t} · ltf={k}"))
    p("\n## 4. Парне порівняння: CONFIRMED проти решти (різниця середніх net R, кластерний bootstrap), DISCOVERY / HOLDOUT / усі")
    for nm, grp in (("A–C", P.DISCOVERY), ("D–G", P.HOLDOUT), ("усі", tuple(P.WIN))):
        a = [r for r in rows if r["per"] in grp and r["ltf"] == "CONFIRMED"]
        b = [r for r in rows if r["per"] in grp and r["ltf"] != "CONFIRMED"]
        if a and b:
            p(f"{nm}: CONFIRMED n={len(a)} E[R]={statistics.mean(r['net'] for r in a):+.3f} · інші n={len(b)} E[R]={statistics.mean(r['net'] for r in b):+.3f} · Δ={statistics.mean(r['net'] for r in a) - statistics.mean(r['net'] for r in b):+.3f}")
        else:
            p(f"{nm}: недостатньо (CONFIRMED={len(a)}, інші={len(b)})")
    p("\n## 5. Скільки суперечностей ТФ (warn) мали READY і як це корелює з результатом")
    byw = defaultdict(list)
    for r in rows:
        byw[min(r["warn"], 3)].append(r)
    for k in sorted(byw):
        p(P.st(byw[k], "net", f"warn={k}{'+' if k == 3 else ''}"))
    p("\nВисновок формулювати лише за n і CI вище; відсутність різниці = top-down-мітка не доведена як фільтр (ГІПОТЕЗА).")
    txt = "\n".join(L)
    print(txt)
    Path(out).write_text(json.dumps({"n": len(rows), "report": txt}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3]))

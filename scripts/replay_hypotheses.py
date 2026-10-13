#!/usr/bin/env python3
"""Replay of the hypothesis engine on REAL Binance Futures history (data.binance.vision), closed bars only.

run:   python scripts/replay_hypotheses.py run <SYMBOL> <END YYYY-MM-DD> <DAYS> <OUT.json>
study: python scripts/replay_hypotheses.py study <DIR with replay-hyp-<PERIOD>-<SYMBOL>/*.json> [OUT.json]

At each hourly decision time hypotheses are built from bars closed before `now` (same builder as live: method_inputs +
hypothesis.build); outcomes use ONLY bars after the signal bar via hypothesis.walk. Control = the OPPOSITE direction on
the same bar with mirrored invalidation and the same R (does the hypothesis direction carry information beyond symmetry?).
Parameters (TTL 24 h, CONFIRM_R=1) are fixed in advance and are NOT tuned on these windows. SMC families are not replayed (cost).
"""
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

STRIDE = 4          # every 4th M15 close = hourly decisions
SEED = 20261013
DISCOVERY, HOLDOUT = ("A", "B", "C"), ("D", "E", "F", "G")


def run(sym, end, days, out):
    import binance_vision_fetch as BV

    end_day = date.fromisoformat(end)
    t_to = float(datetime(end_day.year, end_day.month, end_day.day, tzinfo=timezone.utc).timestamp())
    t_from = t_to - days * 86400
    arrs = BV.build_arrays(sym, end_day, days)
    if not arrs:
        Path(out).write_text(json.dumps({"symbol": sym, "error": "немає даних"}))
        return
    arrs.pop("quality", None)
    rows = core(sym, arrs, t_from, t_to)
    Path(out).write_text(json.dumps({"symbol": sym, "window": [t_from, t_to], "rows": rows}, ensure_ascii=False, default=float))
    print(sym, "hypotheses", sum(1 for r in rows if "id" in r))


def core(sym, arrs, t_from, t_to):
    import numpy as np
    from office2 import hypothesis as HY
    from office2 import features as F
    from office2.method_inputs import build_inputs
    from office2.method_context_features import msk_session
    from office2.smc import replay as RP
    from office2 import brain as B

    m15 = arrs["m15"]
    ends = m15["t"] + 900
    idx = np.flatnonzero((ends > t_from) & (ends <= t_to))
    L = RP.LIVE_LIMITS
    rows, seen = [], set()
    for n, i in enumerate(idx):
        if n % STRIDE:
            continue
        now = float(ends[i])
        c15, c4, cd = RP._cut(m15, 900, now, L["m15"]), RP._cut(arrs.get("h4"), 14400, now, L["h4"]), RP._cut(arrs.get("d1"), 86400, now, L["d1"])
        if not (c15 and c4 and cd) or len(c15["t"]) < 120:
            continue
        ctx = {"m15": c15, "h1": B.complete_h1(c15), "h4": c4, "d1": cd}
        try:
            hyps = HY.build(sym, ctx, now, build_inputs(ctx, now, None), context={"session": msk_session(now)})
        except Exception as exc:  # noqa: BLE001
            rows.append({"error": f"{type(exc).__name__}: {str(exc)[:100]}", "ts": now})
            continue
        for h in hyps:
            if h["id"] in seen or not h.get("risk_ref"):
                continue
            seen.add(h["id"])
            w = HY.walk(h["family"], h["direction"], h["created_bar_ts"], h["level"], h["invalidation"], h["ref_price"], h["risk_ref"], m15, t_to + 2 * 86400)
            opp = "SHORT" if h["direction"] == "LONG" else "LONG"
            c = HY.walk(h["family"], opp, h["created_bar_ts"], h["level"], 2 * h["ref_price"] - h["invalidation"], h["ref_price"], h["risk_ref"], m15, t_to + 2 * 86400)
            against = sum(1 for k in ("D1", "H4") if (h["tf"].get(k) or {}).get("relation") == "AGAINST")
            rows.append({"sym": sym, "id": h["id"], "family": h["family"], "dir": h["direction"], "ts": now, "stage": h["stage"], "state": w["state"], "mfe": w["mfe"], "mae": w["mae"],
                         "bars": w["bars"], "ctl_state": c["state"], "ctl_mfe": c["mfe"], "against": against, "n_support": len(h["supports"]), "n_contra": len(h["contradicts"]),
                         "session": h["context"].get("session")})
    return rows


def _rate(rs, key="state", val="CONFIRMED"):
    return sum(1 for r in rs if r[key] == val) / len(rs) if rs else None


def _ci(rows, fn, B=1000):
    """Cluster bootstrap by (period, symbol, day) of a mean statistic."""
    cl = defaultdict(list)
    for r in rows:
        cl[(r["per"], r["sym"], int(r["ts"] // 86400))].append(r)
    keys = list(cl)
    if len(keys) < 8:
        return None
    rng = random.Random(SEED)
    out = []
    for _ in range(B):
        pick = [x for k in (rng.choice(keys) for _ in keys) for x in cl[k]]
        v = fn(pick)
        if v is not None:
            out.append(v)
    out.sort()
    return (out[int(0.025 * len(out))], out[int(0.975 * len(out))]) if len(out) > B * 0.8 else None


def study(root, out="replay_hypotheses.json"):
    rows = []
    for d in sorted(Path(root).glob("replay-hyp-*")):
        per = d.name.split("-")[2]
        for p in d.glob("**/*.json"):
            j = json.loads(p.read_text())
            if j.get("error"):
                continue
            rows += [dict(r, per=per) for r in j.get("rows", []) if "id" in r]
    L = [f"# Гіпотези на replay Binance Futures · гіпотез: {len(rows)} (унікальних за id у символі/вікні) · SMC-родини не входять (вартість)"]
    p = L.append
    if not rows:
        txt = "\n".join(L + ["Немає даних."])
        print(txt)
        Path(out).write_text(json.dumps({"n": 0, "report": txt}))
        return
    p("Підтверджена = досягла 1R у своєму напрямку до закриття за інвалідацією (конвенція, ГІПОТЕЗА); R = відстань ref→інвалідація, а не ризик угоди.")
    p("Контроль = протилежний напрямок на тому ж барі з дзеркальною інвалідацією та тим самим R. Різниця >0 означає, що напрямок гіпотези несе інформацію понад симетрію.")

    def block(name, rs):
        fin = [r for r in rs if r["state"] != "ACTIVE"]
        if len(fin) < 10:
            p(f"{name:<44} n={len(rs):<4} завершених={len(fin):<4} — замало")
            return
        conf, ctl = _rate(fin), _rate(fin, "ctl_state")
        diff = lambda x: (_rate([r for r in x if r["state"] != "ACTIVE"]) or 0) - (_rate([r for r in x if r["state"] != "ACTIVE"], "ctl_state") or 0)  # noqa: E731
        ci = _ci(fin, diff)
        st = Counter(r["state"] for r in rs)
        p(f"{name:<44} n={len(rs):<4} завершених={len(fin):<4} CONFIRMED={conf:.1%} · контроль={ctl:.1%} · Δ={conf - ctl:+.1%}" + (f" CI[{ci[0]:+.1%};{ci[1]:+.1%}]" if ci else "")
          + f" · стани {dict(st)} · середній MFE {statistics.mean(r['mfe'] for r in fin):.2f}R MAE {statistics.mean(r['mae'] for r in fin):.2f}R")

    p("\n## 1. За родиною")
    for fam in sorted({r["family"] for r in rows}):
        block(fam, [r for r in rows if r["family"] == fam])
    p("\n## 2. LONG / SHORT")
    for fam in sorted({r["family"] for r in rows}):
        for d in ("LONG", "SHORT"):
            block(f"{fam} {d}", [r for r in rows if r["family"] == fam and r["dir"] == d])
    p("\n## 3. Конфлікт старших ТФ (D1/H4 проти напрямку): 0 / 1+")
    for fam in sorted({r["family"] for r in rows}):
        block(f"{fam} без конфлікту", [r for r in rows if r["family"] == fam and r["against"] == 0])
        block(f"{fam} з конфліктом", [r for r in rows if r["family"] == fam and r["against"] > 0])
    p("\n## 4. DISCOVERY (A–C) проти HOLDOUT (D–G) — параметри не підбиралися")
    for fam in sorted({r["family"] for r in rows}):
        block(f"{fam} DISCOVERY", [r for r in rows if r["family"] == fam and r["per"] in DISCOVERY])
        block(f"{fam} HOLDOUT", [r for r in rows if r["family"] == fam and r["per"] in HOLDOUT])
    p("\n## 5. Сесії (МСК-вікна джерела)")
    for s in sorted({r["session"] or "?" for r in rows}):
        block(f"сесія {s}", [r for r in rows if (r["session"] or "?") == s])
    p("\n## Обмеження")
    p("- Це якість ГІПОТЕЗ (чи справдився рух), а не прибутковість угод: немає комісій, прослизання, затримки входу та реальних ENTRY/SL/TP.")
    p("- Гіпотези з одного ринкового епізоду корельовані; CI кластерні (період, символ, доба); багато зрізів → частина «значущих» різниць випадкова.")
    p("- Не відтворено: SMC-родини, календар новин, flow (OI/funding), контекст BTC → контекст у replay неповний.")
    p("- Якщо Δ≈0 або CI містить 0 — перевага напрямку гіпотези не доведена; у production лишається SHADOW.")
    txt = "\n".join(L)
    print(txt)
    Path(out).write_text(json.dumps({"n": len(rows), "report": txt}, ensure_ascii=False))


if __name__ == "__main__":
    if sys.argv[1] == "run":
        run(sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5])
    else:
        study(sys.argv[2], *(sys.argv[3:4]))

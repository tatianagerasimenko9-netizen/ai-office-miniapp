"""Діагностика КОЖНОГО програшу B&R: напрям правильний чи ні, ранній/пізній вхід, глибина вибивання, імпульс-спайк (проксі подій).
Порівняння з виграшними за тими ж метриками. Свічки: candles/{SYM}/1m.csv. Виграш = TP1 раніше SL (як у postmortem). Описова діагностика (пороги — гіпотези, не правила джерел)."""
import glob, sys, bisect, statistics as st, csv, collections
from pathlib import Path
OFF = 1790000000; PL, CD = sys.argv[1], Path(sys.argv[2]); C = {}
def m1(sym):
    if sym not in C:
        try: b = [dict(t=int(r["open_time"]), h=float(r["high"]), l=float(r["low"]), c=float(r["close"]), o=float(r["open"])) for r in csv.DictReader(open(CD / sym / "1m.csv"))]
        except FileNotFoundError: b = None
        C[sym] = (b, [x["t"] for x in b] if b else [])
    return C[sym]
rows = []
for f in sorted(glob.glob(PL)):
    for ln in open(f):
        p = ln.rstrip("\n").split("|")
        if len(p) < 8 or not p[7]: continue
        ev = [(e.split("@")[0], int(e.split("@")[1]) + OFF) for e in p[7].split(",")]
        k = [a for a, _ in ev]
        if "E" not in k or "AMB" in k: continue
        seen = [(a, t) for a, t in ev if a != "E"]
        if not seen or seen[0][0] not in ("T1", "SL"): continue
        ent, sl = float(p[4]), float(p[5]); tp1 = float(p[6].split(",")[0].split(":")[0])
        ets = [t for a, t in ev if a == "E"][0]
        rows.append(dict(sym=p[1] + "USDT", d=1 if p[2] == "L" else -1, ts=int(p[3]), ets=ets, ent=ent, sl=sl, tp1=tp1, risk=abs(ent - sl), win=seen[0][0] == "T1", end=seen[0][1]))
def pct(a, q): a = sorted(a); return a[int(len(a) * q)] if a else float("nan")
out = []
for r in rows:
    b, t = m1(r["sym"])
    if not b: continue
    d, risk = r["d"], r["risk"]
    i0 = bisect.bisect_left(t, r["ets"]); iend = bisect.bisect_right(t, r["end"])
    # до входу: рух за напрямком за 60 хв (у ризиках) — «пізній вхід / гонитва»
    ib = bisect.bisect_left(t, r["ets"] - 3600); pre = b[ib:i0]
    ext = (d * (b[i0]["o"] - pre[0]["o"]) / risk) if pre else None
    # час до кінця угоди (хв) та MAE до кінця
    dur = (r["end"] - r["ets"]) / 60
    seg = b[i0:iend + 1]
    mae = max(((r["ent"] - x["l"]) if d == 1 else (x["h"] - r["ent"])) for x in seg) / risk if seg else None
    mfe = max(((x["h"] - r["ent"]) if d == 1 else (r["ent"] - x["l"])) for x in seg) / risk if seg else None
    # після SL (лише програші): чи дійшла ціна до TP1 за 24 год, глибина проходу за стоп, час до TP1
    after = None; depth = None
    if not r["win"]:
        j = bisect.bisect_right(t, r["end"]); k2 = bisect.bisect_right(t, r["end"] + 24 * 3600); hit = False; worst = 0.0
        for x in b[j:k2]:
            adv = ((r["sl"] - x["l"]) if d == 1 else (x["h"] - r["sl"])) / risk; worst = max(worst, adv)
            if (x["h"] >= r["tp1"]) if d == 1 else (x["l"] <= r["tp1"]): hit = True; break
        after, depth = hit, worst
    # спайк на хвилині SL: діапазон хв-свічки / медіана діапазонів 60 хв до неї
    spike = None
    if not r["win"]:
        q = bisect.bisect_left(t, r["end"]); base = [x["h"] - x["l"] for x in b[max(0, q - 60):q]]
        if base and q < len(b): spike = (b[q]["h"] - b[q]["l"]) / max(st.median(base), 1e-12)
    out.append(dict(r, ext=ext, dur=dur, mae=mae, mfe=mfe, after=after, depth=depth, spike=spike))
W = [x for x in out if x["win"]]; L = [x for x in out if not x["win"]]
print(f"угод {len(out)}: виграшних {len(W)}, програшних {len(L)}\n")
right = [x for x in L if x["after"]]; wrong = [x for x in L if x["after"] is False]
print(f"## Програші: напрям\n- ціна дійшла до TP1 за 24 год після SL: {len(right)} ({len(right)/len(L):.0%})\n- не дійшла (напрям/аналіз хибний): {len(wrong)} ({len(wrong)/len(L):.0%})\n")
if right:
    ds = [x["depth"] for x in right]
    print("## «Напрям правильний, вибило»: наскільки далеко за стоп пішла ціна перед розворотом (в ризиках R)")
    print(f"- медіана {pct(ds,.5):.2f}R, p25 {pct(ds,.25):.2f}R, p75 {pct(ds,.75):.2f}R; частка з проколом ≤0.5R за стоп: {sum(d<=.5 for d in ds)/len(ds):.0%}; ≥2R: {sum(d>=2 for d in ds)/len(ds):.0%}")
print("\n## Таймінг входу: рух за напрямком за 60 хв ДО входу (R) — «гонитва/пізній вхід»")
for nm, S in (("виграшні", W), ("програш-напрям правильний", right), ("програш-напрям хибний", wrong)):
    v = [x["ext"] for x in S if x["ext"] is not None]
    if v: print(f"- {nm}: n={len(v)}, медіана {pct(v,.5):+.2f}R, частка ≥3R (вхід після сильного руху): {sum(a>=3 for a in v)/len(v):.0%}")
print("\n## Тривалість угоди до закриття (хв) та просадка проти позиції (MAE, R)")
for nm, S in (("виграшні", W), ("програш-напрям правильний", right), ("програш-напрям хибний", wrong)):
    if S: print(f"- {nm}: тривалість медіана {pct([x['dur'] for x in S],.5):.0f} хв; частка закритих ≤15 хв: {sum(x['dur']<=15 for x in S)/len(S):.0%}; MFE до кінця медіана {pct([x['mfe'] for x in S if x['mfe'] is not None],.5):.2f}R")
sp = [x for x in L if x["spike"] is not None]
if sp:
    print(f"\n## Імпульс-спайк на хвилині SL (проксі подій/маніпуляції, НЕ підтверджені новини): діапазон хв-свічки ≥4× медіани попередніх 60 хв: {sum(x['spike']>=4 for x in sp)/len(sp):.0%} програшів (n={len(sp)}); серед «напрям правильний»: {sum(x['spike']>=4 for x in sp if x['after'])/max(1,sum(1 for x in sp if x['after'])):.0%}")
print("\n## Таблиця за символом: частка програшів «напрям правильний»")
by = collections.defaultdict(lambda: [0, 0])
for x in L:
    by[x["sym"]][0] += 1; by[x["sym"]][1] += 1 if x["after"] else 0
for s, (n, rgt) in sorted(by.items(), key=lambda kv: -kv[1][0]): print(f"- {s}: програшів {n}, з них напрям правильний {rgt} ({rgt/n:.0%})")
print("\nОБМЕЖЕННЯ: пороги (≥3R гонитва, ≥4× спайк, 24 год) — гіпотези; новини НЕ ПІДТВЕРДЖЕНО без календаря; TP1 близько → «дійшла до TP1» завищує частку 'напрям правильний' (потрібен контроль випадкових моментів).")

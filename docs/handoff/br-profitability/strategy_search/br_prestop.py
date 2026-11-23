"""READ-ONLY. B&R: «ціна не дійшла до входу, зачепила стоп, повернулась до входу і…» (23.11.2026, питання власниці).
Дані: data/br_late_entry.csv (сигнали B&R з бази, де вхід торкнуто пізніше ніж за 3 хв після картки: seq,symbol,direction,sent_ts,entry_ts,entry,sl,status,tpmax) і data/br_noentry.csv (сигнали без входу).
Хвилинні свічки Binance USDT-M (архів). Для пізніх входів: чи торкалась ціна рівня СТОПА між карткою і входом (LONG: low ≤ стоп; SHORT: high ≥ стоп) → підсумок угоди з бази (TP3 / TP1–2 і стоп / стоп / невизначено).
Для сигналів без входу: що було першим за 48 год після картки — рівень стопа чи перша ціль; і чи після стопа ціна дійшла до першої цілі.
Використання: br_prestop.py DATA_DIR CANDLES_DIR"""
import csv, io, os, sys, zipfile, urllib.request, urllib.error, datetime as dt
from concurrent.futures import ThreadPoolExecutor
D, CD = sys.argv[1], sys.argv[2]
late = list(csv.DictReader(open(f"{D}/br_late_entry.csv"))); noent = [r for r in csv.DictReader(open(f"{D}/br_noentry.csv")) if r["status"] != "DATA_GAP"]
need = set()
def days(a, b):
    d = dt.datetime.utcfromtimestamp(a).date(); e = dt.datetime.utcfromtimestamp(b).date()
    while d <= e: yield d; d += dt.timedelta(days=1)
for r in late:
    for d in days(int(r["sent_ts"]), int(r["entry_ts"])): need.add((r["symbol"], d))
for r in noent:
    for d in days(int(r["sent_ts"]), int(r["sent_ts"]) + 48 * 3600): need.add((r["symbol"], d))
def get(j):
    s, d = j; url = f"https://data.binance.vision/data/futures/um/daily/klines/{s}/1m/{s}-1m-{d}.zip"
    for a in range(4):
        try:
            raw = urllib.request.urlopen(url, timeout=60).read(); break
        except urllib.error.HTTPError as e:
            if e.code == 404: return j, None
        except Exception: pass
    else: return j, None
    rows = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        for ln in z.read(z.namelist()[0]).decode().splitlines():
            p = ln.split(",")
            if p[0].isdigit(): t = int(p[0]); rows.append((t // 1000 if t > 10**11 else t, float(p[2]), float(p[3])))
    return j, rows
M = {}
with ThreadPoolExecutor(16) as ex:
    for j, rows in ex.map(get, sorted(need)): M[j] = rows
def bars(sym, a, b):
    out = []; ok = True
    for d in days(a, b):
        rows = M.get((sym, d))
        if rows is None: ok = False; continue
        out += [x for x in rows if a < x[0] + 60 and x[0] <= b]
    return sorted(out), ok
print(f"B&R: стоп до входу. Пізніх входів (вхід пізніше ніж за 3 хв після картки): {len(late)}; сигналів без входу (без DATA_GAP): {len(noent)}; денних файлів: {len(need)}, недоступно: {sum(1 for v in M.values() if v is None)}")
def cls(r): return "ціль 3" if r["status"] == "TP3" else ("ціль 1–2, потім стоп" if r["status"] == "SL" and r["tpmax"] in ("1", "2") else ("стоп" if r["status"] == "SL" else "невизначено/інше"))
G = {"так": {}, "ні": {}}; skipped = 0; waits = {"так": [], "ні": []}
for r in late:
    a, b = int(r["sent_ts"]), int(r["entry_ts"]); bs, ok = bars(r["symbol"], a, b - 60)
    if not ok: skipped += 1; continue
    sl = float(r["sl"]); long = r["direction"] == "LONG"
    hit = any((lo <= sl) if long else (hi >= sl) for _, hi, lo in bs)
    k = "так" if hit else "ні"; G[k][cls(r)] = G[k].get(cls(r), 0) + 1; waits[k].append((b - a) / 60)
print(f"(пропущено через брак свічок: {skipped})")
for k in ("так", "ні"):
    n = sum(G[k].values())
    if not n: continue
    w = sorted(waits[k])[len(waits[k]) // 2]
    print(f"\n== Перед входом ціна торкалась рівня стопа: {k.upper()} — {n} угод (медіана очікування входу {w:.0f} хв)")
    for c in ("ціль 3", "ціль 1–2, потім стоп", "стоп", "невизначено/інше"): print(f"   {c:22s}: {G[k].get(c, 0):4d} ({100 * G[k].get(c, 0) / n:.0f}%)")
print("\n== Сигнали БЕЗ входу за 48 год: що було першим після картки")
res = {}
for r in noent:
    a = int(r["sent_ts"]); bs, ok = bars(r["symbol"], a, a + 48 * 3600)
    if not bs: res["немає даних"] = res.get("немає даних", 0) + 1; continue
    sl, tp, e = float(r["sl"]), float(r["tp1"]), float(r["entry"]); long = r["direction"] == "LONG"; first = None; later_tp = False; side0 = None
    for t, hi, lo in bs:
        s_hit = (lo <= sl) if long else (hi >= sl); t_hit = (hi >= tp) if long else (lo <= tp)
        if first is None:
            if s_hit and t_hit: first = "обидва в одній хвилині"
            elif s_hit: first = "стоп"
            elif t_hit: first = "ціль"
        elif first == "стоп" and t_hit: later_tp = True
    p0 = (bs[0][1] + bs[0][2]) / 2; pos = "ціна на момент картки була на «гіршому» боці від входу (LONG: нижче входу)" if ((p0 < e) if long else (p0 > e)) else "ціна на момент картки була на «кращому» боці (LONG: вище входу)"
    key = (first or "нічого за 48 год") + (" → потім дійшла до цілі 1" if later_tp else "")
    res[key] = res.get(key, 0) + 1; res["__" + pos] = res.get("__" + pos, 0) + 1
for k, v in sorted(res.items(), key=lambda x: -x[1]): print(f"   {k.replace('__', '')}: {v}")

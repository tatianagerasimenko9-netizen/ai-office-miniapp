"""Розбір експорту бота-еталона (лише читання): сигнали + події бота → підсумок кожного сигналу в R ($10 ризику), комісія 0,10% від суми позиції.
Моделі виходу: M1 усе на TP1; M2 50% на TP1, решта до TP2 або беззбитку; M3 50% TP1, 25% TP2, 25% TP3 (залишок після останньої цілі — беззбиток або остання досягнута ціль за даними бота)."""
import json, sys, re, csv
from datetime import datetime
M = json.load(open(sys.argv[1], encoding="utf-8"))["messages"]
def txt(m):
    t = m.get("text"); return t if isinstance(t, str) else "".join(x if isinstance(x, str) else x.get("text", "") for x in t)
num = lambda s: float(s.replace(",", "."))
sigs = []; open_by = {}
for m in M:
    t = txt(m); ts = datetime.fromisoformat(m["date"]).timestamp()
    if "Сигнал бота" in t:
        h = re.search(r"(LONG|SHORT) · (\w+USDT) · (\w+) · #(\d+)", t); e = re.search(r"Вхід:\s+([\d.]+)", t); sl = re.search(r"SL:\s+([\d.]+) \(([\d.]+)%\)", t)
        tp = re.findall(r"TP(\d):\s+([\d.]+)", t)
        we = re.search(r"Вхід:\s+[\d.]+ \((\d+)%\)", t); ad = re.search(r"Добір:\s+([\d.]+) \((\d+)%\)", t)
        if not (h and e and sl and tp): continue
        hd = re.search(r"Сигнал бота · (\S+) · (\S+)", t); sc = re.search(r"(\d+)/20", t); ai = re.search(r"AI: (\w+) \((\d+)/100\)", t)
        ses = re.search(r"\d\d:\d\d \d\d\.\d\d\.\d{4} · (?:\S+ )?([А-ЯІЇЄA-Z\-]+(?: [а-яіїє]+)?) · (\w+)", t); rsi = re.search(r"RSI (\d+) · ADX (\d+) · ATR ([\d.]+)%", t)
        s = dict(ts=ts, date=m["date"], dir=h.group(1), sym=h.group(2), tf=h.group(3), id=int(h.group(4)), tier=hd.group(1) if hd else "?", kind=hd.group(2) if hd else "?", score=int(sc.group(1)) if sc else -1,
                 entry=num(e.group(1)), sl=num(sl.group(1)), slp=num(sl.group(2)), tp={int(k): num(v) for k, v in tp}, ai=ai.group(1) if ai else "-", ai_s=int(ai.group(2)) if ai else -1,
                 ses=ses.group(1) if ses else "?", regime=ses.group(2) if ses else "?", rsi=int(rsi.group(1)) if rsi else -1, adx=int(rsi.group(2)) if rsi else -1, atr=num(rsi.group(3)) if rsi else -1,
                 we=(int(we.group(1)) if we else 100) / 100, addp=num(ad.group(1)) if ad else None, wa=(int(ad.group(2)) if ad else 0) / 100, kz=int("Kill Zone — чиста" in t), against=int("тренд проти" in t), ev=[])
        sigs.append(s); open_by[(s["sym"], s["id"])] = s; continue
    for key, name in (("🟡 ВХІД", "IN"), ("🟠 Добір", "ADD"), ("✅ 🔵 TP1", "TP1"), ("✅ 🟣 TP2", "TP2"), ("TP3", "TP3"), ("🔴 SL", "SL"), ("⚪️ BE", "BE")):
        if t.startswith(key) or (name == "TP3" and t.startswith("✅") and "TP3" in t[:12]):
            h = re.search(r"(\w+USDT) · #(\d+)", t)
            if h and (h.group(1), int(h.group(2))) in open_by:
                s = open_by[(h.group(1), int(h.group(2)))]
                if ts - s["ts"] < 30 * 86400: s["ev"].append((name, ts))
            break
rows = []
for s in sigs:
    ev = [n for n, _ in s["ev"]]; risk = abs(s["entry"] - s["sl"]); rr = {k: abs(v - s["entry"]) / risk for k, v in s["tp"].items()} if risk > 0 else {}
    fee = 0.10 / s["slp"] if s["slp"] > 0 else 0.0; st = "NOENTRY" if "IN" not in ev else None; m1 = m2 = m3 = None
    if st is None:
        t1, t2, t3, slh, be = ("TP1" in ev), ("TP2" in ev), ("TP3" in ev), ("SL" in ev), ("BE" in ev)
        if not t1 and slh: st = "SL"; m1 = m2 = m3 = -1.0
        elif t1:
            st = "TP3" if t3 else ("TP2" if t2 else "TP1"); r1, r2, r3 = rr.get(1, 0), rr.get(2, 0), rr.get(3, 0)
            closed = t3 or be or slh                                              # залишок закрито?
            m1 = r1
            m2 = 0.5 * r1 + 0.5 * (r2 if t2 else 0.0)
            m3 = 0.5 * r1 + 0.25 * (r2 if t2 else 0.0) + 0.25 * (r3 if t3 else 0.0)
            if not closed and not t2: st += "+OPEN"
        elif be: st = "BE"; m1 = m2 = m3 = 0.0
        else: st = "OPEN"
    # модель «за розміром»: $10 — втрата всього плану (вхід + добір) на стопі; якщо добір не спрацював, у грі лише частина входу. Комісія 0,10% від реально відкритої суми.
    z = None
    if m1 is not None and risk > 0:
        side = 1 if s["dir"] == "LONG" else -1; e = s["entry"]; a_ = s["addp"] or e; we, wa = s["we"], (s["wa"] if s["addp"] else 0.0)
        full = we * abs(e - s["sl"]) + wa * abs(a_ - s["sl"]); pos = [(we, e)] + ([(wa, a_)] if "ADD" in ev and wa else []); W = sum(w for w, _ in pos)
        pnl = lambda px, share: share * sum(w * side * (px - p) for w, p in pos) / full
        if st == "SL": z = pnl(s["sl"], 1.0)
        elif st == "BE": z = 0.0
        else: z = pnl(s["tp"][1], 0.5) + (pnl(s["tp"][2], 0.25) if "TP2" in ev and 2 in s["tp"] else 0.0) + (pnl(s["tp"][3], 0.25) if "TP3" in ev and 3 in s["tp"] else 0.0)
        z -= 0.001 * sum(w * p for w, p in pos) / full
    dur = (max(t for _, t in s["ev"]) - s["ts"]) / 3600 if s["ev"] else 0
    rows.append(dict(date=s["date"], sym=s["sym"], dir=s["dir"], tf=s["tf"], id=s["id"], tier=s["tier"], kind=s["kind"], score=s["score"], ai=s["ai"], ai_s=s["ai_s"], ses=s["ses"], regime=s["regime"], rsi=s["rsi"], adx=s["adx"], atr=s["atr"],
                     kz=s["kz"], against=s["against"], slp=s["slp"], rr1=round(rr.get(1, 0), 2), status=st, add=int("ADD" in ev), fee=round(fee, 3),
                     m1=None if m1 is None else round(m1 - fee, 3), m2=None if m2 is None else round(m2 - fee, 3), m3=None if m3 is None else round(m3 - fee, 3), dur_h=round(dur, 1), z=None if z is None else round(z, 3)))
w = csv.DictWriter(open(sys.argv[2], "w", newline=""), fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows); print("signals", len(rows))

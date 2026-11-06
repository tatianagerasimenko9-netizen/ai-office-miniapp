#!/usr/bin/env python3
"""VVV і SYRUP: що існувало ДО READY і до стопа (лише свічки; OI/funding/L/S для монети тут недоступні). Без look-ahead: у кожен момент — лише закриті свічки до нього.
Показує: рух монети й BTC за 15/30/60 хв, виноси ліквідності й втрачені рівні, стани Market Brain для BTC у ті ж хвилини."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import market_study_ready as S  # noqa: E402
import office_brain_features as bf  # noqa: E402
import office_market_brain as mb  # noqa: E402
import office_time_structure as ts  # noqa: E402

CASES = [("VVVUSDT", 1791132285.6, 27.984, 28.351187744, "SHORT"), ("SYRUPUSDT", 1791127685.6, 0.25779, 0.260378225, "SHORT")]
NOW = 1791140000.0


def hhmm(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%H:%M")


def pct(a, b):
    return None if not a or not b else round((a / b - 1) * 100, 2)


def load(sym, t0):
    out = {}
    for tf, back in (("1m", 9 * 3600), ("5m", 3 * 86400), ("15m", 5 * 86400), ("1d", 60 * 86400)):
        rows, src = S.any_src(sym, tf, t0 - back)
        out[tf] = (rows, src)
    return out


def px_at(rows1, t):
    return S.px_at(rows1, t)


btc = load("BTCUSDT", CASES[1][1])
for sym, T, entry, sl, side in CASES:
    d = load(sym, T)
    print(f"\n==================== {sym} {side} READY {hhmm(T)} UTC; вхід {entry}, стоп {sl} | джерела: {d['1m'][1]}/{d['15m'][1]}")
    r1 = d["1m"][0]
    # перший дотик стопа після READY
    sl_t = next((r["t"] for r in r1 if r["t"] >= T and r["high"] >= sl), None)
    en_t = next((r["t"] for r in r1 if r["t"] >= T and r["high"] >= entry * 0.9999 and r["low"] <= entry * 1.0001), None)
    print(f"вхід торкнуто ~{hhmm(en_t) if en_t else '—'}; стоп торкнуто ~{hhmm(sl_t) if sl_t else '—'}")
    marks = [T - 3600, T - 1800, T - 900, T] + ([sl_t - 900] if sl_t else []) + ([sl_t] if sl_t else [])
    for t in marks:
        c1 = [{"ts": r["ts"], "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"]} for r in r1]
        c5 = [r for r in d["5m"][0]]
        c15 = [r for r in d["15m"][0]]
        dd = [r for r in d["1d"][0]]
        closed = bf.upto(dd, t, 86400.0)
        pxc = px_at(r1, t)
        snap = ts.snapshot(t, pxc, closed) if closed and pxc else {}
        f = bf.compute(t, c1=[], c5=c5, c15=c15, daily=dd, week=snap.get("week"), month=snap.get("month"))
        pb = px_at(btc["1m"][0], t)
        row = {"coin": [pct(pxc, px_at(r1, t - m * 60)) for m in (15, 30, 60)], "btc": [pct(pb, px_at(btc["1m"][0], t - m * 60)) for m in (15, 30, 60)]}
        ev = mb.evidence(f) if f.get("ok") else {"LONG": [], "SHORT": []}
        tag = "READY" if t == T else ("стоп" if sl_t and t == sl_t else f"READY{int((t - T) / 60):+d}хв" if t < T else f"стоп{int((t - sl_t) / 60):+d}хв")
        print(f"\n[{hhmm(t)} {tag}] ціна {pxc}; зміна 15/30/60 хв: монета {row['coin']} | BTC {row['btc']}")
        if f.get("ok"):
            print(f"   ATR15 {f.get('atr15_pct')}%; виніс угору: {f['sweep_up'] and (f['sweep_up']['kind'], f['sweep_up']['level'], f['sweep_up']['extreme'])}; виніс униз: {f['sweep_down'] and (f['sweep_down']['kind'], f['sweep_down']['level'])}")
        for k in ("SHORT", "LONG"):
            for e in ev[k]:
                print(f"   доказ {k}: {e['text']}")
    # стани Market Brain для BTC (лише свічки) кожні 5 хв від T-3год до стопа
    print("\n  -- Market Brain (BTC, лише свічки) переходи станів у цьому вікні --")
    mem = mb.new_memory()
    t = T - 3 * 3600
    end = (sl_t or T) + 600
    cb5, cb15, cbd = btc["5m"][0], btc["15m"][0], btc["1d"][0]
    while t <= end:
        closed = bf.upto(cbd, t, 86400.0)
        snap = ts.snapshot(t, px_at(btc["1m"][0], t), closed) if closed else {}
        fb = bf.compute(t, c1=[], c5=cb5, c15=cb15, daily=cbd, week=snap.get("week"), month=snap.get("month"))
        mem, tr = mb.step(mem, fb, t)
        if tr:
            print(f"   {hhmm(t)} {mb.name(tr['from']['state'], tr['from']['side'])} -> {mb.name(tr['to']['state'], tr['to']['side'])} | {tr['reasons'][:2]}")
        t += 300
    print(f"   підсумок у кінці вікна: {mb.name(mem['state'], mem['side'])}")

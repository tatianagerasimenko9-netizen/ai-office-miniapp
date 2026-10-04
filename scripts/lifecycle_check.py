#!/usr/bin/env python3
"""Фактичний стан виданих READY за ринковими свічками 5m (Gate/OKX, лише читання): WAITING_ENTRY / ACTIVE / TP1 / TP2 / TP3 / SL / EXPIRED.
Послідовність без lookahead: вхід можливий лише ПІСЛЯ часу READY (свічки, що відкриваються ≥ T); SL до входу — не SL угоди (клас NOT_ENTERED_SL_TOUCH).
Intrabar high/low; у свічці, що торкнулась і SL, і цілі, — спершу SL. Також друкує «перше торкання SL після T без вимоги входу» для діагностики."""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

PLANS = json.loads(open(sys.argv[1]).read()) if len(sys.argv) > 1 else []
NOW = time.time()


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "office-lifecycle-check"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def gate(sym, t0):
    base = sym[:-4]
    out = []
    d = get(f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={base}_USDT&interval=5m&from={int(t0)}&to={int(NOW)}")
    for c in d:
        out.append((float(c["t"]), float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])))
    return out


def okx(sym, t0):
    base = sym[:-4]
    d = get(f"https://www.okx.com/api/v5/market/candles?instId={base}-USDT-SWAP&bar=5m&limit=300")
    out = [(float(r[0]) / 1000.0, float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in d.get("data", [])]
    return sorted(x for x in out if x[0] >= t0)


def candles(sym, t0):
    for fn in (gate, okx):
        try:
            c = sorted(fn(sym, t0 - 1800))
            if c:
                return c, fn.__name__
        except Exception as e:  # noqa: BLE001
            last = f"{fn.__name__}: {type(e).__name__}"
    return [], last if 'last' in dir() else "немає"


def hhmm(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m %H:%M")


def classify(p, c5):
    long_ = p["dir"] != "SHORT"
    e, sl = p["entry"], p["sl"]
    tps = [(n, p[k]) for n, k in (("TP1", "tp1"), ("TP2", "tp2"), ("TP3", "tp3")) if p.get(k) is not None]
    t0 = p["t"]
    state, t_fill, t_ev, reached, sl_touch_any = "WAITING_ENTRY", None, None, [], None
    for ts, o, h, l, c in c5:
        if ts < t0:
            continue
        stop_hit = (l <= sl) if long_ else (h >= sl)
        if sl_touch_any is None and stop_hit:
            sl_touch_any = ts
        if t_fill is None:
            if ts > p["valid"]:
                state = "EXPIRED"
                break
            if l <= e <= h:
                t_fill, state = ts, "ACTIVE"
                if stop_hit:
                    state, t_ev = "SL", ts
                    break
            continue
        if stop_hit:
            state, t_ev = ("SL" if not reached else f"{reached[-1]}_THEN_SL"), ts
            break
        for n, lv in tps:
            if n not in reached and ((h >= lv) if long_ else (l <= lv)):
                reached.append(n)
                t_ev = ts
        if reached:
            state = reached[-1]
            if tps[-1][0] in reached:
                break
    if t_fill is None and sl_touch_any is not None and state == "WAITING_ENTRY":
        state = "WAITING_ENTRY(+SL торкнуто до входу)"
    return state, t_fill, t_ev, reached, sl_touch_any


def main():
    print("symbol | dir | READY (UTC) | entry | SL | TP1 | джерело | стан | вхід | подія | перше торкання SL після T | остання ціна | max/min після T")
    for p in PLANS:
        c5, src = candles(p["sym"], p["t"])
        if not c5:
            print(f"{p['sym']} | {p['dir']} | {hhmm(p['t'])} | {p['entry']} | {p['sl']} | {p['tp1']} | {src} | НЕМАЄ ДАНИХ")
            continue
        st, tf, te, rc, slt = classify(p, c5)
        after = [x for x in c5 if x[0] >= p["t"]]
        hi = max(x[2] for x in after) if after else None
        lo = min(x[3] for x in after) if after else None
        print(f"{p['sym']} | {p['dir']} | {hhmm(p['t'])} | {p['entry']} | {p['sl']} | {p['tp1']} | {src} | {st} | {hhmm(tf) if tf else '-'} | {hhmm(te) if te else '-'} | "
              f"{hhmm(slt) if slt else '-'} | {c5[-1][4]} (свічка {hhmm(c5[-1][0])}) | max {hi} / min {lo}")


if __name__ == "__main__":
    main()

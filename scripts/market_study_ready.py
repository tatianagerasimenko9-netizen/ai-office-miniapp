#!/usr/bin/env python3
"""Ринок на момент конкретних READY (лише читання публічних даних): BTC/ETH/кошик великих монет, Weekly/Monthly структура, монета проти BTC.
Використовує ті самі модулі, що й Office (office_time_structure, office_market_bias). Джерела: Binance spot (дзеркало), OKX/Gate swap для монет без споту.
Вхід: JSON-список [{"symbol","direction","t"(unix),"entry","sl","tp1",...}]. Вихід: JSON + читабельний текст у stdout."""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_market_bias as mb  # noqa: E402
import office_time_structure as tstruct  # noqa: E402

PLANS = json.loads(Path(sys.argv[1]).read_text()) if len(sys.argv) > 1 else []


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "office-market-study"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def spot(sym, interval, start=None, limit=1000):
    q = f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}" + (f"&startTime={int(start * 1000)}" if start else "")
    rows = get(q)
    return [{"ts": iso(r[0] / 1000.0), "t": r[0] / 1000.0, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in rows]


def okx(sym, bar, limit=300):
    base = sym[:-4]
    d = get(f"https://www.okx.com/api/v5/market/candles?instId={base}-USDT-SWAP&bar={bar}&limit={limit}").get("data", [])
    rows = [{"t": float(r[0]) / 1000.0, "ts": iso(float(r[0]) / 1000.0), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in d]
    return sorted(rows, key=lambda x: x["t"])


def gate(sym, interval, t0):
    base = sym[:-4]
    d = get(f"https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract={base}_USDT&interval={interval}&from={int(t0)}&to={int(time.time())}")
    return [{"t": float(c["t"]), "ts": iso(float(c["t"])), "open": float(c["o"]), "high": float(c["h"]), "low": float(c["l"]), "close": float(c["c"])} for c in d]


def any_src(sym, interval, t0):
    """(rows, source) — перше джерело, що віддало дані."""
    errs = []
    for name, fn in (("binance_spot", lambda: spot(sym, interval, t0)), ("gate_swap", lambda: gate(sym, interval, t0)),
                     ("okx_swap", lambda: okx(sym, interval))):
        try:
            rows = fn()
            if rows:
                return rows, name
        except Exception as e:  # noqa: BLE001
            errs.append(f"{name}:{type(e).__name__}")
    return [], "none:" + ",".join(errs)


def px_at(rows, t):
    """Ціна закриття 1m-свічки, що містить t."""
    best = None
    for r in rows:
        if r["t"] <= t < r["t"] + 60:
            best = r
    if best is None:
        prior = [r for r in rows if r["t"] <= t]
        best = prior[-1] if prior else None
    return best["close"] if best else None


def hourly_series(rows1m, t, n=6):
    """Закриття на T, T-1год, T-2год…: ряд для ret_pct (bars=1 → 1 год, bars=4 → 4 год)."""
    out = []
    for k in range(n, -1, -1):
        p = px_at(rows1m, t - k * 3600)
        if p is not None:
            out.append({"close": p, "open": p, "high": p, "low": p, "ts": iso(t - k * 3600)})
    return out


def pct(a, b):
    return None if a is None or b is None or not b else round((a / b - 1.0) * 100.0, 3)


def main():
    result = {"generated": iso(time.time()), "plans": []}
    t_min = min([p["t"] for p in PLANS] or [time.time()]) - 5 * 3600
    cache = {}

    def m1(sym):
        if sym not in cache:
            cache[sym] = any_src(sym, "1m", t_min)
        return cache[sym]

    c15cache = {}

    def cache15(sym, t):
        if sym not in c15cache:
            c15cache[sym] = any_src(sym, "15m", t_min - 22 * 3600)
        return c15cache[sym]

    btc, ethr = m1("BTCUSDT"), m1("ETHUSDT")
    bsk = {s: m1(s + "USDT") for s in mb.BASKET if s != "ETH"}
    dly_btc, _ = any_src("BTCUSDT", "1d", time.time() - 110 * 86400)
    dly_eth, _ = any_src("ETHUSDT", "1d", time.time() - 110 * 86400)
    hr_btc, _ = any_src("BTCUSDT", "1h", time.time() - 8 * 86400)
    for p in PLANS:
        t, sym = p["t"], p["symbol"]
        coin_rows, coin_src = m1(sym)
        rows_b, rows_e = btc[0], ethr[0]
        bs = hourly_series(rows_b, t)
        es = hourly_series(rows_e, t)
        basket = {s: hourly_series(r[0], t) for s, r in bsk.items() if r[0]}
        basket["ETH"] = es
        pb = px_at(rows_b, t)
        ts_btc = tstruct.snapshot(t, pb, [c for c in dly_btc if c["t"] <= t + 86400], hourly=[c for c in hr_btc if c["t"] <= t])
        market = mb.assess(btc_1h=bs, eth_1h=es, basket_1h=basket, btc_week_dist_pct=ts_btc["week"]["dist_open_pct"])
        cs = hourly_series(coin_rows, t)
        c15, _s15 = any_src(sym, "15m", t - 26 * 3600)
        b15, _sb15 = cache15("BTCUSDT", t)
        corr = mb.corr([r for r in c15 if r["t"] <= t][-48:], [r for r in b15 if r["t"] <= t][-48:], n=47) if c15 and b15 else None
        al = mb.alignment(market, direction=p["direction"], coin=sym[:-4], coin_1h=cs, btc_1h=bs, corr_btc=corr)
        dly_coin, dsrc = any_src(sym, "1d", time.time() - 110 * 86400)
        ts_coin = tstruct.snapshot(t, px_at(coin_rows, t), [c for c in dly_coin if c["t"] <= t + 86400])
        pc = px_at(coin_rows, t)
        result["plans"].append({
            "symbol": sym, "direction": p["direction"], "t": t, "at_utc": iso(t), "coin_src": coin_src, "price_at_t": pc, "entry": p.get("entry"),
            "btc": {"price": pb, "r15m": pct(pb, px_at(rows_b, t - 900)), "r1h": pct(pb, px_at(rows_b, t - 3600)), "r4h": pct(pb, px_at(rows_b, t - 14400)),
                    "week_open": ts_btc["week"]["open"], "week_dist": ts_btc["week"]["dist_open_pct"], "week_high": ts_btc["week"]["high"], "week_low": ts_btc["week"]["low"],
                    "month_open": ts_btc["month"]["open"], "month_dist": ts_btc["month"]["dist_open_pct"], "month_high": ts_btc["month"]["high"], "month_low": ts_btc["month"]["low"],
                    "prev_week": ts_btc["week"]["prev"], "phase": [ts_btc["week"]["phase"], ts_btc["month"]["phase"], ts_btc["quarter"]["phase"]],
                    "week_close_in": ts_btc["week"]["close_in"], "month_close_in": ts_btc["month"]["close_in"], "accept": ts_btc["week"].get("accept")},
            "eth": {"price": px_at(rows_e, t), "r15m": pct(px_at(rows_e, t), px_at(rows_e, t - 900)), "r1h": pct(px_at(rows_e, t), px_at(rows_e, t - 3600)),
                    "r4h": pct(px_at(rows_e, t), px_at(rows_e, t - 14400)), "week_dist": tstruct.snapshot(t, px_at(rows_e, t), [c for c in dly_eth if c["t"] <= t + 86400])["week"]["dist_open_pct"]},
            "coin": {"r15m": pct(pc, px_at(coin_rows, t - 900)), "r1h": pct(pc, px_at(coin_rows, t - 3600)), "r4h": pct(pc, px_at(coin_rows, t - 14400)),
                     "week_dist": ts_coin["week"]["dist_open_pct"], "month_dist": ts_coin["month"]["dist_open_pct"], "daily_src": dsrc},
            "market": {k: market[k] for k in ("bias", "long", "short", "checked", "facts", "breadth")},
            "alignment": al, "sessions": ts_btc["sessions"], "weekday": ts_btc["weekday"]})
    import office_ready_core as rc  # noqa: E402
    import office_user_messages as um  # noqa: E402

    for pl, src in zip(result["plans"], PLANS):
        if not src.get("sl"):
            continue
        gate = rc.gate_snapshot(direction=src["direction"], entry=src["entry"], sl=src["sl"], tp1=src["tp1"], tp2=src.get("tp2"), tp3=src.get("tp3"),
                                confirm={"mode": "inside_zone", "tags": src.get("tags") or [], "detail": "", "price": src["entry"]})
        story = rc.story_for(symbol=src["symbol"], direction=src["direction"], confirm=gate["confirm"], gate=gate, entry=src["entry"],
                             zone_lo=src.get("zone_lo"), zone_hi=src.get("zone_hi"), tf="H1")
        m = pl["market"]
        mk = {"bias": m["bias"], "long": m["long"], "short": m["short"], "checked": m["checked"]}
        lines = mb.signal_lines(mk, pl["alignment"])
        cal = tstruct.lines({"week": {"close_in": pl["btc"]["week_close_in"], "dist_open_pct": pl["btc"]["week_dist"], "open": pl["btc"]["week_open"], "hours_to_close": 6},
                             "month": {"close_in": pl["btc"]["month_close_in"], "dist_open_pct": pl["btc"]["month_dist"], "open": pl["btc"]["month_open"], "hours_to_close": 999}}, "BTC")
        pl["card"] = um.ready_signal(symbol=src["symbol"], direction=src["direction"], entry=src["entry"], sl=src["sl"], tp1=src["tp1"], tp2=src.get("tp2"), tp3=src.get("tp3"),
                                     max_entry=src.get("max_entry"), setup=str(story.get("name") or ""), why=story.get("why") or [], market=lines + cal,
                                     valid_until=rc.kyiv_stamp(src["t"] + 86400))
    print(json.dumps(result, ensure_ascii=False, indent=1))
    for pl in result["plans"]:
        if pl.get("card"):
            print("\n==== CARD", pl["symbol"], "====\n" + pl["card"])


if __name__ == "__main__":
    main()

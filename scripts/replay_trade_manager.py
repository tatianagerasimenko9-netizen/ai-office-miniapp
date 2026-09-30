#!/usr/bin/env python3
"""Replay ведення угоди на реальних свічках (без підглядання в майбутнє): крок 15 хв, `advise`/`reentry` бачать лише закриті свічки до поточного кроку.
Джерела: --source prod (свічки з Mini App /api/v2/candles, ≤500 барів на ТФ) або --source vision (Binance Vision daily zip, лише завершені доби).
Вхід моделюється на першій свічці після --start, що торкнулась --entry; далі друкується хронологія порад і підсумок (MFE/MAE у %, R).
Приклад: python3 scripts/replay_trade_manager.py --symbol AKEUSDT --side LONG --entry 0.030259 --sl 0.029568 --tp1 0.031621 --tp2 0.032086 --start 2026-09-30T00:00:00Z"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
import office_trade_manager as TM  # noqa: E402

TF = {"15m": 900, "1h": 3600, "4h": 14400}


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def from_prod(base, symbol):
    out = {}
    for tf, key in (("15m", "M15"), ("1h", "H1"), ("4h", "H4")):
        raw = json.load(urllib.request.urlopen(urllib.request.Request(f"{base}/api/v2/candles?symbol={symbol}&tf={key}&limit=500", headers={"User-Agent": "replay/1"}), timeout=60))
        out[tf] = [{"ts": c["ts"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"], "volume": c.get("volume")} for c in raw.get("candles", [])]
    return out


def from_vision(symbol, start, end):
    rows = []
    d = start.date()
    while d <= end.date():
        url = f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/15m/{symbol}-15m-{d.isoformat()}.zip"
        try:
            z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url, timeout=60).read()))
            for line in z.read(z.namelist()[0]).decode().splitlines():
                p = line.split(",")
                if p[0].isdigit():
                    rows.append({"ts": iso(int(p[0]) / 1000), "open": float(p[1]), "high": float(p[2]), "low": float(p[3]), "close": float(p[4]), "volume": float(p[5])})
        except Exception as exc:  # noqa: BLE001
            print(f"[vision] {d}: {type(exc).__name__}")
        d += timedelta(days=1)
    return rows


def resample(m15, sec):
    buckets = {}
    for r in m15:
        t = datetime.fromisoformat(r["ts"]).timestamp()
        b = int(t // sec * sec)
        x = buckets.setdefault(b, {"ts": iso(b), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": 0.0})
        x["high"] = max(x["high"], r["high"]); x["low"] = min(x["low"], r["low"]); x["close"] = r["close"]; x["volume"] += r.get("volume") or 0.0
    return [buckets[k] for k in sorted(buckets)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True); ap.add_argument("--side", required=True)
    ap.add_argument("--entry", type=float, required=True); ap.add_argument("--sl", type=float, required=True)
    ap.add_argument("--tp1", type=float, required=True); ap.add_argument("--tp2", type=float)
    ap.add_argument("--start", required=True); ap.add_argument("--end")
    ap.add_argument("--source", default="prod"); ap.add_argument("--base", default="https://ai-office-miniapp.onrender.com")
    a = ap.parse_args()
    start = datetime.fromisoformat(a.start.replace("Z", "+00:00"))
    end = datetime.fromisoformat(a.end.replace("Z", "+00:00")) if a.end else datetime.now(timezone.utc)
    if a.source == "prod":
        data = from_prod(a.base, a.symbol)
    else:
        m15 = from_vision(a.symbol, start - timedelta(days=3), end)
        data = {"15m": m15, "1h": resample(m15, 3600), "4h": resample(m15, 14400)}
    m15 = data["15m"]
    if not m15:
        print("НЕМАЄ ДАНИХ — replay не виконано"); return 2
    long_ = a.side.upper() != "SHORT"
    fill_t = None
    for r in m15:
        t = datetime.fromisoformat(r["ts"]).timestamp()
        if t >= start.timestamp() and r["low"] <= a.entry <= r["high"]:
            fill_t = t + 900
            break
    if fill_t is None:
        print(f"Ціна не торкнулась входу {a.entry} після {a.start} — угоду не відкрито (NOT_FILLED)"); return 0
    pos = {"symbol": a.symbol, "direction": a.side.upper(), "entry": a.entry, "sl": a.sl, "tp1": a.tp1, "tp2": a.tp2, "opened_at": iso(fill_t)}
    sent, stop_ts, timeline = {}, None, []
    mfe = mae = 0.0
    t = fill_t
    last_t = datetime.fromisoformat(m15[-1]["ts"]).timestamp() + 900
    while t <= last_t:
        cut = lambda rows, sec: [r for r in rows if datetime.fromisoformat(r["ts"]).timestamp() + sec <= t]  # noqa: E731
        m, h1, h4 = cut(m15, 900), cut(data["1h"], 3600), cut(data["4h"], 14400)
        if not m:
            t += 900; continue
        px = float(m[-1]["close"])
        for r in m[-1:]:
            mfe = max(mfe, ((r["high"] - a.entry) if long_ else (a.entry - r["low"])) / a.entry * 100)
            mae = max(mae, ((a.entry - r["low"]) if long_ else (r["high"] - a.entry)) / a.entry * 100)
        evs = TM.advise(pos, h1=h1, m15=m, h4=h4, sent=set(sent), now_ts=t, price=px)
        if "STOP_PRICE" in sent and not evs:
            re_ = TM.reentry(pos, m15=m, h4=h4, sent=set(sent), now_ts=t, stop_alert_ts=stop_ts)
            evs = [re_] if re_ else []
        order = {"STOP_PRICE": 0, "END_STRUCTURE_H4": 1, "END_STRUCTURE": 1, "BREAKEVEN": 2, "TP1": 3, "TP2": 4}
        for ev in sorted(evs, key=lambda e: order.get(e["code"].split(":")[0], 9))[:1]:
            sent[ev["code"]] = t
            if ev["code"] == "STOP_PRICE":
                stop_ts = t
            timeline.append((iso(t), ev["text"]))
        if "STOP_PRICE" in sent and "REENTRY" not in sent and t - sent["STOP_PRICE"] > 8 * 3600:
            break
        if "END_STRUCTURE" in sent or "END_STRUCTURE_H4" in sent:
            break
        t += 900
    print(f"== {a.symbol} {a.side} вхід {a.entry} (заповнено {iso(fill_t)}) джерело={a.source}")
    for ts_, tx in timeline:
        print(f"{ts_}  {tx}")
    print(f"MFE {mfe:.2f}% · MAE {mae:.2f}% · подій {len(timeline)} · остання ціна {m15[-1]['close']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

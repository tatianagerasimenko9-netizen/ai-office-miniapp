#!/usr/bin/env python3
"""Replay SHADOW-фільтра «вхід після реакції в зоні» на ІСТОРИЧНИХ Ф'ЮЧЕРСНИХ свічках Binance USDT-M (fapi або data.binance.vision futures/um). Лише читання.

Спот і Bybit НЕ використовуються: якщо ф'ючерсних свічок немає — картка позначається ДАНИХ_НЕМАЄ, жодних підстановок.
V0 = фактичний алгоритм (ліміт на ціні входу, заповнення від дотику; radar_watch.evaluate_card) на тих самих свічках; V1/V2 = office2/reaction_shadow.py (RESEARCH_HYPOTHESIS).
Висновки з окремих карток; загальна статистика не виводиться."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from office2 import reaction_shadow as RS  # noqa: E402

FIX = ROOT / "scripts" / "fixtures" / "radar_cards_filled_2026-10-11.json"
FOCUS = {"B|O2|e008197edf29": "TIA e008", "W|O2|d37a39e701ba": "TIA d37a", "W|O2|c4f50e8085bf": "TIA c4f5", "W|O2|e24e36b66a53": "ETC (WATCH)", "B|O2|e24e36b66a53": "ETC (BLOCKED)",
         "W|O2|7b68061db114": "LINK (WATCH)", "W|O2|cf2a48866bf8": "SEI (WATCH)"}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-office-reaction-shadow/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch_futures_m15(symbol: str, t0: float, t1: float):
    """(бари, джерело). Лише ф'ючерси Binance USDT-M: fapi, інакше денні архіви futures/um. Інакше ([], None)."""
    try:
        raw = json.loads(_get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&startTime={int(t0*1000)}&endTime={int(t1*1000)}&limit=1000"))
        if raw:
            return [{"ts": r[0] / 1000.0, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in raw], "binance_fapi"
    except Exception as exc:  # noqa: BLE001
        print(f"  fapi {symbol}: {type(exc).__name__} {getattr(exc, 'code', '')}", flush=True)
    out = {}
    d = datetime.fromtimestamp(t0, timezone.utc).date()
    end = datetime.fromtimestamp(t1, timezone.utc).date()
    while d <= end:
        url = f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/15m/{symbol}-15m-{d.isoformat()}.zip"
        try:
            z = zipfile.ZipFile(io.BytesIO(_get(url)))
            for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8")):
                if row and row[0].isdigit():
                    o = int(row[0])
                    o = o // 1000 if o > 10**14 else o
                    out[o / 1000.0] = {"ts": o / 1000.0, "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4])}
        except urllib.error.HTTPError as exc:
            print(f"  архів futures {symbol} {d}: HTTP {exc.code}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  архів futures {symbol} {d}: {type(exc).__name__}", flush=True)
        d += timedelta(days=1)
    return ([out[k] for k in sorted(out)], "binance_vision_futures_daily") if out else ([], None)


def run(cards, fetch, now):
    from office2 import radar_watch as RW
    from office2.learning import costs as C

    cache, rows = {}, []
    for c in cards:
        sym = c["symbol"]
        if sym not in cache:
            t0 = min(x["created_ts"] for x in cards if x["symbol"] == sym) - 3600
            cache[sym] = fetch(sym, t0, now)
        bars, src = cache[sym]
        row = {"card_id": c["card_id"], "name": FOCUS.get(c["card_id"], c["symbol"]), "focus": c["card_id"] in FOCUS, "stage": c["stage"], "direction": c["direction"], "source": src, "bars": len(bars)}
        if not bars:
            row["status"] = "ДАНИХ_НЕМАЄ"
            rows.append(row)
            continue
        closed = [b for b in bars if b["ts"] + RS.M15 <= now]
        v0 = RW.evaluate_card(dict(c), closed, now)
        row["V0_actual_on_futures"] = {"status": v0["paper_status"], "r_net": v0["r_net"], "entry_ts": v0["entry_ts"], "reached": v0["reached"]}
        row.update(RS.evaluate(c, bars, now, C.cost_r))
        row["card_entry"], row["card_sl"], row["card_tp1"] = c["entry"], c["sl"], c["tp1"]
        rows.append(row)
    return rows


def fmt(x):
    if not isinstance(x, dict):
        return str(x)
    return f"{x.get('status')} R={x.get('r_net')} вхід={x.get('entry')} RR→TP1={x.get('rr_to_tp1')} MFE={x.get('mfe_r')} MAE={x.get('mae_r')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reaction_shadow_replay.json")
    a = ap.parse_args()
    cards = json.loads(FIX.read_text(encoding="utf-8"))["cards"]
    rows = run(cards, fetch_futures_m15, time.time())
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    nodata = sum(1 for r in rows if r.get("status") == "ДАНИХ_НЕМАЄ")
    for r in sorted(rows, key=lambda x: (not x["focus"], x["name"])):
        print(f"== {r['name']} [{r['card_id']}] {r['stage']} {r['direction']} джерело={r['source']} барів={r['bars']}", flush=True)
        if r.get("status") == "ДАНИХ_НЕМАЄ":
            print("   ДАНИХ_НЕМАЄ (ф'ючерсних свічок не отримано; спот/Bybit не підставляємо)", flush=True)
            continue
        print("   події:", r["events"], "кінець даних:", r.get("data_end_ts"), flush=True)
        if r["focus"]:
            print("   OHLC подій:", r.get("events_ohlc"), "бар скасування:", r.get("cancel_bar"), flush=True)
        print("   V0 фактичний (ліміт від дотику):", r["V0_actual_on_futures"], flush=True)
        print("   V1 реакція:", fmt(r["V1_react"]), flush=True)
        print("   V2 реакція+підтвердження:", fmt(r["V2_react_confirm"]), flush=True)
    print(f"карток {len(rows)}, без ф'ючерсних даних {nodata}", flush=True)
    return 0                                          # частина карток може бути без даних — це видно в підсумку, а не збій


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Хронологічний replay «право на вхід» для карток радара на РЕАЛЬНИХ закритих M15 Binance USDT-M (без lookahead, лише читання).

Для кожної картки з paper-входом: чи вхід відбувся після власного тригера картки (office2/entry_audit.py), і що було б, якби вхід дозволявся лише після тригера (контрфактично, той самий SL/цілі).
Не змінює LIVE, не пише в БД/Telegram. n мале (один день): висновків про edge не робимо — лише факти по кожній картці."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from office2 import entry_audit as EA  # noqa: E402

FIX = ROOT / "scripts" / "fixtures" / "radar_cards_filled_2026-10-11.json"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-office-entry-audit/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def fetch_m15(symbol: str, t0: float, t1: float):
    """Реальні M15: спершу fapi (кінцеві свічки), інакше денні архіви data.binance.vision. Невдача → виняток, дані не вигадуються."""
    try:
        raw = json.loads(_get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&startTime={int(t0*1000)}&endTime={int(t1*1000)}&limit=1000"))
        return [{"ts": r[0] / 1000.0, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])} for r in raw]
    except Exception as exc:  # noqa: BLE001
        print(f"  fapi {symbol}: {type(exc).__name__}; пробую архів", flush=True)
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
        except Exception as exc:  # noqa: BLE001
            print(f"  архів {symbol} {d}: {type(exc).__name__}", flush=True)
        d = datetime.fromtimestamp(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() + 86400, timezone.utc).date()
    if out:
        return [out[k] for k in sorted(out)]
    return fetch_m15_miniapp(symbol)


def fetch_m15_miniapp(symbol: str):
    """Запасний шлях: GET /api/v2/candles нашого Mini App (реальні ф'ючерсні свічки Binance, які бачить production). Лише читання; незакрита свічка відкидається вище за течією."""
    try:
        d = json.loads(_get(f"https://ai-office-miniapp.onrender.com/api/v2/candles?symbol={symbol}&tf=M15&limit=500"))
        bars = [{"ts": float(b["time"]), "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]} for b in (d.get("candles") or d.get("bars") or []) if b.get("time") and not b.get("forming")]
        print(f"  Mini App {symbol}: {len(bars)} закритих M15, джерело {d.get('source')}", flush=True)
        return sorted(bars, key=lambda x: x["ts"])
    except Exception as exc:  # noqa: BLE001
        print(f"  Mini App {symbol}: {type(exc).__name__}: {str(exc)[:80]}", flush=True)
        return []


def run(cards, fetch, now):
    by_sym = {}
    for c in cards:
        by_sym.setdefault(c["symbol"], []).append(c)
    rows = []
    for sym, cs in by_sym.items():
        t0 = min(c["created_ts"] for c in cs) - 3600
        t1 = max([c["expires_ts"] for c in cs] + [now]) + 86400 / 4
        m15 = fetch(sym, t0, min(t1, now))
        for c in cs:
            a = EA.audit_card(c, EA.closed_m15(m15, now))
            a["stage"], a["kind"], a["paper_actual"] = c["stage"], c["kind"], {"status": c["paper_status"], "r_net": c["r_net"]}
            a["variant_confirmed_entry"] = EA.confirmed_variant(c, m15, now)
            a["m15_bars"] = len(m15)
            rows.append(a)
    return rows


def summarize(rows):
    v = {}
    for r in rows:
        v[r["verdict"]] = v.get(r["verdict"], 0) + 1
    both = [r for r in rows if r.get("variant_confirmed_entry") and r["variant_confirmed_entry"].get("r_net") is not None and r["paper_actual"]["r_net"] is not None]
    return {"cards": len(rows), "verdicts": v,
            "r_actual_closed_with_variant": round(sum(r["paper_actual"]["r_net"] for r in both), 3), "r_variant_same_cards": round(sum(r["variant_confirmed_entry"]["r_net"] for r in both), 3), "n_compared": len(both),
            "note": "n мале (один день, одна сесія); це факти по окремих картках, а не доказ edge чи його відсутності"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="entry_audit_replay.json")
    ap.add_argument("--symbols", default="")
    a = ap.parse_args()
    cards = json.loads(FIX.read_text(encoding="utf-8"))["cards"]
    if a.symbols:
        keep = set(a.symbols.upper().split(","))
        cards = [c for c in cards if c["symbol"] in keep]
    rows = run(cards, fetch_m15, time.time())
    summ = summarize(rows)
    summ["cards_without_candles"] = sum(1 for r in rows if r["verdict"] == "НЕМАЄ_СВІЧОК")
    Path(a.out).write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(r["card_id"], r["symbol"], r["stage"], r["verdict"], "actual:", r["paper_actual"], "variant:", r["variant_confirmed_entry"], flush=True)
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    if summ["cards_without_candles"]:
        print("ПОМИЛКА: для частини карток немає реальних свічок — результат неповний, висновків не робимо", flush=True)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

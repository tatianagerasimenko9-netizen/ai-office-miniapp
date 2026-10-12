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
        row["V3_guard"] = RS.invalidation_guard(c, closed, v0["entry_ts"], now)
        row["card_entry"], row["card_sl"], row["card_tp1"] = c["entry"], c["sl"], c["tp1"]
        row["created_ts"], row["sent_ts"] = c["created_ts"], c.get("sent_ts")
        row["signal_bar_start"] = RS.signal_bar_start(c)
        row["V0_visible_from"] = ((max(c["created_ts"], c.get("sent_ts") or 0)) // 900 + 1) * 900.0
        if row["focus"] and row.get("cancel_bar"):
            row["cancel_timing_m1"] = cancel_timing(row, c)
        rows.append(row)
    return rows


def fetch_m1_day(symbol: str, day):
    """Ф'ючерсні M1 за добу (data.binance.vision futures/um) — лише для розв'язання внутрішньобарного порядку подій (кого раніше: сигнал чи пробій стопа)."""
    url = f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/1m/{symbol}-1m-{day.isoformat()}.zip"
    try:
        z = zipfile.ZipFile(io.BytesIO(_get(url)))
        out = []
        for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8")):
            if row and row[0].isdigit():
                o = int(row[0])
                o = o // 1000 if o > 10**14 else o
                out.append({"ts": o / 1000.0, "open": float(row[1]), "high": float(row[2]), "low": float(row[3]), "close": float(row[4])})
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"  M1 {symbol} {day}: {type(exc).__name__} {getattr(exc, 'code', '')}", flush=True)
        return []


def cancel_timing(row, card, m1_fetch=fetch_m1_day):
    """Для картки, скасованої пробоєм стопа в M15-барі: на якій хвилині low досяг SL відносно моменту сигналу (M1)."""
    cb = row.get("cancel_bar")
    if not cb:
        return None
    long_ = str(card["direction"]).upper() != "SHORT"
    day = datetime.fromtimestamp(cb["ts"], timezone.utc).date()
    m1 = [m for m in m1_fetch(card["symbol"], day) if cb["ts"] <= m["ts"] < cb["ts"] + RS.M15]
    if not m1:
        return {"status": "M1_НЕМАЄ"}
    hit = next((m for m in m1 if ((m["low"] <= card["sl"]) if long_ else (m["high"] >= card["sl"]))), None)
    sig = max(card["created_ts"], card.get("sent_ts") or 0)
    return {"signal_ts": sig, "first_minute_at_or_beyond_sl": hit["ts"] if hit else None, "minute_ohlc": hit,
            "breach_before_signal": (hit["ts"] + 60 <= sig) if hit else None}


def boot_ci(xs, iters=2000, seed=7):
    import random

    if len(xs) < 2:
        return None
    rnd = random.Random(seed)
    m = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(iters))
    return [round(m[int(0.025 * iters)], 3), round(m[int(0.975 * iters)], 3)]


def summarize(rows):
    """Підсумок по картках з ф'ючерсними даними; V0/V1/V2 на тих самих свічках, тих самих SL/цілях, тими самими витратами."""
    ok = [r for r in rows if r.get("status") != "ДАНИХ_НЕМАЄ"]
    out = {"cards_with_data": len(ok), "cards_without_data": len(rows) - len(ok)}

    def v(r, k):
        if k == "V3":
            if r["V3_guard"]["blocked"]:
                return {"status": "НЕМАЄ_ВХОДУ", "r_net": None}
            k = "V0"
        if k == "V0":
            x = r["V0_actual_on_futures"]
            if x["status"] in ("WAITING_ENTRY", "NO_ENTRY"):
                return {"status": "НЕМАЄ_ВХОДУ", "r_net": None}
            return {"status": "SL" if x["status"] == "SL" else ("TP1" if x["r_net"] is not None else "ВІДКРИТА"), "r_net": x["r_net"]}
        return r["V1_react" if k == "V1" else "V2_react_confirm"]

    for k in ("V0", "V1", "V2", "V3"):
        xs = [v(r, k) for r in ok]
        ent = [x for x in xs if x["status"] not in ("НЕМАЄ_ВХОДУ", "ПРОПУЩЕНО_ЦІНА_ПОЗА_ПЛАНОМ", "НЕМАЄ_ЦІЛІ")]
        closed = [x["r_net"] for x in ent if x.get("r_net") is not None]
        rr = [x["rr_to_tp1"] for x in ent if x.get("rr_to_tp1") is not None]
        out[k] = {"entered": len(ent), "no_entry": len(xs) - len(ent), "SL": sum(1 for x in ent if x["status"] == "SL"), "TP1": sum(1 for x in ent if x["status"] == "TP1"),
                  "open_at_data_end": sum(1 for x in ent if x["status"] == "ВІДКРИТА"), "closed_n": len(closed), "sum_R_closed": round(sum(closed), 3),
                  "mean_R_closed": round(sum(closed) / len(closed), 3) if closed else None, "mean_R_ci95": boot_ci(closed), "rr_to_tp1_below_2": sum(1 for q in rr if q < 2.0), "rr_known": len(rr)}
    for k in ("V1", "V2", "V3"):
        mw = [r["name"] for r in ok if (v(r, "V0").get("r_net") or 0) > 0 and v(r, k)["status"] in ("НЕМАЄ_ВХОДУ",)]
        al = [r["name"] for r in ok if v(r, "V0")["status"] == "SL" and v(r, k)["status"] in ("НЕМАЄ_ВХОДУ",)]
        both_sl = [r["name"] for r in ok if v(r, "V0")["status"] == "SL" and v(r, k)["status"] == "SL"]
        shrunk = [(r["name"], v(r, "V0")["r_net"], v(r, k).get("r_net")) for r in ok if (v(r, "V0").get("r_net") or 0) > 0 and v(r, k).get("r_net") is not None]
        out[k + "_vs_V0"] = {"missed_winners": mw, "avoided_losses": al, "stop_still_hit": both_sl, "winner_profit_V0_vs_variant": shrunk}
    return out


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
    summ = summarize(rows)
    Path(a.out).write_text(json.dumps({"summary": summ, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    nodata = sum(1 for r in rows if r.get("status") == "ДАНИХ_НЕМАЄ")
    for r in sorted(rows, key=lambda x: (not x["focus"], x["name"])):
        print(f"== {r['name']} [{r['card_id']}] {r['stage']} {r['direction']} джерело={r['source']} барів={r['bars']}", flush=True)
        if r.get("status") == "ДАНИХ_НЕМАЄ":
            print("   ДАНИХ_НЕМАЄ (ф'ючерсних свічок не отримано; спот/Bybit не підставляємо)", flush=True)
            continue
        print("   події:", r["events"], "кінець даних:", r.get("data_end_ts"), flush=True)
        if r["focus"]:
            print("   OHLC подій:", r.get("events_ohlc"), "бар скасування:", r.get("cancel_bar"), "M1:", r.get("cancel_timing_m1"), flush=True)
        print("   V0 фактичний (ліміт від дотику):", r["V0_actual_on_futures"], flush=True)
        print("   V1 реакція:", fmt(r["V1_react"]), flush=True)
        print("   V2 реакція+підтвердження:", fmt(r["V2_react_confirm"]), flush=True)
        print("   V3 (V0 без входу, якщо стоп торкнувся до заповнення):", r["V3_guard"], flush=True)
    print(f"карток {len(rows)}, без ф'ючерсних даних {nodata}", flush=True)
    print("ПІДСУМОК:", json.dumps(summ, ensure_ascii=False, indent=1), flush=True)
    return 0                                          # частина карток може бути без даних — це видно в підсумку, а не збій


if __name__ == "__main__":
    sys.exit(main())

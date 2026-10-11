#!/usr/bin/env python3
"""Replay shadow-правил з першоджерел на реальних D1 Binance USDT-M (data.binance.vision), БЕЗ lookahead.

Що перевіряється (не торгова система, а чи несе правило інформацію про напрям):
  подія = паранормальний D1 бар (G-LVL-PARANORMAL/G-ATR-CALC), виявлений на його закритті; далі для кожного стану бази (D-POST-IMPULSE-BASE) беремо
  ПЕРШИЙ день, коли стан настав (рішення на закритті цього дня), і міряємо рух у напрямку імпульсу за 1/3/7 днів вперед від цього закриття.
Порівняння: базова лінія = середній рух у напрямку імпульсу від закриття паранормального бару (без умови на базу) і нуль. Витрати: подія без входу → комісії не застосовуються;
для торгової перевірки потрібні вхід/стоп, яких джерело не задає (`НЕ ПІДТВЕРДЖЕНО`). Розбивка за періодами train/test; довірчий інтервал — bootstrap за подіями.
Нічого не пише в БД, Render, Telegram. Висновок про edge робиться лише якщо CI не включає 0 в ОБОХ періодах та n≥30 (SOURCE_RULES.md); інакше EDGE_NOT_PROVEN."""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from office2 import source_shadow as S  # noqa: E402

SYMBOLS = "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,ADAUSDT,DOGEUSDT,LTCUSDT,LINKUSDT,AVAXUSDT,DOTUSDT,BNBUSDT,TRXUSDT,ATOMUSDT,NEARUSDT,FILUSDT,APTUSDT,ARBUSDT,OPUSDT,INJUSDT,SUIUSDT"
HORIZONS = (1, 3, 7)
SPLIT = datetime(2024, 7, 1, tzinfo=timezone.utc).timestamp()      # train < SPLIT ≤ test (фіксовано до перегляду результатів)


def months(start: str, end: str) -> List[str]:
    y, m = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def load_symbol(symbol: str, start: str, end: str) -> List[Dict[str, Any]]:
    import fetch_binance_archive as FB

    rows: List[Dict[str, Any]] = []
    for mo in months(start, end):
        try:
            rows += FB._fetch_month(symbol, "1d", mo)
        except Exception:  # noqa: BLE001 — місяця може не бути (лістинг пізніше)
            continue
    out = {}
    for r in rows:
        ts = datetime.fromisoformat(r["ts"]).timestamp()
        out[ts] = {"ts": ts, "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
    return [out[k] for k in sorted(out)]


def events_for(symbol: str, d1: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Walk-forward: рішення на закритті кожного D1; лише бари ≤ i."""
    evs: List[Dict[str, Any]] = []
    seen_anchor: Dict[float, Dict[str, Any]] = {}
    n = len(d1)
    for i in range(10, n):
        as_of = d1[i]["ts"] + 86400.0
        window = d1[max(0, i - 80): i + 1]
        bars = S.closed_d1(window, as_of)
        for p in S.paranormal_bars(bars, last_n=S.LOOKBACK_IMPULSE_DAYS):
            if p["ts"] not in seen_anchor and p["i"] == len(bars) - 1:      # перший раз: виявлений на власному закритті
                seen_anchor[p["ts"]] = {"p": p, "states": {}, "i0": i, "ts": p["ts"], "symbol": symbol}
        for a in list(seen_anchor.values()):
            k = i - a["i0"]
            if k < 1 or k > S.STALE_DAYS + 2:
                continue
            p = a["p"]
            base_after = [b for b in S.closed_d1(window, as_of) if b["ts"] > p["ts"]]
            st = S.base_state(p, base_after)["state"]
            if st not in a["states"]:
                a["states"][st] = i
    for a in seen_anchor.values():
        p = a["p"]
        sign = -1.0 if p["direction"] == "DOWN" else 1.0

        def fwd(i0: int, h: int):
            if i0 + h >= n:
                return None
            return sign * (d1[i0 + h]["close"] / d1[i0]["close"] - 1.0) * 100.0

        rec = {"symbol": a["symbol"], "ts": a["ts"], "direction": p["direction"], "x_atr": p["x_atr"], "base0": {h: fwd(a["i0"], h) for h in HORIZONS}, "states": {}}
        for st, i in a["states"].items():
            rec["states"][st] = {"day": d1[i]["ts"], "fwd": {h: fwd(i, h) for h in HORIZONS}}
        evs.append(rec)
    return evs


def boot_ci(xs: List[float], iters: int = 2000, seed: int = 7):
    if len(xs) < 2:
        return None
    rnd = random.Random(seed)
    means = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(iters))
    return [means[int(0.025 * iters)], means[int(0.975 * iters)]]


def stats(xs: List[float]) -> Dict[str, Any]:
    xs = [x for x in xs if x is not None and not math.isnan(x)]
    if not xs:
        return {"n": 0}
    m = sum(xs) / len(xs)
    return {"n": len(xs), "mean_pct": round(m, 3), "hit_rate": round(sum(1 for x in xs if x > 0) / len(xs), 3), "ci95": [round(v, 3) for v in (boot_ci(xs) or [])]}


def summarize(all_ev: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"events_total": len(all_ev), "by_period": {}}
    for label, f in (("train(<2024-07)", lambda e: e["ts"] < SPLIT), ("test(≥2024-07)", lambda e: e["ts"] >= SPLIT)):
        evs = [e for e in all_ev if f(e)]
        per: Dict[str, Any] = {"events": len(evs), "baseline_after_impulse": {h: stats([e["base0"][h] for e in evs]) for h in HORIZONS}, "states": {}}
        names = sorted({st for e in evs for st in e["states"]})
        for st in names:
            per["states"][st] = {"first_day_events": sum(1 for e in evs if st in e["states"]), "fwd": {h: stats([e["states"][st]["fwd"][h] for e in evs if st in e["states"]]) for h in HORIZONS}}
        out["by_period"][label] = per
    out["verdict"] = verdict(out)
    return out


def verdict(summ: Dict[str, Any]) -> Dict[str, str]:
    """EDGE_NOT_PROVEN, якщо для стану не виконано: n≥30 в обох періодах і CI (3 дні) > 0 в обох."""
    v: Dict[str, str] = {}
    tr, te = summ["by_period"]["train(<2024-07)"], summ["by_period"]["test(≥2024-07)"]
    for st in sorted(set(tr["states"]) | set(te["states"])):
        a = (tr["states"].get(st) or {}).get("fwd", {}).get(3) or {}
        b = (te["states"].get(st) or {}).get("fwd", {}).get(3) or {}
        ok = a.get("n", 0) >= 30 and b.get("n", 0) >= 30 and (a.get("ci95") or [0, 0])[0] > 0 and (b.get("ci95") or [0, 0])[0] > 0
        v[st] = "EDGE_CANDIDATE_NEEDS_COST_AND_ENTRY_TEST" if ok else "EDGE_NOT_PROVEN"
    return v


def selftest() -> int:
    """Синтетичний прогін без мережі: перевіряє, що walk-forward не падає і рахує події."""
    import random as r

    r.seed(3)
    d1, px, t0 = [], 100.0, 1_600_000_000 - (1_600_000_000 % 86400)
    for i in range(400):
        o = px
        c = px * (1 + r.uniform(-0.01, 0.01) * (6 if i % 70 == 69 else 1))
        d1.append({"ts": t0 + i * 86400.0, "open": o, "high": max(o, c) * 1.004, "low": min(o, c) * 0.996, "close": c, "volume": 1.0})
        px = c
    ev = events_for("SYN", d1)
    print("selftest events:", len(ev))
    summ = summarize(ev)
    print(json.dumps(summ["verdict"], ensure_ascii=False))
    return 0 if ev else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default=SYMBOLS)
    ap.add_argument("--start", default="2021-01")
    ap.add_argument("--end", default="2026-09")
    ap.add_argument("--out", default="source_shadow_replay.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    all_ev: List[Dict[str, Any]] = []
    prov: Dict[str, Any] = {}
    for sym in [x.strip().upper() for x in a.symbols.split(",") if x.strip()]:
        d1 = load_symbol(sym, a.start, a.end)
        prov[sym] = {"bars": len(d1), "first": datetime.fromtimestamp(d1[0]["ts"], timezone.utc).date().isoformat() if d1 else None, "last": datetime.fromtimestamp(d1[-1]["ts"], timezone.utc).date().isoformat() if d1 else None}
        if len(d1) < 60:
            continue
        all_ev += events_for(sym, d1)
        print(f"{sym}: {len(d1)} D1, подій {sum(1 for e in all_ev if e['symbol']==sym)}", flush=True)
    summ = summarize(all_ev)
    summ["provenance"] = {"source": "data.binance.vision futures/um monthly 1d", "split_ts": SPLIT, "symbols": prov, "version": S.VERSION,
                          "caveats": ["подія без входу/стопа: джерело їх не задає", "база вимірюється через діапазон одного паранормального бару (ГІПОТЕЗА)", "ATR Герчика на 5 D1 без паранормальних (ГІПОТЕЗА щодо першої оцінки й гепів)", "кілька подій на день між монетами корельовані"]}
    Path(a.out).write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"events": summ["events_total"], "verdict": summ["verdict"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

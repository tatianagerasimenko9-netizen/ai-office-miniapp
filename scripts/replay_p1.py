#!/usr/bin/env python3
"""P1 replay без lookahead: незалежна оцінка входу/стопа/цілей READY на ринкових свічках 5m (data.binance.vision, лише читання).

Рішення (вхід, SL, TP, час) беруться з таблиці READY як є; ATR рахується ЛИШЕ зі свічок ДО моменту READY. Результат дивимось тільки ПІСЛЯ T.
Консервативно: у свічці, що торкнулась і стопа, і цілі, — спершу стоп; свічка підтвердження (відкрита до T) не використовується; на свічці заповнення цілі не зараховуються.
Метрики: заповнення, перший результат (TP1/STOP), найвища ціль, MFE/MAE, STOP_THEN_DIRECTION (після стопа TP1 досягається ≤24 год), розріз за стоп/ATR(H1), ризик%, RR.
Свічок за межами доступних даних немає → результат «не розв'язано» (цензура), а не вигаданий.
Використання: replay_p1.py <таблиця.psv> [--cache DIR]"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

FILL_WINDOW_SEC = 24 * 3600
TRACK_SEC = 72 * 3600
AFTER_STOP_SEC = 24 * 3600
BINS = [(0.0, 0.5, "<0.5 ATR"), (0.5, 0.75, "0.5–0.75"), (0.75, 1.0, "0.75–1.0"), (1.0, 1.25, "1.0–1.25"), (1.25, 1.5, "1.25–1.5"), (1.5, 1e9, ">1.5 ATR")]
Candle = Tuple[float, float, float, float, float]   # open_ts, open, high, low, close


def _f(x: Any) -> Optional[float]:
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def load_psv(path: str, year: int = 2026) -> List[Dict[str, Any]]:
    from zoneinfo import ZoneInfo

    rows = []
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("#") or not ln.strip():
            continue
        c = ln.rstrip("\n").split("|")
        mmdd, hhmm = c[0].split()
        dt = datetime(year, int(mmdd[:2]), int(mmdd[3:5]), int(hhmm[:2]), int(hhmm[3:5]), tzinfo=ZoneInfo("Europe/Kyiv"))
        rows.append({"t": dt.timestamp(), "sym": c[2] + "USDT", "dir": "LONG" if c[3] == "L" else "SHORT", "entry": _f(c[4]), "sl": _f(c[5]), "tp1": _f(c[6]),
                     "tp2": _f(c[7]), "tp3": _f(c[8]), "risk_pct": _f(c[9]), "rr_net": _f(c[10]), "flags": c[15] if len(c) > 15 else ""})
    rows.sort(key=lambda r: r["t"])
    return rows


def fetch_day_5m(sym: str, day: str, cache: Optional[str] = None) -> List[Candle]:
    """Свічки 5m за добу UTC з data.binance.vision; [] якщо файла немає (ще не опубліковано / немає монети)."""
    fn = f"{sym}-5m-{day}"
    cp = os.path.join(cache, fn + ".csv") if cache else None
    if cp and os.path.exists(cp):
        raw = open(cp, encoding="utf-8").read()
    else:
        url = f"https://data.binance.vision/data/futures/um/daily/klines/{sym}/5m/{fn}.zip"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            raw = z.read(z.namelist()[0]).decode()
        except Exception:  # noqa: BLE001
            return []
        if cp:
            os.makedirs(cache, exist_ok=True)
            open(cp, "w", encoding="utf-8").write(raw)
    out: List[Candle] = []
    for rec in csv.reader(io.StringIO(raw)):
        try:
            out.append((float(rec[0]) / 1000.0, float(rec[1]), float(rec[2]), float(rec[3]), float(rec[4])))
        except (ValueError, IndexError):
            continue   # заголовок
    return out


def candles_range(sym: str, t0: float, t1: float, fetch_day: Callable[[str, str], List[Candle]]) -> List[Candle]:
    d = datetime.fromtimestamp(t0, tz=timezone.utc).date()
    end = datetime.fromtimestamp(t1, tz=timezone.utc).date()
    out: List[Candle] = []
    while d <= end:
        out += fetch_day(sym, d.isoformat())
        d += timedelta(days=1)
    return sorted(c for c in out if t0 - 1 <= c[0] <= t1)


def atr_h1(c5: List[Candle], t: float, n: int = 14) -> Optional[float]:
    """ATR(14) по годинних свічках, зібраних зі свічок 5m, ЛИШЕ завершених до t."""
    hours: Dict[float, List[float]] = {}
    for ts, o, h, l, c in c5:
        if ts + 300 > t:
            continue
        hk = ts - ts % 3600
        if hk + 3600 > t:
            continue   # година ще не завершена
        b = hours.setdefault(hk, [o, h, l, c, 0])
        b[1], b[2], b[3] = max(b[1], h), min(b[2], l), c
    keys = sorted(hours)
    trs, prev_c = [], None
    for k in keys:
        o, h, l, c, _ = hours[k]
        trs.append(max(h - l, abs(h - prev_c), abs(l - prev_c)) if prev_c is not None else h - l)
        prev_c = c
    return sum(trs[-n:]) / len(trs[-n:]) if len(trs) >= max(4, n // 2) else None


def simulate(row: Dict[str, Any], c5: List[Candle], data_end: float) -> Dict[str, Any]:
    long_ = row["dir"] != "SHORT"
    e, sl = row["entry"], row["sl"]
    tps = [(n, row[k]) for n, k in (("TP1", "tp1"), ("TP2", "tp2"), ("TP3", "tp3")) if row.get(k) is not None]
    t0 = row["t"]
    res: Dict[str, Any] = {"fill": False, "first": "NONE", "best": None, "mfe": 0.0, "mae": 0.0, "resolved": False, "stop_then_dir": None, "t_fill": None, "t_end": None}
    if not e or sl is None or not tps:
        res["first"] = "INVALID"
        return res
    reached: List[str] = []
    filled = False
    t_stop = None
    for ts, o, h, l, c in c5:
        if ts < t0:
            continue                         # свічка підтвердження/до сигналу не використовується
        if not filled:
            if ts - t0 > FILL_WINDOW_SEC:
                res.update(first="NO_FILL", resolved=True)
                return res
            if l <= e <= h:
                filled, res["fill"], res["t_fill"] = True, True, ts
                res["mfe"] = max(res["mfe"], ((h - e) if long_ else (e - l)) / e * 100)
                res["mae"] = max(res["mae"], ((e - l) if long_ else (h - e)) / e * 100)
                if (l <= sl) if long_ else (h >= sl):
                    res.update(first="STOP", best=None, resolved=True, t_end=ts)
                    t_stop = ts
                    break
            continue
        res["mfe"] = max(res["mfe"], ((h - e) if long_ else (e - l)) / e * 100)
        res["mae"] = max(res["mae"], ((e - l) if long_ else (h - e)) / e * 100)
        if (l <= sl) if long_ else (h >= sl):
            res.update(first=("STOP" if not reached else reached[0] + "_THEN_STOP"), best=(reached[-1] if reached else None), resolved=True, t_end=ts)
            t_stop = ts
            break
        for n, lv in tps:
            if n not in reached and ((h >= lv) if long_ else (l <= lv)):
                reached.append(n)
                if res["first"] == "NONE":
                    res["first"] = n
        if tps[-1][0] in reached:
            res.update(best=reached[-1], resolved=True, t_end=ts)
            break
        if ts - res["t_fill"] > TRACK_SEC:
            res.update(best=reached[-1] if reached else None, resolved=True, t_end=ts)
            break
    if res["fill"] and not res["resolved"]:
        res["best"] = reached[-1] if reached else None   # цензура: дані скінчились
    if not res["fill"] and not res["resolved"]:
        res["first"] = "NO_FILL" if data_end - t0 > FILL_WINDOW_SEC else "NONE"
        res["resolved"] = res["first"] == "NO_FILL"
    if t_stop is not None and row.get("tp1") is not None:
        t1 = row["tp1"]
        after = [x for x in c5 if t_stop < x[0] <= t_stop + AFTER_STOP_SEC]
        if data_end >= t_stop + AFTER_STOP_SEC or any((x[2] >= t1) if long_ else (x[3] <= t1) for x in after):
            res["stop_then_dir"] = any((x[2] >= t1) if long_ else (x[3] <= t1) for x in after)
    return res


def bucket(x: Optional[float]) -> str:
    if x is None:
        return "немає ATR"
    for lo, hi, name in BINS:
        if lo <= x < hi:
            return name
    return ">1.5 ATR"


def run(rows: List[Dict[str, Any]], fetch_day: Callable[[str, str], List[Candle]]) -> Dict[str, Any]:
    by_sym: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_sym[r["sym"]].append(r)
    out_rows = []
    missing = []
    for sym, rs in by_sym.items():
        t_lo, t_hi = min(r["t"] for r in rs) - 3 * 86400, max(r["t"] for r in rs) + 4 * 86400
        c5 = candles_range(sym, t_lo, t_hi, fetch_day)
        if not c5:
            missing.append(sym)
            continue
        data_end = c5[-1][0] + 300
        for r in rs:
            a = atr_h1([c for c in c5 if c[0] < r["t"]], r["t"])
            risk = abs(r["entry"] - r["sl"]) if r["entry"] and r["sl"] is not None else None
            sim = simulate(r, [c for c in c5 if c[0] >= r["t"] - 1], data_end)
            out_rows.append({**r, **sim, "stop_atr": (risk / a) if (risk is not None and a) else None, "bin": bucket((risk / a) if (risk is not None and a) else None)})
    return {"rows": out_rows, "missing": missing}


def summarize(rows: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    g: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        g[str(r[key])].append(r)
    order = [b[2] for b in BINS] + ["немає ATR"]
    out = []
    for k in (order if key == "bin" else sorted(g)):
        rs = g.get(k, [])
        if not rs:
            continue
        filled = [r for r in rs if r["fill"]]
        res = [r for r in filled if r["resolved"] and r["first"] != "NONE"]
        stop1 = [r for r in res if r["first"] == "STOP"]
        tp1 = [r for r in res if r["first"] in ("TP1", "TP2", "TP3") or r["first"].endswith("_THEN_STOP")]
        std = [r for r in stop1 if r["stop_then_dir"] is not None]
        out.append({"група": k, "n": len(rs), "заповнено": len(filled), "розв'язано": len(res), "STOP першим %": round(100 * len(stop1) / len(res), 1) if res else None,
                    "TP1 до стопа %": round(100 * len(tp1) / len(res), 1) if res else None,
                    "STOP_THEN_DIRECTION %": round(100 * sum(1 for r in std if r["stop_then_dir"]) / len(std), 1) if std else None,
                    "MAE середня %": round(sum(r["mae"] for r in filled) / len(filled), 2) if filled else None,
                    "MFE середня %": round(sum(r["mfe"] for r in filled) / len(filled), 2) if filled else None})
    return out


def main() -> int:
    path = sys.argv[1]
    cache = sys.argv[sys.argv.index("--cache") + 1] if "--cache" in sys.argv else "/tmp/klines5m"
    rows = load_psv(path)
    data = run(rows, lambda s, d: fetch_day_5m(s, d, cache))
    rr = data["rows"]
    for r in rr:
        r["unique"] = not any(x in r["flags"].split(",") for x in ("D", "R"))
    for r in rr:   # групи за ризиком і RR
        r["risk_bin"] = "<1%" if (r["risk_pct"] or 0) < 1 else ("1–1.5%" if r["risk_pct"] < 1.5 else ("1.5–2.5%" if r["risk_pct"] < 2.5 else ">2.5%"))
        r["rr_bin"] = "<2" if (r["rr_net"] or 0) < 2 else ("2–3" if r["rr_net"] < 3 else ("3–5" if r["rr_net"] < 5 else "≥5"))
    print(f"READY у таблиці {len(rows)}; з даними свічок {len(rr)}; монет без даних {len(data['missing'])}: {','.join(data['missing'][:30])}")
    for title, subset in (("УСІ", rr), ("УНІКАЛЬНІ (без D/R)", [r for r in rr if r["unique"]])):
        print(f"\n=== {title}: n={len(subset)} ===")
        for key in ("bin", "risk_bin", "rr_bin"):
            print(f"-- за {key}")
            for s in summarize(subset, key):
                print(json.dumps(s, ensure_ascii=False))
        print("-- напрям")
        for s in summarize(subset, "dir"):
            print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

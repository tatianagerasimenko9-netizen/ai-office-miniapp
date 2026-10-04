#!/usr/bin/env python3
"""Строгий пересчет результатів доставлених READY за 1m-свічками Binance USDT-M Futures (публічний архів data.binance.vision, лише читання).

Навіщо: «офіційні» підсумки (SIGNAL_RESULT) рахуються по 15m, а свічка 15m, у якій видано READY, враховується цілою (її рух ДО сигналу теж),
і при дотику стопу й цілі в одній свічці стоп береться першим. Тут той самий production-код `office_signal_track.simulate`, але на 1m-свічках
і з правилом життєвого циклу (свічки до моменту READY пропускаються), плюс окремі позначки:
- tie: стоп і TP1 торкнулись в ОДНІЙ хвилині (порядок невідомий; рахується як стоп — так само, як у lifecycle);
- first: що було ПЕРШИМ — SL чи TP1;
- data_end: до якого моменту є свічки (нема даних = не перевірено, а не «нічого не сталось»).
Без lookahead: ознаки ринку (BTC, ATR) беруться лише зі свічок, закритих ДО моменту READY.

Використання: python scripts/ready_replay_strict.py --plans data/research/ready_plans_2026-10-01_04.json --out /tmp/ready_strict.json [--cache DIR] [--offline]
"""
from __future__ import annotations

import argparse
import bisect
import csv
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

import office_signal_track as trk  # noqa: E402

BASE = "https://data.binance.vision/data/futures/um/daily/klines"
MAX_TRACK = trk.MAX_TRACK_SEC


def _day(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def fetch_day(symbol: str, day: datetime, cache: Path, offline: bool) -> Optional[List[List[float]]]:
    """Рядки [open_time_s, o, h, l, c, v] за добу або None, якщо архіву немає (404 тощо)."""
    name = f"{symbol}-1m-{day:%Y-%m-%d}"
    cp = cache / f"{name}.json"
    if cp.exists():
        return json.loads(cp.read_text())
    if offline:
        return None
    url = f"{BASE}/{urllib.parse.quote(symbol)}/1m/{urllib.parse.quote(name)}.zip"
    data = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "office-research"}), timeout=60) as r:
                data = r.read()
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                cp.write_text("null")
                return None
            time.sleep(2 * (attempt + 1))
        except Exception:  # noqa: BLE001
            time.sleep(2 * (attempt + 1))
    if data is None:
        return None
    rows: List[List[float]] = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        with z.open(z.namelist()[0]) as f:
            for rec in csv.reader(io.TextIOWrapper(f)):
                try:
                    t = float(rec[0])
                except ValueError:
                    continue   # заголовок
                t = t / 1000.0 if t > 1e11 else t
                rows.append([t, float(rec[1]), float(rec[2]), float(rec[3]), float(rec[4]), float(rec[5])])
    cp.write_text(json.dumps(rows))
    return rows


def load_symbol(symbol: str, d0: datetime, d1: datetime, cache: Path, offline: bool) -> Tuple[List[List[float]], List[str]]:
    rows: List[List[float]] = []
    missing: List[str] = []
    d = d0
    while d <= d1:
        r = fetch_day(symbol, d, cache, offline)
        if r:
            rows.extend(r)
        else:
            missing.append(f"{d:%Y-%m-%d}")
        d += timedelta(days=1)
    rows.sort(key=lambda x: x[0])
    return rows, missing


def as_candles(rows: List[List[float]]) -> List[Dict[str, Any]]:
    return [{"ts": datetime.fromtimestamp(r[0], tz=timezone.utc).isoformat(), "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in rows]


def ret_pct(rows: List[List[float]], times: List[float], t: float, back_sec: float) -> Optional[float]:
    """Зміна close за back_sec до моменту t лише за свічками, ЗАКРИТИМИ до t (open+60 ≤ t)."""
    i = bisect.bisect_right(times, t - 60.0) - 1
    j = bisect.bisect_right(times, t - 60.0 - back_sec) - 1
    if i < 0 or j < 0 or abs(times[i] - (t - 60.0)) > 180 or abs(times[j] - (t - 60.0 - back_sec)) > 180:
        return None
    a, b = rows[j][4], rows[i][4]
    return round((b / a - 1.0) * 100.0, 3) if a else None


def atr15(rows: List[List[float]], times: List[float], t: float, n: int = 14) -> Optional[float]:
    """ATR(14) по 15m-барах, зібраних із 1m, закритих ДО t."""
    end = bisect.bisect_right(times, t - 60.0)
    if end < 15 * (n + 2):
        return None
    last_bar_open = ((int(t) - 900) // 900) * 900   # останній повністю закритий 15m бар
    bars: List[Tuple[float, float, float]] = []   # high, low, close
    for k in range(n + 1):
        b0 = last_bar_open - 900 * k
        i0 = bisect.bisect_left(times, b0)
        i1 = bisect.bisect_left(times, b0 + 900)
        if i1 - i0 < 10:
            return None
        seg = rows[i0:i1]
        bars.append((max(x[2] for x in seg), min(x[3] for x in seg), seg[-1][4]))
    bars.reverse()
    trs = []
    for k in range(1, len(bars)):
        h, l, _c = bars[k]
        pc = bars[k - 1][2]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / len(trs) if trs else None


def replay_one(plan: Dict[str, Any], rows: List[List[float]], times: List[float]) -> Dict[str, Any]:
    ct = float(plan["ct"])
    data_end = rows[-1][0] + 60.0 if rows else None
    out: Dict[str, Any] = {"mid": plan["mid"], "data_end": data_end}
    if not rows or data_end is None or data_end <= ct:
        out.update(status="NO_DATA", first=None, tie=False)
        return out
    p = {"direction": plan["direction"], "entry": plan["entry"], "sl": plan["sl"], "tp1": plan["tp1"], "tp2": plan.get("tp2"), "tp3": plan.get("tp3"),
         "confirmed_ts": ct, "valid_until_ts": float(plan["vt"])}
    i0 = max(0, bisect.bisect_left(times, ct) - 2)
    horizon = ct + MAX_TRACK + 3600
    i1 = bisect.bisect_right(times, horizon)
    cs = as_candles(rows[i0:i1])
    res = trk.simulate(p, cs, now_ts=data_end, tf_sec=60.0, live_tail=False)
    at = res.get("at") or {}
    first = None
    tie = False
    if "SL" in at or "TP1" in at:
        t_sl, t_tp = at.get("SL"), at.get("TP1")
        first = "SL" if t_sl is not None and (t_tp is None or t_sl <= t_tp) else "TP1"
        if t_sl is not None:
            long_ = str(plan["direction"]).upper() != "SHORT"
            tp1 = float(plan["tp1"])
            k = bisect.bisect_left(times, t_sl)
            if k < len(rows) and rows[k][0] == t_sl:
                touched = rows[k][2] >= tp1 if long_ else rows[k][3] <= tp1
                tie = bool(touched)
                if tie and t_tp is None:
                    first = "SL"   # TP1 торкнуто в ту ж хвилину, що й стоп: порядок невідомий
    out.update(status=res["status"], first=first, tie=tie, entry_at=at.get("ENTRY"), result_at=res.get("result_at"), reached=res.get("reached"),
               mfe=res.get("mfe_pct"), mae=res.get("mae_pct"), at=at)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", default="/tmp/ready_cache")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=0)
    a = ap.parse_args()
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    plans = json.load(open(a.plans))
    now = time.time()
    by_sym: Dict[str, List[Dict[str, Any]]] = {}
    for p in plans:
        by_sym.setdefault(p["symbol"], []).append(p)
    ct_min = min(float(p["ct"]) for p in plans)
    ct_max = max(float(p["ct"]) for p in plans)
    d_last = _day(min(now, ct_max + MAX_TRACK + 3600))
    # BTC для ринкового контексту: від доби перед першим READY (ознаки за 4 год до сигналу)
    btc_rows, btc_missing = load_symbol("BTCUSDT", _day(ct_min - 86400), d_last, cache, a.offline)
    btc_times = [r[0] for r in btc_rows]
    results: List[Dict[str, Any]] = []
    syms = sorted(by_sym)
    if a.max_symbols:
        syms = syms[: a.max_symbols]
    no_arch: Dict[str, List[str]] = {}
    for n, sym in enumerate(syms, 1):
        ps = by_sym[sym]
        c0 = min(float(p["ct"]) for p in ps)
        c1 = max(float(p["ct"]) for p in ps)
        rows, missing = load_symbol(sym, _day(c0 - 86400), _day(min(now, c1 + MAX_TRACK + 3600)), cache, a.offline)
        if missing:
            no_arch[sym] = missing
        times = [r[0] for r in rows]
        for p in ps:
            r = replay_one(p, rows, times)
            ct = float(p["ct"])
            r["btc_30m"] = ret_pct(btc_rows, btc_times, ct, 1800)
            r["btc_4h"] = ret_pct(btc_rows, btc_times, ct, 4 * 3600)
            r["coin_30m"] = ret_pct(rows, times, ct, 1800) if rows else None
            r["coin_4h"] = ret_pct(rows, times, ct, 4 * 3600) if rows else None
            atr = atr15(rows, times, ct) if rows else None
            e, sl = float(p["entry"]), float(p["sl"])
            r["sl_atr15"] = round(abs(e - sl) / atr, 2) if atr else None
            r["atr15_pct"] = round(atr / e * 100.0, 3) if atr else None
            results.append(r)
        if n % 25 == 0:
            print(f"[replay] {n}/{len(syms)} символів", flush=True)
    json.dump({"generated": datetime.now(timezone.utc).isoformat(), "plans": len(plans), "symbols": len(syms), "btc_missing_days": btc_missing, "no_archive": no_arch, "results": results},
              open(a.out, "w"), ensure_ascii=False, separators=(",", ":"))
    st: Dict[str, int] = {}
    for r in results:
        st[r["status"]] = st.get(r["status"], 0) + 1
    print("[replay] статуси:", dict(sorted(st.items())))
    print("[replay] символи без архіву (частково/повністю):", len(no_arch))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

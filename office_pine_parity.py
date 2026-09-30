"""Звірка Pine-еталону (office_pine_ref.py) з продакшн-детекторами office_ict_hunter.py.

Без TradingView CSV: обидві сторони беруть ОДНІ Й ТІ САМІ свічки.
  python3 scripts/compare_pine_python.py                 # синтетичні свічки (детерміновано)
  python3 scripts/compare_pine_python.py --csv f.csv     # свої свічки: ts,open,high,low,close,volume
Вихід: таблиця по патернах (скільки разів спрацювало в Pine / у Python / разом) + розбіжності рівнів і MO.
"""
import csv
import math
import random
from datetime import datetime, timedelta, timezone

import office_ict_hunter as hunter
import office_pine_ref as ref
import office_trade_steer as steer


def synthetic(n_days=45, seed=7):
    """15m свічки з режимами (тренд/флет/імпульси), об'єм корелює з рухом, є стрибки об'єму."""
    rnd = random.Random(seed)
    t = datetime(2026, 7, 1, tzinfo=timezone.utc)
    price, vol_level, drift, regime_left = 100.0, 1000.0, 0.0, 0
    out = []
    for _ in range(n_days * 96):
        if regime_left <= 0:
            regime_left = rnd.randint(60, 400)
            drift = rnd.choice([-0.0006, -0.0002, 0.0, 0.0, 0.0002, 0.0006])
            vol_level = rnd.choice([0.0015, 0.003, 0.006])
        regime_left -= 1
        ret = rnd.gauss(drift, vol_level)
        if rnd.random() < 0.02:
            ret *= rnd.uniform(3, 6)
        o = price
        c = max(0.5, o * (1 + ret))
        wick = abs(rnd.gauss(0, vol_level)) * o
        h = max(o, c) + wick * rnd.random()
        l = min(o, c) - wick * rnd.random()
        v = 1000 * math.exp(rnd.gauss(0, 0.4)) * (1 + 40 * abs(ret))
        if rnd.random() < 0.03:
            v *= rnd.uniform(2.5, 5)
        out.append({"ts": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
        price = c
        t += timedelta(minutes=15)
    return out


def load_csv(path):
    out = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            raw = r.get("ts") or r.get("time")
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00")) if not raw.isdigit() else datetime.fromtimestamp(int(raw) / (1000 if len(raw) > 10 else 1), tz=timezone.utc)
            out.append({"ts": ts.astimezone(timezone.utc), "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"]), "volume": float(r.get("volume") or 0)})
    return out


def prod_rows(bars, i, win):
    lo = max(0, i - win + 1)
    return [{"ts": b["ts"].isoformat(), "open": b["open"], "high": b["high"], "low": b["low"],
             "close": b["close"], "volume": b["volume"]} for b in bars[lo:i + 1]]


# (назва, Pine-ключ, сторона Python, детектор)
PAIRS = [
    ("SMS ↑ (long)", "sms_bull", "LONG", hunter.detect_sms),
    ("SMS ↓ (short)", "sms_bear", "SHORT", hunter.detect_sms),
    ("3 Drives розворот ↑", "drv_bull", "LONG", hunter.detect_three_drives),
    ("3 Drives розворот ↓", "drv_bear", "SHORT", hunter.detect_three_drives),
    ("3 Tap підтримка", "tap_lo", "LONG", hunter.detect_three_tap),
    ("3 Tap опір", "tap_hi", "SHORT", hunter.detect_three_tap),
    ("Inversion FVG ↑", "ifvg_bull", "LONG", hunter.detect_ifvg),
    ("Inversion FVG ↓", "ifvg_bear", "SHORT", hunter.detect_ifvg),
    ("AMD long (HIGH/CONF/MANIP)", "amd_long_any", "LONG", hunter.detect_amd_3),
    ("AMD short (HIGH/CONF/MANIP)", "amd_short_any", "SHORT", hunter.detect_amd_3),
    ("Turtle Soup long (Pine 5 барів)", "ts_long", "LONG", hunter.detect_turtle_soup),
    ("Turtle Soup short (Pine 5 барів)", "ts_short", "SHORT", hunter.detect_turtle_soup),
]


def compare(bars, win=100, warmup=250, step=1):
    pine = ref.run(bars)
    pine["amd_long_any"] = [bool(a or b or c) for a, b, c in zip(pine["amd_long_high"], pine["amd_long_conf"], pine["amd_long_manip"])]
    pine["amd_short_any"] = [bool(a or b or c) for a, b, c in zip(pine["amd_short_high"], pine["amd_short_conf"], pine["amd_short_manip"])]
    stats = {p[0]: {"pine": 0, "py": 0, "both": 0, "bars": 0} for p in PAIRS}
    for i in range(warmup, len(bars), step):
        rows = prod_rows(bars, i, win)
        cache = {}
        for name, key, side, fn in PAIRS:
            if fn not in cache:
                cache[fn] = fn(rows)
            res = cache[fn]
            py = bool(res.get("ok")) and res.get("side") == side
            pn = bool(pine[key][i])
            s = stats[name]
            s["bars"] += 1
            s["pine"] += pn
            s["py"] += py
            s["both"] += pn and py
    return pine, stats


def print_report(stats):
    print(f"{'патерн':36s} {'Pine':>6s} {'Python':>7s} {'разом':>6s} {'збіг/Pine':>10s} {'збіг/Py':>9s}")
    for name, s in stats.items():
        rec = f"{100 * s['both'] / s['pine']:.0f}%" if s["pine"] else "—"
        prec = f"{100 * s['both'] / s['py']:.0f}%" if s["py"] else "—"
        print(f"{name:36s} {s['pine']:6d} {s['py']:7d} {s['both']:6d} {rec:>10s} {prec:>9s}")


def compare_levels(bars, pine, warmup=250):
    """EMA, MO, щоденний EQ/OTE, азійський рендж — числові розбіжності."""
    rep = {}
    # EMA (на всій історії, як у продакшн ema_last)
    rows = [{"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "ts": b["ts"].isoformat()} for b in bars]
    for p in (55, 200):
        a, b = steer.ema_last(rows, p), pine[f"ema{p}"][-1]
        rep[f"EMA{p} (повна історія)"] = (a, b)
    # MO на останній добі
    last = bars[-1]["ts"]
    mo_py = steer.midnight_open_price(rows, asof=last.isoformat())
    rep["MO (Київ 07:00)"] = (mo_py, pine["mo_price"][-1])
    # денний EQ/OTE
    drows = []
    days = {}
    for b in bars:
        d = b["ts"].astimezone(timezone.utc).date()
        x = days.setdefault(d, {"open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]})
        x["high"], x["low"], x["close"] = max(x["high"], b["high"]), min(x["low"], b["low"]), b["close"]
    for d in sorted(days):
        drows.append({"ts": datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat(), **days[d]})
    lv = hunter.daily_eq_ote_hunter(drows)
    rep["щоденний EQ 0.786"] = (lv["eq"], pine["eq"][-1])
    rep["щоденний OTE 0.5"] = (lv["ote"], pine["ote"][-1])
    # азійський рендж останньої доби vs рендж по всьому вікну
    ar = hunter._asia_range(rows[-500:])
    rep["Asian high (Python: всі бари вікна / Pine: остання сесія)"] = (ar["high"], pine["asian_high"][-1])
    rep["Asian low  (Python: всі бари вікна / Pine: остання сесія)"] = (ar["low"], pine["asian_low"][-1])
    return rep


def report_lines(bars, win=100):
    pine, stats = compare(bars, win=win)
    lines = []
    for name, s in stats.items():
        lines.append(f"{name}: Pine={s['pine']} Python={s['py']} разом={s['both']}")
    return pine, stats, lines


def pine_samples(bars, pine, limit=12):
    """Останні спрацювання Pine-еталона (час Київ, відкриття бару) — щоб власниця вручну звірила з мітками на графіку TradingView без CSV."""
    keys = ("sms_bull", "sms_bear", "drv_bull", "drv_bear", "tap_lo", "tap_hi", "ifvg_bull", "ifvg_bear", "amd_long_high", "amd_short_high")
    ev = []
    for i in range(1, len(bars)):
        for k in keys:
            if pine[k][i] and not pine[k][i - 1]:
                ev.append((bars[i]["ts"], k))
    ev.sort()
    return [[t.astimezone(ref.KYIV).strftime("%Y-%m-%d %H:%M"), k] for t, k in ev[-limit:]]


VERSION = "pine-parity-2026-09-30"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "ENAUSDT")


def run_once(db, printer=print, getter=None, days=21, step=2):
    """Одноразово на production: реальні 15m свічки з архіву Binance → звірка Pine-еталон ↔ продакшн. Результат — у БД (LAUNCH_DIAG, task=pine_parity)."""
    import json
    import time
    from datetime import timedelta

    import office_launch_once as lo
    import office_replay as rp
    from office_bridge import _fetchall, log_event

    def _done():
        try:
            rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT 300", ("LAUNCH_DIAG",))
        except Exception:  # noqa: BLE001
            return False
        for r in rows or []:
            try:
                p = json.loads(r[0]) if isinstance(r[0], str) else dict(r[0])
            except (TypeError, ValueError):
                continue
            if p.get("version") == VERSION and p.get("task") == "pine_parity_done":
                return True
        return False

    if _done():
        return False
    _ = lo  # лише для узгодженості подій
    end = datetime.now(timezone.utc) - timedelta(days=2)
    start = end - timedelta(days=days)
    for sym in SYMBOLS:
        try:
            data = rp.from_vision(sym, start, end, getter=getter)
            rows = [{"ts": datetime.fromisoformat(r["ts"].replace("Z", "+00:00")), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
                    for r in data["15m"]]
            if len(rows) < 500:
                log_event(db, "LAUNCH_DIAG", {"version": VERSION, "task": "pine_parity", "symbol": sym, "error": f"мало свічок: {len(rows)}", "missing_days": data["missing_days"]})
                continue
            pine, stats = compare(rows, step=step)
            lv = {k: [py, pn] for k, (py, pn) in compare_levels(rows, pine).items()}
            samples = pine_samples(rows, pine)
            log_event(db, "LAUNCH_DIAG", {"version": VERSION, "task": "pine_parity", "symbol": sym, "bars": len(rows), "missing_days": data["missing_days"], "patterns": stats, "levels": lv, "samples_pine": samples})
            printer(f"[pine-parity] {sym}: {len(rows)} барів, записано в БД")
        except Exception as exc:  # noqa: BLE001
            log_event(db, "LAUNCH_DIAG", {"version": VERSION, "task": "pine_parity", "symbol": sym, "error": f"{type(exc).__name__}: {exc}"})
    log_event(db, "LAUNCH_DIAG", {"version": VERSION, "task": "pine_parity_done", "at": time.time()})
    return True

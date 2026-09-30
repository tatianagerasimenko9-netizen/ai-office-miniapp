"""Еталонний порт ICT SMC HUNTER v9.9 SYNC (Pine) на Python — БУКВАЛЬНО, бар за баром.

Це НЕ частина рішень Лева. Це «лінійка»: кожен рядок тут відповідає рядку повного Pine-коду
(який власниця передала в чаті). Мета — порівнювати з продакшн-детекторами (`office_ict_hunter.py`)
на одних і тих самих свічках без TradingView CSV.

Семантика Pine, яку відтворено:
- history operator x[k] = значення k барів тому (на перших барах — None = na);
- var-змінні зберігають стан між барами;
- ta.atr / ta.rsi = RMA (Wilder), ta.rma стартує з SMA перших n значень;
- ta.ema стартує з першого значення джерела;
- ta.pivothigh/low(L,R) підтверджується через R барів, значення = півот на барі i-R;
- ta.crossover(a,b) = a>b і a[1]<=b[1]; якщо що-небудь na — false;
- сесія Київ (Europe/Kiev): бар належить сесії [start, end) за часом ВІДКРИТТЯ бару;
- денні рівні (D[1]) — попередня доба за UTC.
НЕ ПЕРЕВІРЯЮТЬСЯ без TradingView (див. docs/pine-python-parity.md): дрібні деталі рушія TV
(рівність цін у півотах, початок історії EMA, точне округлення на межах сесій).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
Num = Optional[float]


def _na(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def at(s: List[Any], i: int, k: int = 0) -> Any:
    j = i - k
    return s[j] if 0 <= j < len(s) else None


# ── ta.* ─────────────────────────────────────────────────────────
def sma(src: List[Num], n: int) -> List[Num]:
    out: List[Num] = [None] * len(src)
    for i in range(n - 1, len(src)):
        w = src[i - n + 1 : i + 1]
        if any(_na(x) for x in w):
            continue
        out[i] = sum(w) / n  # type: ignore[arg-type]
    return out


def rma(src: List[Num], n: int) -> List[Num]:
    out: List[Num] = [None] * len(src)
    for i in range(len(src)):
        if _na(src[i]):
            continue
        prev = out[i - 1] if i > 0 else None
        if _na(prev):
            if i >= n - 1 and all(not _na(x) for x in src[i - n + 1 : i + 1]):
                out[i] = sum(src[i - n + 1 : i + 1]) / n  # type: ignore[arg-type]
        else:
            out[i] = (src[i] + (n - 1) * prev) / n  # type: ignore[operator]
    return out


def ema(src: List[Num], n: int) -> List[Num]:
    k = 2.0 / (n + 1.0)
    out: List[Num] = [None] * len(src)
    for i, x in enumerate(src):
        if _na(x):
            continue
        prev = out[i - 1] if i > 0 else None
        out[i] = x if _na(prev) else k * x + (1 - k) * prev  # type: ignore[operator]
    return out


def true_range(h: List[float], l: List[float], c: List[float]) -> List[float]:
    out = []
    for i in range(len(h)):
        if i == 0:
            out.append(h[i] - l[i])
        else:
            out.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return out


def atr(h, l, c, n: int = 14) -> List[Num]:
    return rma(true_range(h, l, c), n)


def rsi(c: List[float], n: int = 14) -> List[Num]:
    up: List[Num] = [None] + [max(c[i] - c[i - 1], 0.0) for i in range(1, len(c))]
    dn: List[Num] = [None] + [max(c[i - 1] - c[i], 0.0) for i in range(1, len(c))]
    ru, rd = rma(up, n), rma(dn, n)
    out: List[Num] = []
    for u, d in zip(ru, rd):
        if _na(u) or _na(d):
            out.append(None)
        elif d == 0:
            out.append(100.0)
        else:
            out.append(100.0 - 100.0 / (1.0 + u / d))
    return out


def highest(src: List[Num], n: int, i: int) -> Num:
    if i - n + 1 < 0:
        return None
    w = src[i - n + 1 : i + 1]
    return None if any(_na(x) for x in w) else max(w)  # type: ignore[type-var]


def lowest(src: List[Num], n: int, i: int) -> Num:
    if i - n + 1 < 0:
        return None
    w = src[i - n + 1 : i + 1]
    return None if any(_na(x) for x in w) else min(w)  # type: ignore[type-var]


def pivot_high(h: List[float], L: int, R: int, i: int) -> Num:
    j = i - R
    if j - L < 0:
        return None
    w = h[j - L : j + R + 1]
    return h[j] if h[j] >= max(w) else None


def pivot_low(l: List[float], L: int, R: int, i: int) -> Num:
    j = i - R
    if j - L < 0:
        return None
    w = l[j - L : j + R + 1]
    return l[j] if l[j] <= min(w) else None


def crossover(a: Num, b: Num, a1: Num, b1: Num) -> bool:
    if any(_na(x) for x in (a, b, a1, b1)):
        return False
    return a > b and a1 <= b1  # type: ignore[operator]


def crossunder(a: Num, b: Num, a1: Num, b1: Num) -> bool:
    if any(_na(x) for x in (a, b, a1, b1)):
        return False
    return a < b and a1 >= b1  # type: ignore[operator]


# ── основний розрахунок ─────────────────────────────────────────
def kyiv_minutes(ts: datetime) -> int:
    k = ts.astimezone(KYIV)
    return k.hour * 60 + k.minute


def in_session(ts: datetime, start_hm: int, end_hm: int) -> bool:
    m = kyiv_minutes(ts)
    return start_hm <= m < end_hm


def run(bars: List[Dict[str, Any]], *, tap_window: int = 25, amd_acc_relax: float = 1.0) -> Dict[str, List[Any]]:
    """bars: [{ts: datetime(UTC), open, high, low, close, volume}] від найстарішого."""
    n = len(bars)
    o = [float(b["open"]) for b in bars]
    h = [float(b["high"]) for b in bars]
    l = [float(b["low"]) for b in bars]
    c = [float(b["close"]) for b in bars]
    v = [float(b.get("volume") or 0.0) for b in bars]
    ts = [b["ts"] for b in bars]

    atr14 = atr(h, l, c, 14)
    rsi14 = rsi(c, 14)
    ema21, ema55, ema200 = ema(c, 21), ema(c, 55), ema(c, 200)
    vol_sma = sma(v, 20)
    rng = [h[i] - l[i] for i in range(n)]
    range_avg20 = sma(rng, 20)

    keys = [
        "sc_bull", "sc_bear", "sms_bull", "sms_bear", "drv_bull", "drv_bear",
        "tap_lo", "tap_hi", "ifvg_bull", "ifvg_bear",
        "amd_long_high", "amd_long_conf", "amd_long_manip",
        "amd_short_high", "amd_short_conf", "amd_short_manip",
        "ts_long", "ts_short", "sfp_bull", "sfp_bear",
        "asian_high", "asian_low", "mo_price", "eq", "ote", "d_bull",
        "sync_sc_lo", "sync_sc_hi", "last_sc_dir",
    ]
    out: Dict[str, List[Any]] = {k: [None] * n for k in keys}
    out.update({"atr14": atr14, "rsi14": rsi14, "ema21": ema21, "ema55": ema55, "ema200": ema200, "vol_sma": vol_sma})

    # var-стан
    asian_high: Num = None
    asian_low: Num = None
    in_asia_prev = False
    mo_price: Num = None
    mo_in_prev = False
    td_ph = [None, None, None]
    td_pl = [None, None, None]
    ifvg_bull_top = ifvg_bull_bot = ifvg_bear_top = ifvg_bear_bot = None
    sync_lo: Num = None
    sync_hi: Num = None
    last_dir = 0

    # денні бари за UTC для D[1]
    day_key = [t.astimezone(timezone.utc).date() for t in ts]
    daily: Dict[Any, Dict[str, float]] = {}
    order: List[Any] = []
    for i in range(n):
        d = day_key[i]
        if d not in daily:
            daily[d] = {"open": o[i], "high": h[i], "low": l[i], "close": c[i]}
            order.append(d)
        else:
            daily[d]["high"] = max(daily[d]["high"], h[i])
            daily[d]["low"] = min(daily[d]["low"], l[i])
            daily[d]["close"] = c[i]
    prev_day = {order[k]: order[k - 1] for k in range(1, len(order))}

    for i in range(n):
        a = atr14[i]
        close, open_, high, low, vol = c[i], o[i], h[i], l[i], v[i]

        # сильна свічка + зона
        vs = vol_sma[i]
        strong_vol = vs is not None and vol > vs * 2.0
        sc_rng = high - low
        sc_bull = bool(strong_vol and close > open_ and a is not None and sc_rng > a * 1.2)
        sc_bear = bool(strong_vol and close < open_ and a is not None and sc_rng > a * 1.2)
        if sc_bull:
            last_dir, sync_lo, sync_hi = 1, low, high
        if sc_bear:
            last_dir, sync_lo, sync_hi = -1, low, high
        out["sc_bull"][i], out["sc_bear"][i] = sc_bull, sc_bear
        out["sync_sc_lo"][i], out["sync_sc_hi"][i], out["last_sc_dir"][i] = sync_lo, sync_hi, last_dir

        # сесії
        in_asia = in_session(ts[i], 3 * 60, 7 * 60)
        if in_asia and not in_asia_prev:
            asian_high, asian_low = high, low
        elif in_asia:
            asian_high, asian_low = max(asian_high, high), min(asian_low, low)  # type: ignore[type-var]
        in_asia_prev = in_asia
        out["asian_high"][i], out["asian_low"][i] = asian_high, asian_low

        mo_in = in_session(ts[i], 7 * 60, 7 * 60 + 5)
        if mo_in and not mo_in_prev:
            mo_price = open_
        mo_in_prev = mo_in
        out["mo_price"][i] = mo_price

        # денний EQ/OTE (у Pine eq=0.786, ote=0.5)
        pd = prev_day.get(day_key[i])
        if pd is not None:
            dd = daily[pd]
            d_rng = dd["high"] - dd["low"]
            d_bull = dd["close"] > dd["open"]
            out["d_bull"][i] = d_bull
            out["eq"][i] = dd["high"] - d_rng * 0.786 if d_bull else dd["low"] + d_rng * 0.786
            out["ote"][i] = dd["high"] - d_rng * 0.5 if d_bull else dd["low"] + d_rng * 0.5

        # SMS
        hi20, lo20 = highest(h, 20, i), lowest(l, 20, i)
        rng20 = (hi20 - lo20) if hi20 is not None and lo20 is not None else None
        sms_expanded = bool(rng20 is not None and a is not None and rng20 > a * 3.0)
        hh5 = highest(h, 5, i)
        hh20_5 = highest(h, 20, i - 5) if i - 5 >= 0 else None
        sms_lh_fail = bool(hh5 is not None and hh20_5 is not None and hh5 < hh20_5 * 0.997)
        lo10_1 = lowest(l, 10, i - 1) if i >= 1 else None
        sms_break_lo = bool(lo10_1 is not None and close < lo10_1)
        lo3 = lowest(l, 3, i)
        lo8_1 = lowest(l, 8, i - 1) if i >= 1 else None
        liq_dn = bool((asian_low is not None and lo3 is not None and lo3 < asian_low) or (lo8_1 is not None and low <= lo8_1))
        out["sms_bear"][i] = bool(sms_expanded and sms_lh_fail and sms_break_lo and close < open_ and liq_dn)

        ll5 = lowest(l, 5, i)
        ll20_5 = lowest(l, 20, i - 5) if i - 5 >= 0 else None
        sms_hl_fail = bool(ll5 is not None and ll20_5 is not None and ll5 > ll20_5 * 1.003)
        hi10_1 = highest(h, 10, i - 1) if i >= 1 else None
        sms_break_hi = bool(hi10_1 is not None and close > hi10_1)
        hi3 = highest(h, 3, i)
        hi8_1 = highest(h, 8, i - 1) if i >= 1 else None
        liq_up = bool((asian_high is not None and hi3 is not None and hi3 > asian_high) or (hi8_1 is not None and high >= hi8_1))
        out["sms_bull"][i] = bool(sms_expanded and sms_hl_fail and sms_break_hi and close > open_ and liq_up)

        # Three Drives
        ph, pl = pivot_high(h, 3, 3, i), pivot_low(l, 3, 3, i)
        if ph is not None:
            td_ph = [td_ph[1], td_ph[2], ph]
        if pl is not None:
            td_pl = [td_pl[1], td_pl[2], pl]
        up = all(x is not None for x in td_ph) and td_ph[0] < td_ph[1] < td_ph[2]  # type: ignore[operator]
        dn = all(x is not None for x in td_pl) and td_pl[0] > td_pl[1] > td_pl[2]  # type: ignore[operator]
        out["drv_bull"][i] = bool(dn and close > td_pl[1] and close > open_)  # type: ignore[operator]
        out["drv_bear"][i] = bool(up and close < td_ph[1] and close < open_)  # type: ignore[operator]

        # Three Tap
        if a is not None and i - tap_window + 1 >= 0:
            band = a * 0.15
            ref_hi = max(h[i - tap_window + 1 : i + 1])
            ref_lo = min(l[i - tap_window + 1 : i + 1])
            n_hi = sum(1 for k in range(tap_window) if h[i - k] >= ref_hi - band)
            n_lo = sum(1 for k in range(tap_window) if l[i - k] <= ref_lo + band)
            out["tap_hi"][i] = bool(n_hi >= 3 and close < ref_hi and ref_hi > ref_lo)
            out["tap_lo"][i] = bool(n_lo >= 3 and close > ref_lo and ref_hi > ref_lo)
        else:
            out["tap_hi"][i] = out["tap_lo"][i] = False

        # FVG + Inversion FVG (оновлення стану ДО перетину, як у Pine)
        if i >= 2 and a is not None:
            if low > h[i - 2] and (low - h[i - 2]) > a * 0.25:
                ifvg_bull_top, ifvg_bull_bot = low, h[i - 2]
            if high < l[i - 2] and (l[i - 2] - high) > a * 0.25:
                ifvg_bear_top, ifvg_bear_bot = l[i - 2], high
        c1 = c[i - 1] if i >= 1 else None
        co = crossover(close, ifvg_bear_top, c1, ifvg_bear_top)
        cu = crossunder(close, ifvg_bull_bot, c1, ifvg_bull_bot)
        out["ifvg_bull"][i] = bool(co and close > open_)
        out["ifvg_bear"][i] = bool(cu and close < open_)

        # AMD (3 свічки + підтвердження)
        if i >= 3:
            ra = range_avg20[i]
            acc_rng = (ra if ra is not None else (high - low)) * 0.6 * amd_acc_relax
            acc_ok = (h[i - 3] - l[i - 3]) < acc_rng
            c3_h, c3_l = h[i - 3], l[i - 3]
            c2_h, c2_l, c2_o, c2_c = h[i - 2], l[i - 2], o[i - 2], c[i - 2]
            c1_o, c1_c = o[i - 1], c[i - 1]
            l_sweep, l_reject = c2_l < c3_l * 0.999, c2_c > c2_o
            l_engulf = c1_c > c2_h and c1_o < c2_c
            l_high = l_engulf and c1_c > c3_h
            l_conf = close > c1_c
            hi_l = acc_ok and l_sweep and l_reject and l_high and l_conf
            cf_l = (not hi_l) and acc_ok and l_sweep and l_reject and l_engulf and l_conf
            mn_l = (not hi_l) and (not cf_l) and acc_ok and l_sweep and l_reject
            s_sweep, s_reject = c2_h > c3_h * 1.001, c2_c < c2_o
            s_engulf = c1_c < c2_l and c1_o > c2_c
            s_high = s_engulf and c1_c < c3_l
            s_conf = close < c1_c
            hi_s = acc_ok and s_sweep and s_reject and s_high and s_conf
            cf_s = (not hi_s) and acc_ok and s_sweep and s_reject and s_engulf and s_conf
            mn_s = (not hi_s) and (not cf_s) and acc_ok and s_sweep and s_reject
            out["amd_long_high"][i], out["amd_long_conf"][i], out["amd_long_manip"][i] = bool(hi_l), bool(cf_l), bool(mn_l)
            out["amd_short_high"][i], out["amd_short_conf"][i], out["amd_short_manip"][i] = bool(hi_s), bool(cf_s), bool(mn_s)
        else:
            for k in ("amd_long_high", "amd_long_conf", "amd_long_manip", "amd_short_high", "amd_short_conf", "amd_short_manip"):
                out[k][i] = False

        # Turtle Soup / SFP (5 барів, [1])
        key_low5 = lowest(l, 5, i - 1) if i >= 1 else None
        key_high5 = highest(h, 5, i - 1) if i >= 1 else None
        out["ts_long"][i] = bool(key_low5 is not None and low < key_low5 and close > key_low5)
        out["ts_short"][i] = bool(key_high5 is not None and high > key_high5 and close < key_high5)
        o1 = o[i - 1] if i >= 1 else None
        out["sfp_bull"][i] = bool(key_low5 is not None and o1 is not None and low < key_low5 and close > key_low5 and close > o1)
        out["sfp_bear"][i] = bool(key_high5 is not None and o1 is not None and high > key_high5 and close < key_high5 and close < o1)

    return out

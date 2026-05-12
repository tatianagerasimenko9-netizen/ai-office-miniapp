from __future__ import annotations

import json
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen


JSONLike = Union[Dict[str, Any], List[Any]]


def _http_get_json(url: str, params: Dict[str, Any]) -> JSONLike:
    qs = urlencode(params)
    full_url = f"{url}?{qs}" if qs else url
    req = Request(
        full_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urlopen(req, timeout=12) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def fetch_candles(symbol: str, tf: str, limit: int = 3) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetch futures candles from Binance for any USDT symbol.
    Returns list of candles or {} on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        data = _http_get_json(
            "https://fapi.binance.com/fapi/v1/klines",
            {"symbol": sym, "interval": tf, "limit": int(limit)},
        )
        out: List[Dict[str, Any]] = []
        if not isinstance(data, list):
            return {}
        for row in data:
            if not isinstance(row, list) or len(row) < 6:
                continue
            ts_ms = int(row[0])
            ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat()
            out.append(
                {
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "ts": ts,
                }
            )
        return out
    except Exception:
        return {}


def fetch_session_levels(symbol: str) -> Dict[str, Any]:
    """
    High/low сесій Asia / London / NY за останні ~24 год (15m, UTC),
    та PDH / PDL / PDC попереднього дня (1d).

    Вікна UTC:
    Asia:   00:00 – 08:00  (година h: 0 <= h < 8)
    London: 08:00 – 16:00  (8 <= h < 16)
    NY:     13:00 – 21:00  (13 <= h < 21; перетин з London 13–16 — свічка враховується в обох)
    """
    try:
        now = datetime.now(timezone.utc)
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"

        candles = fetch_candles(sym, "15m", 96)
        if not isinstance(candles, list) or not candles:
            return {}

        sessions = {
            "asia": (0, 8),
            "london": (8, 16),
            "ny": (13, 21),
        }

        def _candle_hour_utc(c: Dict[str, Any]) -> Optional[int]:
            ts = c.get("ts")
            if not isinstance(ts, str) or not ts.strip():
                return None
            try:
                dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.hour)
            except Exception:
                return None

        result: Dict[str, Any] = {
            "symbol": sym,
            "asof_utc": now.isoformat(),
            "sessions_utc": {
                "asia": "00:00-08:00",
                "london": "08:00-16:00",
                "ny": "13:00-21:00",
            },
        }

        for sess_name, (h_start, h_end) in sessions.items():
            highs: List[float] = []
            lows: List[float] = []
            for c in candles:
                if not isinstance(c, dict):
                    continue
                hour = _candle_hour_utc(c)
                if hour is None:
                    continue
                if h_start <= hour < h_end:
                    try:
                        highs.append(float(c.get("high") or 0.0))
                        lows.append(float(c.get("low") or 0.0))
                    except (TypeError, ValueError):
                        continue
            if highs and lows:
                result[f"{sess_name}_high"] = max(highs)
                result[f"{sess_name}_low"] = min(lows)

        daily = fetch_candles(sym, "1d", 3)
        if isinstance(daily, list) and len(daily) >= 2:
            prev = daily[-2]
            if isinstance(prev, dict):
                result["pdh"] = float(prev.get("high") or 0.0)
                result["pdl"] = float(prev.get("low") or 0.0)
                result["pdc"] = float(prev.get("close") or 0.0)

        return result
    except Exception as e:
        print(f"[session] error {symbol}: {e}")
        return {}


def fetch_liquidity_sweep(symbol: str, tf: str = "1h") -> Dict[str, Any]:
    """
    Грубий ICT-подібний sweep ліквідності на останніх свічках:

    - BSL (buy-side liquidity / стопи над хаями): wick пробив max(high[-3], high[-2]),
      close повернувся нижче цього рівня → ймовірний bearish reaction.
    - SSL (sell-side liquidity під лоями): wick нижче min(low[-3], low[-2]),
      close вище цього рівня → ймовірний bullish reaction.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        tf_s = str(tf or "1h").strip().lower() or "1h"

        candles = fetch_candles(sym, tf_s, 10)
        if not isinstance(candles, list) or len(candles) < 3:
            return {}

        c1 = candles[-3]
        c2 = candles[-2]
        c3 = candles[-1]
        if not all(isinstance(c, dict) for c in (c1, c2, c3)):
            return {}

        h1 = float(c1.get("high") or 0.0)
        h2 = float(c2.get("high") or 0.0)
        l1 = float(c1.get("low") or 0.0)
        l2 = float(c2.get("low") or 0.0)
        c3_high = float(c3.get("high") or 0.0)
        c3_low = float(c3.get("low") or 0.0)
        c3_close = float(c3.get("close") or 0.0)
        _ = float(c3.get("open") or 0.0)  # зарезервовано для розширення (тіло/дісплейсмент)

        result: Dict[str, Any] = {
            "symbol": sym,
            "tf": tf_s,
            "bsl_sweep": False,
            "ssl_sweep": False,
            "sweep_level": None,
            "description": "",
        }

        prev_high = max(h1, h2)
        if prev_high > 0 and c3_high > prev_high and c3_close < prev_high:
            result["bsl_sweep"] = True
            result["sweep_level"] = prev_high
            result["description"] = (
                f"BSL sweep {prev_high:.4f} — пробила хай і повернулась. Можливий SHORT сетап."
            )

        prev_low = min(l1, l2)
        if prev_low > 0 and c3_low < prev_low and c3_close > prev_low:
            result["ssl_sweep"] = True
            result["sweep_level"] = prev_low
            ssl_desc = (
                f"SSL sweep {prev_low:.4f} — пробила лоу і повернулась. Можливий LONG сетап."
            )
            if result["bsl_sweep"]:
                result["description"] = (str(result.get("description") or "").strip() + " | " + ssl_desc).strip(
                    " |"
                )
            else:
                result["description"] = ssl_desc

        return result
    except Exception as e:
        print(f"[sweep] error {symbol}: {e}")
        return {}


def fetch_pd_array(symbol: str, tf: str = "4h") -> Dict[str, Any]:
    """
    Premium/Discount Array.
    Визначає де знаходиться ціна відносно останнього значного імпульсу
    (найбільший діапазон high-low серед попередніх свічок, без останньої):
    - Premium (>50% від імпульсу, вище EQ) — зона шорту
    - Discount (<50%, нижче EQ) — зона лонгу
    - Equilibrium (~50%, біля EQ) — нейтральна зона
    OTE (61.8–78.6% Fib) від того ж імпульсу.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        tf_s = str(tf or "4h").strip().lower() or "4h"

        candles = fetch_candles(sym, tf_s, 20)
        if not isinstance(candles, list) or len(candles) < 5:
            return {}

        max_range = 0.0
        impulse_high = 0.0
        impulse_low = 0.0

        for i in range(len(candles) - 1):
            c = candles[i]
            if not isinstance(c, dict):
                continue
            h = float(c.get("high") or 0.0)
            l = float(c.get("low") or 0.0)
            rng = h - l
            if rng > max_range:
                max_range = rng
                impulse_high = h
                impulse_low = l

        if impulse_high <= 0 or impulse_low <= 0 or impulse_high <= impulse_low:
            return {}

        last = candles[-1]
        if not isinstance(last, dict):
            return {}
        current_price = float(last.get("close") or 0.0)
        if current_price <= 0:
            return {}

        eq = (impulse_high + impulse_low) / 2.0
        span = impulse_high - impulse_low
        ote_low = impulse_low + span * 0.618
        ote_high = impulse_low + span * 0.786

        # тонка смуга навколо 50% — уникнути «фальшивого Discount» через float noise
        eps = max(span * 1e-6, span / 10_000.0, current_price * 1e-10)
        if current_price > eq + eps:
            zone = "PREMIUM"
            bias = "SHORT"
            description = (
                f"Ціна в Premium зоні ({current_price:.4f} > EQ {eq:.4f}). "
                f"Шукаємо SHORT від рівнів опору."
            )
        elif current_price < eq - eps:
            zone = "DISCOUNT"
            bias = "LONG"
            description = (
                f"Ціна в Discount зоні ({current_price:.4f} < EQ {eq:.4f}). "
                f"Шукаємо LONG від рівнів підтримки."
            )
        else:
            zone = "EQUILIBRIUM"
            bias = "NEUTRAL"
            description = (
                f"Ціна біля Equilibrium ({current_price:.4f} ≈ EQ {eq:.4f}). "
                f"Нейтрально — чекаємо дислокації в Premium/Discount."
            )

        return {
            "symbol": sym,
            "tf": tf_s,
            "current_price": current_price,
            "impulse_high": impulse_high,
            "impulse_low": impulse_low,
            "equilibrium": round(eq, 4),
            "ote_low": round(ote_low, 4),
            "ote_high": round(ote_high, 4),
            "zone": zone,
            "bias": bias,
            "description": description,
        }
    except Exception as e:
        print(f"[pd_array] error {symbol}: {e}")
        return {}


def fetch_market_structure(symbol: str, tf: str = "1h") -> Dict[str, Any]:
    """
    Ринкова структура на swing highs/lows (спрощено під ICT):

    - BOS (Break of Structure): у бичій структурі close вище попереднього swing high;
      у ведмежій — close нижче попереднього swing low → продовження тренду.
    - HH/HL або LH/LL: структура активна, без пробою останнього значного рівня.
    - CHOCH (Change of Character): коли немає чіткої HH/HL чи LH/LL — перехідний стан.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        tf_s = str(tf or "1h").strip().lower() or "1h"

        candles = fetch_candles(sym, tf_s, 20)
        if not isinstance(candles, list) or len(candles) < 6:
            return {}

        closes: List[float] = []
        highs: List[float] = []
        lows: List[float] = []
        for c in candles:
            if not isinstance(c, dict):
                return {}
            closes.append(float(c.get("close") or 0.0))
            highs.append(float(c.get("high") or 0.0))
            lows.append(float(c.get("low") or 0.0))

        swing_highs: List[tuple[int, float]] = []
        swing_lows: List[tuple[int, float]] = []

        for i in range(2, len(candles) - 2):
            if (
                highs[i] > highs[i - 1]
                and highs[i] > highs[i - 2]
                and highs[i] > highs[i + 1]
                and highs[i] > highs[i + 2]
            ):
                swing_highs.append((i, highs[i]))
            if (
                lows[i] < lows[i - 1]
                and lows[i] < lows[i - 2]
                and lows[i] < lows[i + 1]
                and lows[i] < lows[i + 2]
            ):
                swing_lows.append((i, lows[i]))

        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {
                "symbol": sym,
                "tf": tf_s,
                "structure": "UNCLEAR",
                "description": "Недостатньо даних",
            }

        sh1 = swing_highs[-2][1]
        sh2 = swing_highs[-1][1]
        sl1 = swing_lows[-2][1]
        sl2 = swing_lows[-1][1]
        current = closes[-1]

        bullish_structure = sh2 > sh1 and sl2 > sl1
        bearish_structure = sh2 < sh1 and sl2 < sl1

        result: Dict[str, Any] = {
            "symbol": sym,
            "tf": tf_s,
            "last_sh": sh2,
            "last_sl": sl2,
            "prev_sh": sh1,
            "prev_sl": sl1,
            "current_price": current,
        }

        if bullish_structure:
            result["structure"] = "BULLISH"
            result["trend"] = "UP"
            if current > sh1:
                result["event"] = "BOS_BULLISH"
                result["description"] = (
                    f"BOS вгору — пробило SH {sh1:.4f}. "
                    f"Тренд продовжується вгору. "
                    f"Шукаємо LONG від підтримок."
                )
            else:
                result["event"] = "HH_HL"
                result["description"] = (
                    f"Higher High + Higher Low — бичача структура активна."
                )
        elif bearish_structure:
            result["structure"] = "BEARISH"
            result["trend"] = "DOWN"
            if current < sl1:
                result["event"] = "BOS_BEARISH"
                result["description"] = (
                    f"BOS вниз — пробило SL {sl1:.4f}. "
                    f"Тренд продовжується вниз. "
                    f"Шукаємо SHORT від опорів."
                )
            else:
                result["event"] = "LH_LL"
                result["description"] = (
                    f"Lower High + Lower Low — ведмежа структура активна."
                )
        else:
            result["structure"] = "TRANSITION"
            result["event"] = "CHOCH"
            result["description"] = (
                f"CHOCH — зміна характеру ринку. "
                f"Можливий розворот тренду. "
                f"Чекаємо підтвердження."
            )

        return result
    except Exception as e:
        print(f"[structure] error {symbol}: {e}")
        return {}


def fetch_btc_candles(tf: str, limit: int = 3) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Backward-compatible wrapper for BTC candles.
    """
    return fetch_candles("BTCUSDT", tf, limit)


def fetch_open_interest(symbol: str) -> Dict[str, Any]:
    """
    Fetch current OI and recent 1h OI history.
    Returns {} on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}

        now_data = _http_get_json(
            "https://fapi.binance.com/fapi/v1/openInterest",
            {"symbol": sym},
        )
        hist_data = _http_get_json(
            "https://fapi.binance.com/futures/data/openInterestHist",
            {"symbol": sym, "period": "1h", "limit": 4},
        )

        oi_contracts = float((now_data or {}).get("openInterest") or 0.0) if isinstance(now_data, dict) else 0.0
        liq = fetch_liquidations_proxy(sym)
        current_price = float((liq or {}).get("current_price") or 0.0) if isinstance(liq, dict) else 0.0
        if current_price > 0:
            oi_now = oi_contracts * current_price
            oi_unit = "USDT"
            oi_note = ""
        else:
            oi_now = oi_contracts
            oi_unit = "contracts"
            oi_note = "(контракти, не USDT)"
        hist: List[Dict[str, Any]] = []
        if isinstance(hist_data, list):
            for item in hist_data:
                if not isinstance(item, dict):
                    continue
                oi_val = float(item.get("sumOpenInterestValue") or item.get("sumOpenInterest") or 0.0)
                ts_ms = int(item.get("timestamp") or 0)
                ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat() if ts_ms > 0 else ""
                hist.append({"oi": oi_val, "timestamp": ts})

        return {
            "oi": oi_now,
            "oi_contracts": oi_contracts,
            "oi_unit": oi_unit,
            "oi_note": oi_note,
            "symbol": sym,
            "history": hist,
        }
    except Exception:
        return {}


def fetch_liquidations_proxy(symbol: str) -> Dict[str, Any]:
    """
    Proxy liquidation zones from 24h high/low and current price.
    Returns {} on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        data = _http_get_json(
            "https://fapi.binance.com/fapi/v1/ticker/24hr",
            {"symbol": sym},
        )
        if not isinstance(data, dict):
            return {}
        high_24h = float(data.get("highPrice") or 0.0)
        low_24h = float(data.get("lowPrice") or 0.0)
        current_price = float(data.get("lastPrice") or 0.0)
        return {
            "liq_zone_above": high_24h * 1.002,
            "liq_zone_below": low_24h * 0.998,
            "current_price": current_price,
        }
    except Exception:
        return {}


def fetch_funding_rate(symbol: str) -> Dict[str, Any]:
    """
    Fetch current funding/mark/index data from Binance premiumIndex.
    Returns {} on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        data = _http_get_json(
            "https://fapi.binance.com/fapi/v1/premiumIndex",
            {"symbol": sym},
        )
        if not isinstance(data, dict):
            return {}
        fr = data.get("lastFundingRate")
        funding_rate_pct = None
        try:
            if fr is not None:
                funding_rate_pct = float(fr) * 100.0
        except Exception:
            funding_rate_pct = None
        return {
            "symbol": sym,
            "funding_rate_pct": funding_rate_pct,
            "mark_price": float(data.get("markPrice") or 0.0),
            "index_price": float(data.get("indexPrice") or 0.0),
        }
    except Exception:
        return {}


def fetch_atr_context(symbol: str) -> Dict[str, Any]:
    """
    ATR context on daily candles (15 bars, Wilder-style TR average over 14).
    Returns {} on failure.
    """
    try:
        candles = fetch_candles(symbol, "1d", 15)
        if not isinstance(candles, list) or len(candles) < 15:
            return {}
        trs: List[float] = []
        for i in range(1, len(candles)):
            cur = candles[i]
            prev = candles[i - 1]
            h = float(cur.get("high") or 0.0)
            l = float(cur.get("low") or 0.0)
            pc = float(prev.get("close") or 0.0)
            tr = max(h - l, abs(h - pc), abs(l - pc))
            trs.append(tr)
        if len(trs) < 14:
            return {}
        atr = sum(trs[-14:]) / 14.0
        today = candles[-1]
        day_high = float(today.get("high") or 0.0)
        day_low = float(today.get("low") or 0.0)
        day_range = day_high - day_low
        day_used_pct = (day_range / atr * 100.0) if atr > 0 else 0.0
        day_remaining_pct = max(0.0, 100.0 - day_used_pct)
        if day_used_pct < 30.0:
            assessment = "Монета тільки розігрівається"
        elif day_used_pct < 60.0:
            assessment = "Є куди йти — нормально"
        elif day_used_pct < 80.0:
            assessment = "Обережно — більша частина пройдена"
        else:
            assessment = "Не входити — монета втомлена"
        return {
            "atr": atr,
            "day_high": day_high,
            "day_low": day_low,
            "day_range": day_range,
            "day_used_pct": day_used_pct,
            "day_remaining_pct": day_remaining_pct,
            "assessment": assessment,
        }
    except Exception:
        return {}


def fetch_long_short_ratio(symbol: str) -> Dict[str, Any]:
    """
    Global long/short account ratio (1h, last 4 points).
    Returns {} on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        data = _http_get_json(
            "https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
            {"symbol": sym, "period": "1h", "limit": 4},
        )
        if not isinstance(data, list) or not data:
            return {}
        hist: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            ratio = float(item.get("longShortRatio") or 0.0)
            long_pct = float(item.get("longAccount") or 0.0)
            short_pct = float(item.get("shortAccount") or 0.0)
            ts_ms = int(item.get("timestamp") or 0)
            ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat() if ts_ms > 0 else ""
            hist.append(
                {
                    "ratio": ratio,
                    "long_pct": long_pct,
                    "short_pct": short_pct,
                    "timestamp": ts,
                }
            )
        if not hist:
            return {}
        current_ratio = float(hist[-1]["ratio"])
        trend = "flat"
        if len(hist) >= 2:
            if current_ratio > float(hist[0]["ratio"]):
                trend = "up"
            elif current_ratio < float(hist[0]["ratio"]):
                trend = "down"
        return {
            "symbol": sym,
            "current_ratio": current_ratio,
            "trend": trend,
            "history": hist,
        }
    except Exception:
        return {}


def fetch_top_traders_ratio(symbol: str) -> Dict[str, Any]:
    """
    Top traders long/short position ratio snapshot.
    Returns {} on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        data = _http_get_json(
            "https://fapi.binance.com/futures/data/topLongShortPositionRatio",
            {"symbol": sym, "period": "1h", "limit": 1},
        )
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return {}
        item = data[0]
        return {
            "symbol": sym,
            "long_pct": float(item.get("longAccount") or 0.0),
            "short_pct": float(item.get("shortAccount") or 0.0),
        }
    except Exception:
        return {}


def fetch_recent_liquidations(symbol: str) -> List[Dict[str, Any]]:
    """
    Recent liquidation orders (force orders).
    Returns [] on failure.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return []
        data = _http_get_json(
            "https://fapi.binance.com/fapi/v1/forceOrders",
            {"symbol": sym, "limit": 10},
        )
        if not isinstance(data, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            side = str(item.get("side") or "")
            price = float(item.get("price") or 0.0)
            qty = float(item.get("origQty") or item.get("executedQty") or 0.0)
            ts_ms = int(item.get("time") or 0)
            ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).isoformat() if ts_ms > 0 else ""
            out.append({"side": side, "price": price, "qty": qty, "time": ts})
        return out
    except Exception:
        return []


def fetch_key_levels(symbol: str) -> List[Dict[str, Any]]:
    """
    Detect repeated support/resistance levels from daily highs/lows (30 candles).
    Returns [] on failure.
    """
    try:
        candles = fetch_candles(symbol, "1d", 30)
        if not isinstance(candles, list) or len(candles) < 10:
            return []
        points: List[Dict[str, Any]] = []
        for c in candles:
            h = float(c.get("high") or 0.0)
            l = float(c.get("low") or 0.0)
            if h > 0:
                points.append({"price": h, "type": "resistance"})
            if l > 0:
                points.append({"price": l, "type": "support"})
        if not points:
            return []
        clusters: List[Dict[str, Any]] = []
        for p in points:
            price = float(p["price"])
            ptype = str(p["type"])
            matched = False
            for c in clusters:
                if str(c["type"]) != ptype:
                    continue
                center = float(c["price"])
                tol = max(center * 0.005, 1e-9)
                if abs(price - center) <= tol:
                    touches = int(c["touches"]) + 1
                    c["touches"] = touches
                    c["price"] = ((center * (touches - 1)) + price) / touches
                    matched = True
                    break
            if not matched:
                clusters.append({"price": price, "type": ptype, "touches": 1})
        clusters = [c for c in clusters if int(c["touches"]) >= 2]
        clusters.sort(key=lambda x: int(x["touches"]), reverse=True)
        out: List[Dict[str, Any]] = []
        for c in clusters[:5]:
            touches = int(c["touches"])
            strength = "strong" if touches >= 4 else "medium"
            out.append(
                {
                    "price": float(c["price"]),
                    "type": str(c["type"]),
                    "touches": touches,
                    "strength": strength,
                }
            )
        return out
    except Exception:
        return []


def fetch_ote_levels(symbol: str, timeframe: str = "4h") -> Dict[str, Any]:
    """
    Compute OTE levels (61.8 / 70.5 / 78.6) from the largest impulse body.
    Returns {} on failure.
    """
    try:
        candles = fetch_candles(symbol, timeframe, 10)
        if not isinstance(candles, list) or len(candles) < 3:
            return {}
        best = None
        best_body = -1.0
        for c in candles:
            o = float(c.get("open") or 0.0)
            cl = float(c.get("close") or 0.0)
            body = abs(cl - o)
            if body > best_body:
                best_body = body
                best = c
        if not isinstance(best, dict):
            return {}
        high = float(best.get("high") or 0.0)
        low = float(best.get("low") or 0.0)
        o = float(best.get("open") or 0.0)
        cl = float(best.get("close") or 0.0)
        if high <= low:
            return {}
        ote_618 = low + (high - low) * 0.618
        ote_705 = low + (high - low) * 0.705
        ote_786 = low + (high - low) * 0.786
        direction = "LONG" if cl >= o else "SHORT"
        return {
            "impulse_high": high,
            "impulse_low": low,
            "ote_618": ote_618,
            "ote_705": ote_705,
            "ote_786": ote_786,
            "direction": direction,
        }
    except Exception:
        return {}


def fetch_top_movers(direction: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Top gainers/losers by 24h change for USDT symbols with quoteVolume > 5M.
    Returns [] on failure.
    """
    try:
        data = _http_get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", {})
        if not isinstance(data, list):
            return []
        rows: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            sym = str(item.get("symbol") or "")
            if not sym.endswith("USDT"):
                continue
            quote_vol = float(item.get("quoteVolume") or 0.0)
            if quote_vol <= 5_000_000:
                continue
            change_pct = float(item.get("priceChangePercent") or 0.0)
            rows.append(
                {
                    "symbol": sym,
                    "change_pct": change_pct,
                    "price": float(item.get("lastPrice") or 0.0),
                    "volume_usdt": quote_vol,
                }
            )
        d = str(direction or "").strip().lower()
        if d == "losers":
            rows.sort(key=lambda x: float(x["change_pct"]))
        else:
            rows.sort(key=lambda x: float(x["change_pct"]), reverse=True)
        return rows[: max(1, int(limit or 5))]
    except Exception:
        return []


def _fetch_yahoo_change(symbol: str) -> Union[float, None]:
    try:
        data = _http_get_json(
            f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}",
            {"interval": "1d", "range": "5d"},
        )
        if not isinstance(data, dict):
            return None
        chart = data.get("chart")
        if not isinstance(chart, dict):
            return None
        result = chart.get("result")
        if not isinstance(result, list) or not result or not isinstance(result[0], dict):
            return None
        indicators = result[0].get("indicators")
        if not isinstance(indicators, dict):
            return None
        quote = indicators.get("quote")
        if not isinstance(quote, list) or not quote or not isinstance(quote[0], dict):
            return None
        closes = quote[0].get("close")
        if not isinstance(closes, list):
            return None
        vals = [float(v) for v in closes if isinstance(v, (int, float)) and math.isfinite(float(v))]
        if len(vals) < 2 or vals[-2] == 0:
            return None
        return ((vals[-1] - vals[-2]) / vals[-2]) * 100.0
    except Exception:
        return None


def _fetch_stooq_change(symbol: str) -> Union[float, None]:
    try:
        parsed = urlparse(
            f"https://stooq.com/q/d/l/?{urlencode({'s': symbol, 'i': 'd'})}"
        )
        url = parsed.geturl()
        with urlopen(url, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if len(lines) < 3:
            return None
        prev_parts = [x.strip() for x in lines[-2].split(",")]
        curr_parts = [x.strip() for x in lines[-1].split(",")]
        if len(prev_parts) < 5 or len(curr_parts) < 5:
            return None
        prev_close = float(prev_parts[4])
        curr_close = float(curr_parts[4])
        if not math.isfinite(prev_close) or not math.isfinite(curr_close) or prev_close == 0:
            return None
        return ((curr_close - prev_close) / prev_close) * 100.0
    except Exception:
        return None


def fetch_macro_context() -> Dict[str, Any]:
    """
    Macro context snapshot: BTC, Gold, SP500, DXY and correlation note.
    Returns {} on failure.
    """
    try:
        btc_change = None
        btc = fetch_candles("BTCUSDT", "1d", 2)
        if isinstance(btc, list) and len(btc) >= 2:
            c0 = float(btc[-2].get("close") or 0.0)
            c1 = float(btc[-1].get("close") or 0.0)
            if c0 != 0:
                btc_change = ((c1 - c0) / c0) * 100.0

        gold_change = _fetch_yahoo_change("GC=F")
        sp500_change = _fetch_yahoo_change("^GSPC")
        dxy_change = _fetch_yahoo_change("DX-Y.NYB")

        if gold_change is None:
            gold_change = _fetch_stooq_change("gc.f")
        if sp500_change is None:
            sp500_change = _fetch_stooq_change("^spx")
        if dxy_change is None:
            dxy_change = _fetch_stooq_change("dx.f")

        note = "Нейтральний макро фон"
        if dxy_change is not None and dxy_change > 0:
            note = "Долар зміцнюється — тиск на крипто"
        elif (sp500_change is not None and sp500_change < 0) and (gold_change is not None and gold_change > 0):
            note = "Risk-off — обережно"
        elif sp500_change is not None and sp500_change > 0:
            note = "Risk-on — сприятливо для крипто"

        return {
            "btc_change_24h": btc_change,
            "gold_change_24h": gold_change,
            "sp500_change_24h": sp500_change,
            "dxy_change_24h": dxy_change,
            "correlation_note": note,
        }
    except Exception:
        return {}

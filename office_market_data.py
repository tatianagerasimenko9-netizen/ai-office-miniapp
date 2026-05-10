from __future__ import annotations

import json
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Union
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

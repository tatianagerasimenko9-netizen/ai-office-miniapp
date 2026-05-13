from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen


JSONLike = Union[Dict[str, Any], List[Any]]

_PROBABILITY_PHASE4_DEFAULT: Dict[str, Any] = {
    "expected_value": 0.0,
    "ev_positive": False,
    "sweep_probability": 15,
    "fake_breakout_prob": 20,
}

# Поріг «снайперського» сетапу для fetch_edge_score() та проактивного сканера.
SIGNAL_THRESHOLD = 85


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


def fetch_order_book_walls(symbol: str, min_size_usdt: float = 500_000.0) -> Dict[str, Any]:
    """
    Order book depth — великі рівні bid/ask (агреговані як «стіни» у notional USDT).

    Binance GET /fapi/v1/depth limit=100 — рівні з price*qty >= min_size_usdt.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {"symbol": "", "description": "DOM недоступний"}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"

        try:
            min_sz = float(min_size_usdt)
        except (TypeError, ValueError):
            min_sz = 500_000.0
        if min_sz <= 0:
            min_sz = 500_000.0

        raw = _http_get_json(
            "https://fapi.binance.com/fapi/v1/depth",
            {"symbol": sym, "limit": 100},
        )
        if not isinstance(raw, dict):
            return {"symbol": sym, "description": "DOM недоступний"}

        bids = raw.get("bids")
        asks = raw.get("asks")
        if not isinstance(bids, list) or not isinstance(asks, list):
            return {"symbol": sym, "description": "DOM недоступний"}

        whale_bids: List[Dict[str, Any]] = []
        whale_asks: List[Dict[str, Any]] = []

        for bid in bids:
            if not isinstance(bid, (list, tuple)) or len(bid) < 2:
                continue
            try:
                price = float(bid[0])
                qty = float(bid[1])
            except (TypeError, ValueError):
                continue
            size_usdt = price * qty
            if size_usdt >= min_sz:
                whale_bids.append(
                    {
                        "price": price,
                        "qty": qty,
                        "size_usdt": round(size_usdt / 1000.0, 1),
                        "size_str": f"${size_usdt / 1000.0:.0f}K",
                    }
                )

        for ask in asks:
            if not isinstance(ask, (list, tuple)) or len(ask) < 2:
                continue
            try:
                price = float(ask[0])
                qty = float(ask[1])
            except (TypeError, ValueError):
                continue
            size_usdt = price * qty
            if size_usdt >= min_sz:
                whale_asks.append(
                    {
                        "price": price,
                        "qty": qty,
                        "size_usdt": round(size_usdt / 1000.0, 1),
                        "size_str": f"${size_usdt / 1000.0:.0f}K",
                    }
                )

        whale_bids.sort(key=lambda x: float(x.get("size_usdt") or 0.0), reverse=True)
        whale_asks.sort(key=lambda x: float(x.get("size_usdt") or 0.0), reverse=True)

        biggest_bid = whale_bids[0] if whale_bids else None
        biggest_ask = whale_asks[0] if whale_asks else None

        descriptions: List[str] = []
        if biggest_bid:
            descriptions.append(
                f"Кит BID {biggest_bid['size_str']} на {biggest_bid['price']} — підтримка"
            )
        if biggest_ask:
            descriptions.append(
                f"Кит ASK {biggest_ask['size_str']} на {biggest_ask['price']} — опір"
            )

        return {
            "symbol": sym,
            "whale_bids": whale_bids[:5],
            "whale_asks": whale_asks[:5],
            "biggest_support": biggest_bid,
            "biggest_resistance": biggest_ask,
            "total_whale_bids": len(whale_bids),
            "total_whale_asks": len(whale_asks),
            "description": " | ".join(descriptions) if descriptions else "Великих ордерів не знайдено",
        }
    except Exception as e:
        print(f"[dom] error {symbol}: {e}")
        return {
            "symbol": str(symbol or "").upper().strip(),
            "description": "DOM недоступний",
        }


def fetch_order_blocks(symbol: str, tf: str = "1h") -> Dict[str, Any]:
    """
    Order Blocks (спрощено під ICT):

    - Bullish OB: остання ведмежа свічка перед сильною бичачою, що пробиває її high.
    - Bearish OB: остання бичача свічка перед сильною ведмежою, що пробиває її low.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        tf_s = str(tf or "1h").strip().lower() or "1h"

        candles = fetch_candles(sym, tf_s, 20)
        if not isinstance(candles, list) or len(candles) < 5:
            return {}

        result: Dict[str, Any] = {
            "symbol": sym,
            "tf": tf_s,
            "bullish_ob": None,
            "bearish_ob": None,
            "description": "",
        }
        descriptions: List[str] = []

        for i in range(1, len(candles) - 2):
            c = candles[i]
            c_next = candles[i + 1]
            if not isinstance(c, dict) or not isinstance(c_next, dict):
                continue

            o = float(c.get("open") or 0.0)
            cl = float(c.get("close") or 0.0)
            h = float(c.get("high") or 0.0)
            l = float(c.get("low") or 0.0)

            o_next = float(c_next.get("open") or 0.0)
            cl_next = float(c_next.get("close") or 0.0)

            is_bearish = cl < o
            next_bullish_strong = cl_next > o_next and cl_next > h

            if is_bearish and next_bullish_strong:
                result["bullish_ob"] = {
                    "high": h,
                    "low": l,
                    "open": o,
                    "close": cl,
                    "index": i,
                }
                descriptions.append(f"Bullish OB: зона {l:.4f}–{h:.4f}")

            is_bullish = cl > o
            next_bearish_strong = cl_next < o_next and cl_next < l

            if is_bullish and next_bearish_strong:
                result["bearish_ob"] = {
                    "high": h,
                    "low": l,
                    "open": o,
                    "close": cl,
                    "index": i,
                }
                descriptions.append(f"Bearish OB: зона {l:.4f}–{h:.4f}")

        result["description"] = " | ".join(descriptions) if descriptions else "Order Blocks не знайдено"
        return result
    except Exception as e:
        print(f"[ob] error {symbol}: {e}")
        return {}


def fetch_fvg(symbol: str, tf: str = "1h") -> Dict[str, Any]:
    """
    Fair Value Gap — незаповнені гапи між high/low сусідніх свічок (3-свічкова схема).

    - Bullish FVG: low свічки i+1 вище high свічки i−1 (імбаланс вгору).
    - Bearish FVG: high свічки i+1 нижче low свічки i−1 (імбаланс вниз).
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        tf_s = str(tf or "1h").strip().lower() or "1h"

        candles = fetch_candles(sym, tf_s, 20)
        if not isinstance(candles, list) or len(candles) < 3:
            return {}

        last = candles[-1]
        if not isinstance(last, dict):
            return {}
        current_price = float(last.get("close") or 0.0)

        bullish_fvgs: List[Dict[str, Any]] = []
        bearish_fvgs: List[Dict[str, Any]] = []

        for i in range(1, len(candles) - 1):
            prev = candles[i - 1]
            next_ = candles[i + 1]
            if not isinstance(prev, dict) or not isinstance(next_, dict):
                continue

            prev_high = float(prev.get("high") or 0.0)
            prev_low = float(prev.get("low") or 0.0)
            next_high = float(next_.get("high") or 0.0)
            next_low = float(next_.get("low") or 0.0)

            if next_low > prev_high and prev_high > 0:
                gap_size = next_low - prev_high
                gap_pct = gap_size / prev_high * 100.0
                if gap_pct > 0.1:
                    fvg: Dict[str, Any] = {
                        "type": "BULLISH",
                        "high": next_low,
                        "low": prev_high,
                        "gap_pct": round(gap_pct, 3),
                        "index": i,
                        "filled": (current_price < next_low and current_price > prev_high),
                    }
                    bullish_fvgs.append(fvg)

            if next_high < prev_low and prev_low > 0:
                gap_size = prev_low - next_high
                gap_pct = gap_size / prev_low * 100.0
                if gap_pct > 0.1:
                    fvg = {
                        "type": "BEARISH",
                        "high": prev_low,
                        "low": next_high,
                        "gap_pct": round(gap_pct, 3),
                        "index": i,
                        "filled": (current_price < prev_low and current_price > next_high),
                    }
                    bearish_fvgs.append(fvg)

        active_bull = [f for f in bullish_fvgs if not f["filled"]]
        active_bear = [f for f in bearish_fvgs if not f["filled"]]

        active_bull.sort(key=lambda x: abs(current_price - float(x["low"])))
        active_bear.sort(key=lambda x: abs(current_price - float(x["high"])))

        descriptions: List[str] = []
        if active_bull:
            closest = active_bull[0]
            descriptions.append(
                f"Bullish FVG: {float(closest['low']):.4f}–{float(closest['high']):.4f} ({closest['gap_pct']}%)"
            )
        if active_bear:
            closest = active_bear[0]
            descriptions.append(
                f"Bearish FVG: {float(closest['low']):.4f}–{float(closest['high']):.4f} ({closest['gap_pct']}%)"
            )

        return {
            "symbol": sym,
            "tf": tf_s,
            "current_price": current_price,
            "bullish_fvg": active_bull[0] if active_bull else None,
            "bearish_fvg": active_bear[0] if active_bear else None,
            "all_bullish": active_bull[:3],
            "all_bearish": active_bear[:3],
            "description": " | ".join(descriptions) if descriptions else "FVG не знайдено",
        }
    except Exception as e:
        print(f"[fvg] error {symbol}: {e}")
        return {}


def _ticker_24h_change_pct(symbol: str) -> float:
    """Добова зміна % з Binance USDT-M ticker."""
    try:
        sym = str(symbol or "").upper().strip()
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"
        data = _http_get_json("https://fapi.binance.com/fapi/v1/ticker/24hr", {"symbol": sym})
        if isinstance(data, dict):
            return float(data.get("priceChangePercent") or 0.0)
    except Exception:
        pass
    return 0.0


def _parse_econ_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    s = str(value).strip()
    for p in (
        lambda x: datetime.fromisoformat(x.replace("Z", "+00:00")),
        lambda x: datetime.strptime(x, "%Y-%m-%d %H:%M:%S"),
        lambda x: datetime.strptime(x, "%Y-%m-%d"),
    ):
        try:
            dt = p(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _news_chaos_sync() -> tuple[bool, str]:
    """
    NEWS CHAOS: важлива макро-подія за FMP — за <30 хв або щойно (до 15 хв тому).
    """
    key = os.getenv("NEWS_API_KEY", "").strip()
    if not key:
        return False, ""
    keys_hi = ("fomc", "fed", "rate", "cpi", "nfp", "powell", "inflation", "ecb", "boj")
    try:
        now = datetime.now(timezone.utc)
        from_s = now.strftime("%Y-%m-%d")
        data = _http_get_json(
            "https://financialmodelingprep.com/stable/economic-calendar",
            {"from": from_s, "to": from_s, "apikey": key},
        )
        if not isinstance(data, list):
            return False, ""
        for e in data:
            if not isinstance(e, dict):
                continue
            title = str(e.get("event") or e.get("title") or "")
            if not title:
                continue
            impact = str(e.get("impact") or e.get("importance") or "").lower().strip()
            important = "high" in impact or "medium" in impact or "med" in impact
            if not important and not any(k in title.lower() for k in keys_hi):
                continue
            dt = _parse_econ_dt(str(e.get("date") or e.get("time") or ""))
            if dt is None:
                continue
            mins = int((dt - now).total_seconds() / 60)
            if 0 <= mins <= 30:
                return True, title[:120]
            if -15 <= mins < 0:
                return True, title[:120]
    except Exception as exc:
        print(f"[regime-news] {exc}")
    return False, ""


def fetch_market_regime(symbol: str) -> Dict[str, Any]:
    """
    Поточний режим ринку (евристика для вибору стратегії):

    NEWS_CHAOS — важлива макроподія скоро / щойно (не торгуємо);
    PANIC — day_used_pct ATR > 200% (не торгуємо);
    EUPHORIA — сильна доба + перегрітий L/S (обережно з лонгами);
    COMPRESSION — вузький range_pct і низький day_used (стискання);
    LIQUIDITY_HUNT — BSL/SSL sweep і повернення ціни (чекаємо підтвердження);
    LOW_LIQUIDITY — високий day_used_pct;
    EXPANSION — сплеск обсягу + низький day_used_pct;
    TREND_UP / TREND_DOWN — послідовні 4h closes;
    RANGE — вузький діапазон 24×1h;
    NEUTRAL.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {"regime": "UNKNOWN"}
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"

        candles_1h = fetch_candles(sym, "1h", 24)
        candles_4h = fetch_candles(sym, "4h", 10)
        atr_data = fetch_atr_context(sym)

        if not isinstance(candles_1h, list) or not isinstance(candles_4h, list):
            return {"regime": "UNKNOWN", "symbol": sym}
        if len(candles_1h) < 6 or len(candles_4h) < 5:
            return {"regime": "UNKNOWN", "symbol": sym}

        atr_ad = atr_data if isinstance(atr_data, dict) else {}
        day_used = float(atr_ad.get("day_used_pct") or 50.0)

        volumes = [float(c.get("volume") or 0.0) for c in candles_1h[-6:] if isinstance(c, dict)]
        avg_vol = sum(volumes) / len(volumes) if volumes else 0.0
        last_vol = volumes[-1] if volumes else 0.0
        vol_spike = (last_vol > avg_vol * 2.5) if avg_vol > 0 else False

        prices_4h = [float(c.get("close") or 0.0) for c in candles_4h if isinstance(c, dict)]
        if len(prices_4h) >= 5:
            trend_up = all(prices_4h[i] > prices_4h[i - 1] for i in range(-4, 0))
            trend_down = all(prices_4h[i] < prices_4h[i - 1] for i in range(-4, 0))
        else:
            trend_up = False
            trend_down = False

        highs_24h = [float(c.get("high") or 0.0) for c in candles_1h if isinstance(c, dict)]
        lows_24h = [float(c.get("low") or 0.0) for c in candles_1h if isinstance(c, dict)]
        range_24h = max(highs_24h) - min(lows_24h) if highs_24h and lows_24h else 0.0
        last1 = candles_1h[-1]
        if not isinstance(last1, dict):
            return {"regime": "UNKNOWN", "symbol": sym}
        current = float(last1.get("close") or 0.0)
        range_pct = (range_24h / current * 100.0) if current > 0 else 0.0

        last = candles_1h[-1]
        prev = candles_1h[-2]
        if not isinstance(last, dict) or not isinstance(prev, dict):
            return {"regime": "UNKNOWN", "symbol": sym}
        last_h = float(last.get("high") or 0.0)
        last_l = float(last.get("low") or 0.0)
        last_c = float(last.get("close") or 0.0)
        prev_h = float(prev.get("high") or 0.0)
        prev_l = float(prev.get("low") or 0.0)

        bsl_sweep = last_h > prev_h and last_c < prev_h
        ssl_sweep = last_l < prev_l and last_c > prev_l
        manipulation = bsl_sweep or ssl_sweep

        ls_data = fetch_long_short_ratio(sym)
        ls_ratio = float(ls_data.get("current_ratio") or 1.0) if isinstance(ls_data, dict) else 1.0
        change_pct_24h = _ticker_24h_change_pct(sym)
        news_chaos, news_title = _news_chaos_sync()

        if manipulation:
            controller = "Маркетмейкер"
        elif vol_spike and trend_up:
            controller = "Інституції"
        elif ls_ratio > 2.5:
            controller = "Ритейл (натовп)"
        else:
            controller = "Алгоритми"

        regime = "NEUTRAL"
        description = "Нейтральний ринок."

        if news_chaos:
            regime = "NEWS_CHAOS"
            description = (
                "Новинний хаос: важлива подія за <30 хв або щойно (<15 хв). Не торгуємо. "
                + (news_title or "")
            )
        elif day_used > 200.0:
            regime = "PANIC"
            description = "ATR доби > 200% — паніка / екстрем. Не торгуємо."
        elif change_pct_24h > 15.0 and ls_ratio > 3.0:
            regime = "EUPHORIA"
            description = (
                f"Ейфорія: доба +{change_pct_24h:.1f}%, L/S {ls_ratio:.2f}. "
                "Небезпечно входити в лонг."
            )
        elif range_pct < 1.5 and day_used < 30.0:
            regime = "COMPRESSION"
            description = (
                f"Компресія: вузький діапазон {range_pct:.2f}% і ATR day_used {day_used:.0f}% "
                "(<30%) — стискання перед імпульсом."
            )
        elif manipulation:
            regime = "LIQUIDITY_HUNT"
            sweep_type = "BSL" if bsl_sweep else "SSL"
            description = (
                f"{sweep_type}: sweep ліквідності й повернення ціни. "
                "Чекаємо підтвердження розвороту."
            )
        elif day_used > 150.0:
            regime = "LOW_LIQUIDITY"
            description = "ATR перевищено — монета мертва. Не торгуємо до нового дня."
        elif vol_spike and day_used < 50:
            regime = "EXPANSION"
            description = "Сильний об'єм + малий ATR. Ринок починає великий рух."
        elif trend_up:
            regime = "TREND_UP"
            description = "Висхідний тренд на 4H. Шукаємо LONG від підтримок."
        elif trend_down:
            regime = "TREND_DOWN"
            description = "Низхідний тренд на 4H. Шукаємо SHORT від опорів."
        elif range_pct < 3:
            regime = "RANGE"
            description = f"Боковик — діапазон {range_pct:.1f}%. Mean-reversion стратегія."
        else:
            regime = "NEUTRAL"
            description = "Нейтральний ринок."

        return {
            "symbol": sym,
            "regime": regime,
            "description": description,
            "day_used_pct": day_used,
            "vol_spike": vol_spike,
            "manipulation": manipulation,
            "bsl_sweep": bsl_sweep,
            "ssl_sweep": ssl_sweep,
            "trend_up": trend_up,
            "trend_down": trend_down,
            "range_pct": round(range_pct, 2),
            "controller": controller,
            "ls_ratio": round(ls_ratio, 3),
            "change_pct_24h": round(change_pct_24h, 2),
            "news_chaos": bool(news_chaos),
        }
    except Exception as e:
        print(f"[regime] error {symbol}: {e}")
        return {"regime": "UNKNOWN", "symbol": str(symbol or "").upper().strip()}


def fetch_probability_score(symbol: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Probability Engine — грубий confluence-скоринг LONG vs SHORT vs NO TRADE.
    Не прогноз, а узгодженість факторів (funding, L/S, OI, regime, structure, PD, sweep).
    Додає expected_value / sweep_probability / fake_breakout_prob (Фаза 4).
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {
                "symbol": "",
                "recommendation": "NO_TRADE",
                "reason": "Порожній символ",
                "long_prob": 0,
                "short_prob": 0,
                "no_trade_prob": 100,
                **_PROBABILITY_PHASE4_DEFAULT,
            }
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"

        atr = fetch_atr_context(sym)
        ls = fetch_long_short_ratio(sym)
        funding = fetch_funding_rate(sym)
        oi = fetch_open_interest(sym)
        regime = fetch_market_regime(sym)
        structure = fetch_market_structure(sym, "1h")
        sweep = fetch_liquidity_sweep(sym, "1h")
        pd_arr = fetch_pd_array(sym, "4h")

        atr_d = atr if isinstance(atr, dict) else {}
        ls_d = ls if isinstance(ls, dict) else {}
        funding_d = funding if isinstance(funding, dict) else {}
        oi_d = oi if isinstance(oi, dict) else {}
        regime_d = regime if isinstance(regime, dict) else {}
        structure_d = structure if isinstance(structure, dict) else {}
        sweep_d = sweep if isinstance(sweep, dict) else {}
        pd_d = pd_arr if isinstance(pd_arr, dict) else {}

        def _phase4_metrics() -> Dict[str, Any]:
            rv = str(regime_d.get("regime") or "")
            vol_sp = bool(regime_d.get("vol_spike"))
            b_manip = bool(regime_d.get("manipulation"))
            bsl = bool(regime_d.get("bsl_sweep") or sweep_d.get("bsl_sweep"))
            ssl = bool(regime_d.get("ssl_sweep") or sweep_d.get("ssl_sweep"))
            if bsl or ssl:
                sw_p = 75
            elif b_manip:
                sw_p = 50
            else:
                sw_p = 15
            if rv == "RANGE" and vol_sp:
                fk = 70
            elif rv in ("MANIPULATION", "LIQUIDITY_HUNT"):
                fk = 80
            else:
                fk = 20
            dbp = (
                (db_path or "").strip()
                or os.getenv("OFFICE_DB_PATH", "").strip()
                or os.getenv("DATABASE_URL", "").strip()
                or "office_bridge.db"
            )
            wr = 0.5
            try:
                from office_bridge import trade_journal_get_stats

                stats = trade_journal_get_stats(dbp)
                wr = float(stats.get("win_rate", 50.0)) / 100.0
            except Exception:
                pass
            avg_rr = 2.0
            ev = (wr * avg_rr) - (1.0 - wr)
            return {
                "expected_value": round(float(ev), 2),
                "ev_positive": bool(ev > 0),
                "sweep_probability": int(sw_p),
                "fake_breakout_prob": int(fk),
            }

        phase4 = _phase4_metrics()

        long_score = 0
        short_score = 0
        factors_long: List[str] = []
        factors_short: List[str] = []

        day_used = float(atr_d.get("day_used_pct") or 100.0)
        if day_used > 85.0:
            return {
                "symbol": sym,
                "long_prob": 0,
                "short_prob": 0,
                "no_trade_prob": 100,
                "confidence": "LOW",
                "recommendation": "NO_TRADE",
                "reason": f"ATR {day_used:.0f}% — немає запасу ходу",
                "factors_long": [],
                "factors_short": [],
                **phase4,
            }

        fr_raw = funding_d.get("funding_rate_pct")
        fr = float(fr_raw) if fr_raw is not None else 0.0
        if fr < -0.01:
            long_score += 15
            factors_long.append(f"Funding від'ємний {fr:.3f}% (шорти переплачують)")
        elif fr > 0.01:
            short_score += 15
            factors_short.append(f"Funding позитивний {fr:.3f}% (лонги переплачують)")

        ls_ratio = float(ls_d.get("current_ratio") or 1.0)
        if ls_ratio > 2.0:
            short_score += 20
            factors_short.append(f"L/S {ls_ratio:.2f} — натовп у лонгах (пастка)")
        elif ls_ratio < 0.7:
            long_score += 20
            factors_long.append(f"L/S {ls_ratio:.2f} — натовп у шортах (squeeze)")

        oi_hist = oi_d.get("history", [])
        if isinstance(oi_hist, list) and len(oi_hist) >= 3:
            oi_vals: List[float] = []
            for x in oi_hist[-3:]:
                if not isinstance(x, dict):
                    continue
                v = float(x.get("oi_usdt") or x.get("oi") or 0.0)
                oi_vals.append(v)
            if len(oi_vals) >= 3:
                oi_growing = oi_vals[-1] > oi_vals[-2] > oi_vals[-3]
                oi_falling = oi_vals[-1] < oi_vals[-2] < oi_vals[-3]
                if oi_growing:
                    pass
                if oi_falling:
                    short_score += 10
                    factors_short.append("OI падає — позиції закриваються")

        regime_val = str(regime_d.get("regime") or "")
        if regime_val == "TREND_UP":
            long_score += 25
            factors_long.append("Режим TREND_UP на 4H")
        elif regime_val == "TREND_DOWN":
            short_score += 25
            factors_short.append("Режим TREND_DOWN на 4H")
        elif regime_val == "EUPHORIA":
            short_score += 35
            factors_short.append("Режим EUPHORIA — перегріті лонги, небезпечно входити в LONG")
            long_score = max(0, long_score - 25)
        elif regime_val in ("LIQUIDITY_HUNT", "MANIPULATION"):
            if sweep_d.get("bsl_sweep") or regime_d.get("bsl_sweep"):
                short_score += 20
                factors_short.append("BSL sweep — можливий SHORT")
            elif sweep_d.get("ssl_sweep") or regime_d.get("ssl_sweep"):
                long_score += 20
                factors_long.append("SSL sweep — можливий LONG")
        elif regime_val in ("LOW_LIQUIDITY", "RANGE", "NEWS_CHAOS", "PANIC"):
            return {
                "symbol": sym,
                "long_prob": 0,
                "short_prob": 0,
                "no_trade_prob": 100,
                "confidence": "LOW",
                "recommendation": "NO_TRADE",
                "reason": f"Режим {regime_val} — не торгуємо",
                "factors_long": [],
                "factors_short": [],
                **phase4,
            }

        struct_event = str(structure_d.get("event") or "")
        if struct_event == "BOS_BULLISH":
            long_score += 20
            factors_long.append("BOS вгору — структура бичача")
        elif struct_event == "BOS_BEARISH":
            short_score += 20
            factors_short.append("BOS вниз — структура ведмежа")
        elif struct_event == "CHOCH":
            long_score = max(0, long_score - 10)
            short_score = max(0, short_score - 10)

        pd_zone = str(pd_d.get("zone") or "")
        if pd_zone == "PREMIUM":
            short_score += 15
            factors_short.append("Ціна в Premium зоні — шукаємо SHORT")
        elif pd_zone == "DISCOUNT":
            long_score += 15
            factors_long.append("Ціна в Discount зоні — шукаємо LONG")

        if sweep_d.get("ssl_sweep"):
            long_score += 15
            lvl = sweep_d.get("sweep_level")
            factors_long.append(f"SSL sweep на {lvl} — LONG після маніпуляції")
        if sweep_d.get("bsl_sweep"):
            short_score += 15
            lvl = sweep_d.get("sweep_level")
            factors_short.append(f"BSL sweep на {lvl} — SHORT після маніпуляції")

        total = long_score + short_score
        if total == 0:
            long_p = short_p = 30
            no_trade_p = 40
        else:
            long_p = int(long_score / total * 70)
            short_p = int(short_score / total * 70)
            no_trade_p = 30

        total_p = long_p + short_p + no_trade_p
        if total_p > 100:
            factor = 100.0 / float(total_p)
            long_p = int(long_p * factor)
            short_p = int(short_p * factor)
            no_trade_p = 100 - long_p - short_p

        max_score = max(long_score, short_score)
        if max_score >= 60:
            confidence = "HIGH"
        elif max_score >= 35:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        if no_trade_p >= 50 or max_score < 25:
            recommendation = "NO_TRADE"
        elif long_score > short_score:
            recommendation = "LONG"
        else:
            recommendation = "SHORT"

        return {
            "symbol": sym,
            "long_prob": long_p,
            "short_prob": short_p,
            "no_trade_prob": no_trade_p,
            "confidence": confidence,
            "recommendation": recommendation,
            "long_score": long_score,
            "short_score": short_score,
            "factors_long": factors_long,
            "factors_short": factors_short,
            "regime": regime_val,
            "reason": f"LONG {long_p}% / SHORT {short_p}% / NO TRADE {no_trade_p}%",
            **phase4,
        }
    except Exception as e:
        print(f"[prob] error {symbol}: {e}")
        return {
            "symbol": str(symbol or "").upper().strip(),
            "recommendation": "NO_TRADE",
            "reason": "Помилка розрахунку",
            "long_prob": 0,
            "short_prob": 0,
            "no_trade_prob": 100,
            "confidence": "LOW",
            "factors_long": [],
            "factors_short": [],
            **_PROBABILITY_PHASE4_DEFAULT,
        }


def _near_session_or_pdh_pdl(price: float, session_d: Dict[str, Any], tol: float = 0.005) -> bool:
    """Ціна близько до PDH/PDL або high/low сесій Asia/London/NY."""
    if price <= 0 or not session_d:
        return False
    keys = (
        "pdh",
        "pdl",
        "asia_high",
        "asia_low",
        "london_high",
        "london_low",
        "ny_high",
        "ny_low",
    )
    for k in keys:
        raw = session_d.get(k)
        if raw is None:
            continue
        try:
            lv = float(raw)
        except (TypeError, ValueError):
            continue
        if lv <= 0:
            continue
        if abs(price - lv) / lv < tol:
            return True
    return False


def fetch_edge_score(symbol: str) -> Dict[str, Any]:
    """
    Edge Detector — setup score 0–100 (макс. після капу 100), поріг SIGNAL_THRESHOLD.

    has_edge=True лише якщо score >= SIGNAL_THRESHOLD і напрямок LONG/SHORT.
    """
    try:
        sym = str(symbol or "").upper().strip()
        if not sym:
            return {
                "symbol": "",
                "edge_score": 0,
                "grade": "C",
                "has_edge": False,
                "confirmed_factors": 0,
                "verdict": "Немає символу",
                "factors": [],
                "recommendation": "NO_TRADE",
                "signal_threshold": SIGNAL_THRESHOLD,
                "day_used_pct": None,
                "funding_rate_pct": None,
                "structure_event": "",
            }
        if not sym.endswith("USDT"):
            sym = f"{sym}USDT"

        fr = 0.0
        day_used = 100.0
        struct_event = ""

        atr = fetch_atr_context(sym)
        sweep = fetch_liquidity_sweep(sym, "1h")
        structure = fetch_market_structure(sym, "1h")
        pd_arr = fetch_pd_array(sym, "4h")
        session = fetch_session_levels(sym)
        walls = fetch_order_book_walls(sym)
        funding = fetch_funding_rate(sym)
        regime_sym = fetch_market_regime(sym)
        regime_btc = fetch_market_regime("BTCUSDT")
        _dbp = (os.getenv("OFFICE_DB_PATH") or os.getenv("DATABASE_URL") or "").strip() or None
        prob = fetch_probability_score(sym, _dbp)

        atr_d = atr if isinstance(atr, dict) else {}
        sweep_d = sweep if isinstance(sweep, dict) else {}
        structure_d = structure if isinstance(structure, dict) else {}
        pd_d = pd_arr if isinstance(pd_arr, dict) else {}
        session_d = session if isinstance(session, dict) else {}
        walls_d = walls if isinstance(walls, dict) else {}
        funding_d = funding if isinstance(funding, dict) else {}
        regime_sym_d = regime_sym if isinstance(regime_sym, dict) else {}
        regime_btc_d = regime_btc if isinstance(regime_btc, dict) else {}
        prob_d = prob if isinstance(prob, dict) else {}

        direction = str(prob_d.get("recommendation") or "").strip().upper()
        if direction not in ("LONG", "SHORT"):
            direction = str(direction or "NO_TRADE").upper() or "NO_TRADE"

        curr_f = float(pd_d.get("current_price") or 0.0)
        if curr_f <= 0:
            c1h = fetch_candles(sym, "1h", 1)
            if isinstance(c1h, list) and c1h and isinstance(c1h[-1], dict):
                try:
                    curr_f = float(c1h[-1].get("close") or 0.0)
                except (TypeError, ValueError):
                    curr_f = 0.0

        edge_score = 0
        edge_factors: List[str] = []
        confirmed = 0

        # 1. Liquidity location (+15)
        if curr_f > 0 and _near_session_or_pdh_pdl(curr_f, session_d):
            edge_score += 15
            edge_factors.append("Ціна біля рівня ліквідності (сесія / PDH / PDL)")
            confirmed += 1

        # 2. Sweep (+20)
        if sweep_d.get("bsl_sweep") or sweep_d.get("ssl_sweep"):
            edge_score += 20
            lvl = sweep_d.get("sweep_level")
            edge_factors.append(f"Sweep підтверджено @ {lvl}")
            confirmed += 1

        # 3. Displacement BOS (+15)
        struct_event = str(structure_d.get("event") or "")
        if struct_event in ("BOS_BULLISH", "BOS_BEARISH"):
            edge_score += 15
            edge_factors.append(f"{struct_event} — імпульс після структури")
            confirmed += 1

        # 4. BTC context (+10)
        btc_reg = str(regime_btc_d.get("regime") or "").upper()
        if btc_reg and btc_reg not in ("RANGE", "NEUTRAL", "NEWS_CHAOS", "LOW_LIQUIDITY", "UNKNOWN"):
            edge_score += 10
            edge_factors.append(f"BTC режим сприяє: {btc_reg}")
            confirmed += 1

        # 5. Whales aligned (+10) — підтримка для LONG, опір для SHORT
        biggest_bid = walls_d.get("biggest_support")
        biggest_ask = walls_d.get("biggest_resistance")
        if direction == "LONG" and biggest_bid:
            edge_score += 10
            edge_factors.append("Кит BID на стороні лонгу")
            confirmed += 1
        elif direction == "SHORT" and biggest_ask:
            edge_score += 10
            edge_factors.append("Кит ASK на стороні шорту")
            confirmed += 1

        # 6. Funding (+10)
        try:
            fr = abs(float(funding_d.get("funding_rate_pct", 0) or 0))
        except (TypeError, ValueError):
            fr = 0.0
        if fr < 0.05:
            edge_score += 10
            edge_factors.append(f"Funding помірний ({fr:.4f}%)")
            confirmed += 1

        # 7. ATR (+10 / +5)
        day_used = float(atr_d.get("day_used_pct") or 100.0)
        if day_used < 60:
            edge_score += 10
            edge_factors.append(f"ATR: запас ходу великий (day_used {day_used:.0f}%)")
            confirmed += 1
        elif day_used < 75:
            edge_score += 5
            edge_factors.append(f"ATR: помірний запас (day_used {day_used:.0f}%)")
            confirmed += 1

        # 8. News / режим символу (+10)
        regime_val = str(regime_sym_d.get("regime") or "").upper()
        if regime_val not in ("NEWS_CHAOS", "PANIC"):
            edge_score += 10
            edge_factors.append(f"Новинний/режимний фон ок ({regime_val or 'NEUTRAL'})")
            confirmed += 1

        edge_score = min(edge_score, 100)

        if edge_score >= SIGNAL_THRESHOLD:
            grade = "A+"
            verdict = "СНАЙПЕРСЬКИЙ ВХІД — дозволено"
        elif edge_score >= 70:
            grade = "B"
            verdict = "Слабкий сетап — чекаємо"
        else:
            grade = "C"
            verdict = "Немає переваги — мовчимо"

        has_edge = bool(edge_score >= SIGNAL_THRESHOLD and direction in ("LONG", "SHORT"))

        return {
            "symbol": sym,
            "edge_score": edge_score,
            "grade": grade,
            "has_edge": has_edge,
            "confirmed_factors": confirmed,
            "verdict": verdict,
            "factors": edge_factors,
            "recommendation": direction if direction in ("LONG", "SHORT") else "NO_TRADE",
            "signal_threshold": SIGNAL_THRESHOLD,
            "day_used_pct": day_used,
            "funding_rate_pct": fr,
            "structure_event": struct_event,
        }
    except Exception as e:
        print(f"[edge] error {symbol}: {e}")
        return {
            "symbol": str(symbol or "").upper().strip(),
            "edge_score": 0,
            "grade": "C",
            "has_edge": False,
            "confirmed_factors": 0,
            "verdict": "Помилка розрахунку",
            "factors": [],
            "recommendation": "NO_TRADE",
            "signal_threshold": SIGNAL_THRESHOLD,
            "day_used_pct": None,
            "funding_rate_pct": None,
            "structure_event": "",
        }


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

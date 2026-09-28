"""Єдине відображення цін: tickSize + Decimal. Не змінює торгові розрахунки.

Сирі float (0.07144666000000001) у Telegram / Mini App / PNG-підписах заборонені.
Округлення лише для тексту; SL/TP у розрахунках лишаються як є.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Optional


def to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        x = value
    else:
        try:
            x = Decimal(format(float(value), ".15g")) if isinstance(value, float) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
    if x.is_nan() or x <= 0:
        return None
    return x


def tick_size_for(symbol: str = "", price: Any = None) -> Decimal:
    """Біржовий крок: спочатку exchangeInfo, інакше евристика лише для тексту."""
    s = str(symbol or "").upper()
    try:
        from office_exchange_info import get_symbol_filters

        flt = get_symbol_filters(s)
        if flt.get("ok") and flt.get("tickSize") is not None:
            return flt["tickSize"]
    except Exception:
        pass
    p = to_decimal(price)
    if "BTC" in s:
        return Decimal("0.1")
    if s.startswith("ETH") or s.startswith("XAU") or "PAXG" in s:
        return Decimal("0.01") if p is None or p >= 1 else Decimal("0.001")
    if p is None:
        return Decimal("0.000001")
    if p >= 1000:
        return Decimal("0.1")
    if p >= 100:
        return Decimal("0.01")
    if p >= 10:
        return Decimal("0.001")
    if p >= 1:
        return Decimal("0.0001")
    if p >= Decimal("0.1"):
        return Decimal("0.0001")
    # Альти на кшталт MANTA (~0.07): 6 знаків, як tickSize-відображення 0.070471.
    return Decimal("0.000001")


def quantize_display(
    value: Any,
    *,
    symbol: str = "",
    tick: Any = None,
    side: str = "",
    kind: str = "",
) -> Optional[Decimal]:
    """Текст. SL/TP не підкручуємо в бік гіршого ризику (LONG SL вниз, SHORT SL вгору)."""
    from decimal import ROUND_DOWN, ROUND_UP

    d = to_decimal(value)
    if d is None:
        return None
    t = to_decimal(tick) if tick is not None else tick_size_for(symbol, d)
    if t is None or t <= 0:
        t = Decimal("0.000001")
    k = str(kind or "").upper()
    sd = str(side or "").upper()
    rounding = ROUND_HALF_UP
    if k in ("SL", "STOP"):
        rounding = ROUND_DOWN if sd == "LONG" else (ROUND_UP if sd == "SHORT" else ROUND_HALF_UP)
    elif k in ("TP", "TP1", "TP2", "TP3"):
        rounding = ROUND_DOWN if sd == "LONG" else (ROUND_UP if sd == "SHORT" else ROUND_HALF_UP)
    # Decimal.quantize(t) only matches decimal places; it does NOT enforce
    # non-power-of-ten tick sizes (e.g. 0.05 or 0.25).
    units = (d / t).to_integral_value(rounding=rounding)
    return (units * t).quantize(t)


def format_px(
    value: Any,
    symbol: str = "",
    *,
    tick: Any = None,
    group_thousands: bool = True,
    side: str = "",
    kind: str = "",
) -> str:
    """Текст ціни для всіх маршрутів офісу."""
    q = quantize_display(value, symbol=symbol, tick=tick, side=side, kind=kind)
    if q is None:
        return ""
    s = format(q, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if "." in s:
        whole, frac = s.split(".", 1)
    else:
        whole, frac = s, ""
    try:
        n = int(whole)
    except ValueError:
        return s
    if group_thousands and abs(n) >= 1000:
        grouped = f"{n:,}".replace(",", " ")
        return f"{grouped}.{frac}" if frac else grouped
    return s


def format_level_span(low: Any, high: Any, symbol: str = "", *, tick: Any = None) -> str:
    lo_d, hi_d = to_decimal(low), to_decimal(high)
    if lo_d is not None and hi_d is not None and lo_d > hi_d:
        low, high = high, low
    a, b = format_px(low, symbol, tick=tick), format_px(high, symbol, tick=tick)
    if not a and not b:
        return ""
    if not b or a == b:
        return a
    return f"{a}–{b}"


def has_float_tail(text: str) -> bool:
    s = str(text or "")
    return "000000" in s or "999999" in s


_PRICE_KEYS = (
    "entry",
    "entry_low",
    "entry_high",
    "entry_price",
    "sl",
    "stop_loss",
    "tp",
    "tp1",
    "tp2",
    "tp3",
    "price",
    "last_price",
    "add_px",
)


def format_price_fields(data: dict, symbol: str = "") -> dict:
    """Лише текст для UI. Числа в розрахунках не чіпає."""
    out = dict(data or {})
    sym = str(symbol or out.get("symbol") or "")
    for k in _PRICE_KEYS:
        if k not in out or out[k] is None or out[k] == "":
            continue
        txt = format_px(out[k], sym, group_thousands=False)
        if txt:
            out[k] = txt
    return out

"""T8: автономний дворівневий скаут усього Binance Futures.

Рівень 1 — легкий огляд усіх USDT-перпів (24h ticker): топ зростання/падіння,
обсяг, волатильність. Великий % зміни ≠ сетап.
Рівень 2 — детальні свічки лише для динамічного WATCHING.
Запит Тетяни додається поверх автоскрину, не замість нього.
BTC/XAU — контекст. Картка після підтвердження, без наздоганяння, без ордера.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from office_market_data import SIGNAL_THRESHOLD
from office_radar import MIN_RR

KIND_SCOUT = "market_scout"
# Ті самі стейбли, що відсікає Марічка — не торговий поріг ATR/Edge.
STABLE_BASES = frozenset({"USDC", "BUSD", "TUSD", "USDP", "DAI", "FDUSD"})
# Той самий ліквідний поріг, що fetch_top_movers.
MIN_QUOTE_VOLUME = 5_000_000.0
DEEP_SCAN_CAP = 24
CONTEXT_SEEDS: Tuple[str, ...] = ("BTCUSDT", "XAUUSDT")
GOLD_SYMBOLS = ("XAUUSDT", "XAUUSD")
GOLD_YAHOO = "GC=F"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
DATA_OK = "DATA_OK"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def _sym(v: Any) -> str:
    return str(v or "").upper().strip()


def is_usdt_perp(symbol: str) -> bool:
    s = _sym(symbol)
    if not s.endswith("USDT"):
        return False
    base = s[:-4]
    return base not in STABLE_BASES and bool(base)


def parse_ticker_row(item: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    sym = _sym(item.get("symbol"))
    if not is_usdt_perp(sym):
        return None
    last = _f(item.get("lastPrice") if item.get("lastPrice") is not None else item.get("price"))
    ch = _f(item.get("priceChangePercent") if item.get("priceChangePercent") is not None else item.get("change_pct"))
    vol = _f(item.get("quoteVolume") if item.get("quoteVolume") is not None else item.get("volume_usdt"))
    high = _f(item.get("highPrice") if item.get("highPrice") is not None else item.get("high"))
    low = _f(item.get("lowPrice") if item.get("lowPrice") is not None else item.get("low"))
    if last is None or last <= 0 or vol is None:
        return None
    rng_pct = None
    if high and low and last > 0 and high >= low:
        rng_pct = (high - low) / last * 100.0
    return {
        "symbol": sym,
        "price": last,
        "change_pct": float(ch or 0.0),
        "volume_usdt": float(vol),
        "high": high,
        "low": low,
        "range_pct": rng_pct,
        "qualifies_as_setup": False,
        "opens_position": False,
        "kind": KIND_SCOUT,
    }


def top_move_is_setup(change_pct: Any) -> bool:
    """Потрапляння в топ — привід дивитись, не сигнал."""
    return False


def mover_watch_reasons(row: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []
    ch = float(row.get("change_pct") or 0.0)
    vol = float(row.get("volume_usdt") or 0.0)
    rng = row.get("range_pct")
    if ch >= 5.0:
        reasons.append("top_gainer_24h")
        reasons.append("continuation_or_reversal_after_liquidity")
    if ch <= -5.0:
        reasons.append("top_loser_24h")
        reasons.append("continuation_or_reversal_after_liquidity")
    if vol >= MIN_QUOTE_VOLUME * 8:
        reasons.append("high_volume")
    if rng is not None and float(rng) >= 8.0:
        reasons.append("wide_intraday_range")
    return reasons


def already_ran_without_entry(
    *,
    direction: str,
    entry: Any,
    price: Any,
    sl: Any,
) -> bool:
    """True, якщо рух уже пройшов ~1R — не наздоганяємо."""
    side = str(direction or "").upper()
    e, p, s = _f(entry), _f(price), _f(sl)
    if None in (e, p, s) or e <= 0:
        return False
    risk = abs(e - s)
    if risk <= 0:
        return False
    if side == "LONG" and p > e + risk:
        return True
    if side == "SHORT" and p < e - risk:
        return True
    return False


@dataclass
class MarketScreen:
    data_status: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    gainers: List[Dict[str, Any]] = field(default_factory=list)
    losers: List[Dict[str, Any]] = field(default_factory=list)
    gold: Optional[Dict[str, Any]] = None
    btc: Optional[Dict[str, Any]] = None
    screened: int = 0
    note: str = ""
    opens_position: bool = False
    kind: str = KIND_SCOUT


def gold_quote_from_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    yahoo_last: Any = None,
) -> Dict[str, Any]:
    """Підтверджене джерело: спочатку Binance XAUUSDT, інакше Yahoo GC=F."""
    by = {str(r.get("symbol")): r for r in rows if isinstance(r, dict)}
    for g in GOLD_SYMBOLS:
        if g in by:
            snap = dict(by[g])
            snap["source"] = "binance_futures"
            snap["confirmed_quote"] = True
            return snap
    y = _f(yahoo_last)
    if y is not None and y > 0:
        return {
            "symbol": "XAUUSDT",
            "price": y,
            "source": f"yahoo:{GOLD_YAHOO}",
            "confirmed_quote": True,
            "qualifies_as_setup": False,
            "opens_position": False,
        }
    return {
        "symbol": "XAUUSDT",
        "source": "unavailable",
        "confirmed_quote": False,
        "data_status": DATA_UNAVAILABLE,
        "qualifies_as_setup": False,
        "opens_position": False,
    }


def screen_futures_market(
    tickers: Optional[Iterable[Any]],
    *,
    yahoo_gold_last: Any = None,
) -> MarketScreen:
    """Легкий огляд. Порожній вхід = DATA_UNAVAILABLE, не порожній топ як WR=0."""
    if tickers is None:
        return MarketScreen(
            data_status=DATA_UNAVAILABLE,
            note="немає знімка ticker/24hr — ринок не вигадуємо",
        )
    rows: List[Dict[str, Any]] = []
    for item in tickers:
        parsed = parse_ticker_row(item)
        if not parsed:
            continue
        if float(parsed["volume_usdt"]) < MIN_QUOTE_VOLUME:
            continue
        parsed["watch_reasons"] = mover_watch_reasons(parsed)
        parsed["qualifies_as_setup"] = top_move_is_setup(parsed.get("change_pct"))
        rows.append(parsed)
    if not rows:
        return MarketScreen(
            data_status=DATA_UNAVAILABLE,
            note="ticker порожній або без ліквідних USDT-перпів",
            gold=gold_quote_from_rows([], yahoo_last=yahoo_gold_last),
        )
    by_chg_desc = sorted(rows, key=lambda r: float(r["change_pct"]), reverse=True)
    by_chg_asc = sorted(rows, key=lambda r: float(r["change_pct"]))
    gold = gold_quote_from_rows(rows, yahoo_last=yahoo_gold_last)
    btc = next((r for r in rows if r["symbol"] == "BTCUSDT"), None)
    return MarketScreen(
        data_status=DATA_OK,
        rows=rows,
        gainers=by_chg_desc[:15],
        losers=by_chg_asc[:15],
        gold=gold,
        btc=btc,
        screened=len(rows),
        note="топ % зміни — WATCHING, не картка входу",
    )


def promote_for_deep_scan(
    screen: MarketScreen,
    *,
    extra_user_symbols: Optional[Sequence[str]] = None,
    active_watching: Optional[Sequence[str]] = None,
    cap: int = DEEP_SCAN_CAP,
) -> List[str]:
    """Динамічний список. Запит Тетяни — додатково. Контекст BTC/XAU завжди в глибині."""
    seen = set()
    user: List[str] = []
    auto: List[str] = []

    def _ok(sym: Any) -> str:
        s = _sym(sym)
        if not s or s in seen:
            return ""
        if not (is_usdt_perp(s) or s in GOLD_SYMBOLS or s in CONTEXT_SEEDS or s.endswith("USDT")):
            return ""
        seen.add(s)
        return s

    for s in extra_user_symbols or []:
        u = _ok(s)
        if u:
            user.append(u)
    for s in CONTEXT_SEEDS:
        u = _ok(s)
        if u:
            auto.append(u)
    for s in active_watching or []:
        u = _ok(s)
        if u:
            auto.append(u)
    if screen.data_status == DATA_OK:
        movers = list(screen.gainers[:8]) + list(screen.losers[:8])
        movers.sort(key=lambda r: abs(float(r.get("change_pct") or 0.0)), reverse=True)
        vol_sorted = sorted(screen.rows, key=lambda r: float(r.get("volume_usdt") or 0.0), reverse=True)
        for r in movers:
            u = _ok(r.get("symbol"))
            if u:
                auto.append(u)
        for r in vol_sorted[:12]:
            u = _ok(r.get("symbol"))
            if u:
                auto.append(u)
    return (user + auto)[: max(1, int(cap))]


def btc_context_only(screen: MarketScreen) -> Dict[str, Any]:
    btc = screen.btc or {}
    return {
        "symbol": "BTCUSDT",
        "change_pct": btc.get("change_pct"),
        "not_a_signal_for_alts": True,
        "copies_direction": False,
    }


def format_scout_watch_line(row: Dict[str, Any]) -> str:
    reasons = ", ".join(row.get("watch_reasons") or []) or "ліквідний перп"
    return (
        f"Скаут · {row.get('symbol')} 24h {row.get('change_pct')}% · "
        f"{reasons}. Це спостереження, не вхід."
    )

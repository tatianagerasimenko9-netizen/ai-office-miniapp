"""Paper-trading поверх сесійного радара: окремий шар від live-журналу.

Читає той самий локальний OHLCV що T6. Не пише trade_journal і не чіпає WATCHING.
kind=paper завжди. Ордерів немає.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from office_session_radar import KIND_PAPER, evaluate_session_radar, session_at_utc
from office_t6_backtest import (
    closed_asof,
    close_time,
    load_ohlcv_file,
    simulate_exit_on_bar,
)

DISCLAIMER = (
    "Це paper-звіт по файлу OHLCV, не жива угода і не запис у trade_journal."
)


@dataclass
class PaperTrade:
    kind: str = KIND_PAPER
    session: str = ""
    setup_type: str = ""
    direction: str = ""
    entry: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    outcome: str = ""
    skip_reason: str = ""
    r_multiple: float = 0.0


@dataclass
class PaperReport:
    symbol: str
    kind: str = KIND_PAPER
    disclaimer: str = DISCLAIMER
    signals: int = 0
    watching: int = 0
    skips: int = 0
    trades: List[PaperTrade] = field(default_factory=list)
    skip_reasons: Dict[str, int] = field(default_factory=dict)
    opens_live_journal: bool = False


def run_session_paper(path: str) -> PaperReport:
    data = load_ohlcv_file(path)
    symbol = str(data["symbol"])
    daily_all = data["timeframes"]["1d"]
    h1_all = data["timeframes"]["1h"]
    m15_all = data["timeframes"]["15m"]
    m5_all = data["timeframes"].get("5m") or []
    m1_all = data["timeframes"].get("1m") or []
    report = PaperReport(symbol=symbol)
    reasons: Counter[str] = Counter()
    open_t: Optional[PaperTrade] = None
    prev_dir = ""

    for bar in m15_all:
        asof = close_time(bar, "15m")
        daily = closed_asof(daily_all, "1d", asof)
        h1 = closed_asof(h1_all, "1h", asof)
        m15 = closed_asof(m15_all, "15m", asof)
        m5 = closed_asof(m5_all, "5m", asof) if m5_all else []
        m1 = closed_asof(m1_all, "1m", asof) if m1_all else []
        if open_t is not None:
            hit = simulate_exit_on_bar(
                side=open_t.direction,
                sl=open_t.sl,
                tp=open_t.tp,
                high=float(bar["high"]),
                low=float(bar["low"]),
            )
            if hit:
                open_t.outcome = "LOSS" if str(hit).startswith("SL") else "WIN"
                report.trades.append(open_t)
                prev_dir = open_t.direction
                open_t = None
            continue
        if not daily or not h1 or not m15:
            continue
        px = float(bar["close"])
        # Рівень — останній денний low як якір без look-ahead (closed daily).
        lvl = float((daily[-1] or {}).get("low") or px)
        res = evaluate_session_radar(
            symbol=symbol,
            price=px,
            level_price=lvl,
            sweep_candles=h1[-8:],
            m15_candles=m15[-8:],
            m5_candles=m5[-12:] if m5 else [],
            m1_candles=m1[-20:] if m1 else [],
            utc_now=asof,
            previous_direction=prev_dir,
            stop_hit=False,
        )
        if res.status == "WATCHING":
            report.watching += 1
            reasons[res.reason or "watching"] += 1
            continue
        if res.status != "SIGNAL" or not res.card:
            report.skips += 1
            reasons[res.reason or "skip"] += 1
            continue
        report.signals += 1
        c = res.card
        sl = float(c["sl"])
        tp = float(c.get("tp") or 0.0)
        if tp <= 0:
            report.skips += 1
            continue
        open_t = PaperTrade(
            session=res.session or session_at_utc(asof),
            setup_type=res.setup_type,
            direction=res.direction,
            entry=float(c["entry"]),
            sl=sl,
            tp=tp,
        )
    report.skip_reasons = dict(reasons)
    return report

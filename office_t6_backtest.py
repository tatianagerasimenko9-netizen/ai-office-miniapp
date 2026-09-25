"""Офлайн-бектест T6: чинний evaluate_radar, без мережі й без ордерів.

Не змінює логіку радара, журнал, WATCHING і Worker.
Результат — історична статистика на файлі OHLCV, не прогноз прибутку.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from office_radar import evaluate_radar
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT

TF_SEC = {"15m": 900, "1h": 3600, "1d": 86400}
DISCLAIMER = (
    "Це офлайн-звіт по історичному файлу, не прогноз прибутку і не дозвіл на ордери."
)


class BacktestDataError(ValueError):
    """Немає файлу, порожні/нехронологічні свічки — зупинка, без генерації даних."""


def parse_ts(raw: Any) -> datetime:
    text = str(raw or "").strip()
    if not text:
        raise BacktestDataError("свічка без ts")
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def close_time(candle: Dict[str, Any], tf: str) -> datetime:
    if tf not in TF_SEC:
        raise BacktestDataError(f"невідомий ТФ {tf}")
    return parse_ts(candle.get("ts")) + timedelta(seconds=TF_SEC[tf])


def _num(c: Dict[str, Any], key: str) -> float:
    try:
        x = float(c.get(key))
    except (TypeError, ValueError):
        raise BacktestDataError(f"погане поле {key}")
    if x <= 0:
        raise BacktestDataError(f"{key} <= 0")
    return x


def validate_series(candles: List[Dict[str, Any]], tf: str) -> None:
    if not candles:
        raise BacktestDataError(f"немає свічок {tf} — зупинка, генерації немає")
    prev: Optional[datetime] = None
    for c in candles:
        if not isinstance(c, dict):
            raise BacktestDataError(f"свічка {tf} не dict")
        t = parse_ts(c.get("ts"))
        if prev is not None and t <= prev:
            raise BacktestDataError(f"{tf} не хронологічні: {t.isoformat()} <= {prev.isoformat()}")
        prev = t
        for k in ("open", "high", "low", "close"):
            _num(c, k)
        if _num(c, "high") < _num(c, "low"):
            raise BacktestDataError(f"{tf} high < low @ {t.isoformat()}")
        if close_time(c, tf) <= t:
            raise BacktestDataError("close_time <= open")


def load_ohlcv_file(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise BacktestDataError(f"немає файлу OHLCV: {p} — зупинка, свічки не генеруємо")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BacktestDataError(f"OHLCV JSON нечитабельний: {exc}") from exc
    if not isinstance(raw, dict):
        raise BacktestDataError("корінь OHLCV має бути об'єктом")
    tfs = raw.get("timeframes")
    if not isinstance(tfs, dict):
        raise BacktestDataError("немає timeframes")
    out_tfs: Dict[str, List[Dict[str, Any]]] = {}
    for tf in ("1d", "1h", "15m"):
        rows = tfs.get(tf)
        if not isinstance(rows, list) or not rows:
            raise BacktestDataError(f"немає {tf} у файлі — зупинка")
        cleaned: List[Dict[str, Any]] = []
        for c in rows:
            if not isinstance(c, dict):
                raise BacktestDataError(f"{tf}: рядок не dict")
            cleaned.append(
                {
                    "ts": str(c.get("ts") or ""),
                    "open": _num(c, "open"),
                    "high": _num(c, "high"),
                    "low": _num(c, "low"),
                    "close": _num(c, "close"),
                    "volume": float(c.get("volume") or 0.0),
                }
            )
        validate_series(cleaned, tf)
        out_tfs[tf] = cleaned
    return {
        "symbol": str(raw.get("symbol") or "BTCUSDT").upper(),
        "source": str(raw.get("source") or ""),
        "timeframes": out_tfs,
        "bot_action": raw.get("bot_action"),
    }


def closed_asof(candles: List[Dict[str, Any]], tf: str, asof: datetime) -> List[Dict[str, Any]]:
    """Лише повністю закриті на asof свічки — без look-ahead."""
    out: List[Dict[str, Any]] = []
    for c in candles:
        if close_time(c, tf) <= asof:
            out.append(c)
        else:
            break
    return out


def day_used_pct_offline(daily: List[Dict[str, Any]]) -> Optional[float]:
    """Той самий 14-TR середнього, що fetch_atr_context, лише по закритих 1d."""
    if not isinstance(daily, list) or len(daily) < 15:
        return None
    trs: List[float] = []
    for i in range(1, len(daily)):
        cur, prev = daily[i], daily[i - 1]
        h = float(cur["high"])
        l = float(cur["low"])
        pc = float(prev["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < 14:
        return None
    atr = sum(trs[-14:]) / 14.0
    today = daily[-1]
    day_range = float(today["high"]) - float(today["low"])
    if atr <= 0:
        return None
    return day_range / atr * 100.0


def classify_skip_reason(status: str, reason: str) -> Optional[str]:
    st = str(status or "")
    r = str(reason or "")
    if st == "SIGNAL":
        return None
    if "Kill Zone" in r or "поза Kill Zone" in r:
        return "SKIP_KILL_ZONE"
    if "ATR" in r or "day_used" in r:
        return "SKIP_ATR"
    if "BLOCKED" in r:
        return "SKIP_BLOCKED"
    if "RR" in r:
        return "SKIP_RR"
    if "без підтвердження" in r or "sweep/наближення" in r:
        return "SKIP_NO_M15"
    if st == "NONE":
        return "SKIP_NONE"
    if st == "WATCHING":
        return "WATCHING"
    return "SKIP_OTHER"


@dataclass
class SimulatedTrade:
    direction: str
    entry: float
    sl: float
    tp: float
    entry_ts: str
    exit_ts: str = ""
    outcome: str = ""
    r_multiple: float = 0.0
    conservative_sl_tp: bool = False


@dataclass
class BacktestReport:
    symbol: str
    n_decisions: int = 0
    n_watching: int = 0
    n_signal: int = 0
    n_skip: int = 0
    n_trades: int = 0
    wins: int = 0
    losses: int = 0
    wr_pct: Optional[float] = None
    avg_r: Optional[float] = None
    sum_r_after_costs: float = 0.0
    max_drawdown_r: float = 0.0
    reject_reasons: Dict[str, int] = field(default_factory=dict)
    trades: List[SimulatedTrade] = field(default_factory=list)
    disclaimer: str = DISCLAIMER
    data_error: str = ""

    def as_dict(self) -> Dict[str, Any]:
        wr = "немає даних" if self.wr_pct is None else round(self.wr_pct, 2)
        avg = "немає даних" if self.avg_r is None else round(self.avg_r, 3)
        return {
            "symbol": self.symbol,
            "decisions": self.n_decisions,
            "watching": self.n_watching,
            "confirmed_setups": self.n_signal,
            "skip": self.n_skip,
            "trades": self.n_trades,
            "wins": self.wins,
            "losses": self.losses,
            "wr_pct": wr,
            "avg_r": avg,
            "sum_r_after_costs": round(self.sum_r_after_costs, 4),
            "max_drawdown_r": round(self.max_drawdown_r, 4),
            "reject_reasons": dict(self.reject_reasons),
            "disclaimer": self.disclaimer,
            "data_error": self.data_error,
        }


def _fill_price(side: str, raw_entry: float, slippage_pct: float) -> float:
    slip = max(0.0, float(slippage_pct))
    if str(side).upper() == "LONG":
        return float(raw_entry) * (1.0 + slip)
    return float(raw_entry) * (1.0 - slip)


def _hit_sl_tp(
    *,
    side: str,
    sl: float,
    tp: float,
    high: float,
    low: float,
) -> Tuple[bool, bool]:
    up = str(side).upper()
    if up == "LONG":
        return low <= sl, high >= tp
    return high >= sl, low <= tp


def simulate_exit_on_bar(
    *,
    side: str,
    sl: float,
    tp: float,
    high: float,
    low: float,
) -> Optional[str]:
    """Якщо SL і TP в одній свічці — консервативно SL."""
    hit_sl, hit_tp = _hit_sl_tp(side=side, sl=sl, tp=tp, high=high, low=low)
    if hit_sl and hit_tp:
        return "SL_CONSERVATIVE"
    if hit_sl:
        return "SL"
    if hit_tp:
        return "TP"
    return None


def run_t6_backtest(
    path: str | Path,
    *,
    commission_pct: float = 0.0004,
    slippage_pct: float = 0.0005,
) -> BacktestReport:
    data = load_ohlcv_file(path)
    symbol = str(data["symbol"])
    daily_all = data["timeframes"]["1d"]
    h1_all = data["timeframes"]["1h"]
    m15_all = data["timeframes"]["15m"]
    bot_action = data.get("bot_action")
    report = BacktestReport(symbol=symbol)
    reasons: Counter[str] = Counter()
    open_trade: Optional[SimulatedTrade] = None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    r_closed: List[float] = []

    for i, bar in enumerate(m15_all):
        asof = close_time(bar, "15m")
        daily = closed_asof(daily_all, "1d", asof)
        h1 = closed_asof(h1_all, "1h", asof)
        m15 = closed_asof(m15_all, "15m", asof)
        if open_trade is not None:
            outcome = simulate_exit_on_bar(
                side=open_trade.direction,
                sl=open_trade.sl,
                tp=open_trade.tp,
                high=float(bar["high"]),
                low=float(bar["low"]),
            )
            if outcome:
                risk = abs(open_trade.entry - open_trade.sl)
                costs = abs(open_trade.entry) * (2.0 * float(commission_pct)) 
                costs_r = (costs / risk) if risk > 0 else 0.0
                if outcome.startswith("SL"):
                    r_val = -1.0 - costs_r
                    open_trade.outcome = "LOSS"
                    report.losses += 1
                    open_trade.conservative_sl_tp = outcome == "SL_CONSERVATIVE"
                else:
                    reward = abs(open_trade.tp - open_trade.entry)
                    r_val = (reward / risk if risk > 0 else 0.0) - costs_r
                    open_trade.outcome = "WIN"
                    report.wins += 1
                open_trade.r_multiple = r_val
                open_trade.exit_ts = asof.isoformat()
                report.trades.append(open_trade)
                r_closed.append(r_val)
                equity += r_val
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
                open_trade = None
            continue

        if len(m15) < 1 or not daily or not h1:
            continue
        price = float(bar["close"])
        day_used = day_used_pct_offline(daily)
        res = evaluate_radar(
            symbol=symbol,
            price=price,
            daily_candles=daily,
            sweep_candles=h1,
            m15_candles=m15,
            day_used_pct=day_used,
            bot_action=bot_action,
            utc_now=asof,
        )
        report.n_decisions += 1
        tag = classify_skip_reason(res.status, res.reason)
        if res.status == "WATCHING":
            report.n_watching += 1
        if res.status == "SIGNAL":
            report.n_signal += 1
        if tag and tag.startswith("SKIP"):
            report.n_skip += 1
            reasons[tag] += 1
        elif tag == "WATCHING":
            reasons["WATCHING"] += 1
        elif res.status == "SIGNAL":
            reasons["SIGNAL"] += 1
        else:
            reasons[tag or res.status] += 1

        if res.status != "SIGNAL" or not res.card:
            continue
        nxt = m15_all[i + 1] if i + 1 < len(m15_all) else None
        if nxt is None:
            reasons["NO_NEXT_BAR"] += 1
            continue
        card = res.card
        side = res.direction
        raw_entry = float(card["entry"])
        fill = _fill_price(side, raw_entry, slippage_pct)
        open_trade = SimulatedTrade(
            direction=side,
            entry=fill,
            sl=float(card["sl"]),
            tp=float(card["tp"]),
            entry_ts=close_time(nxt, "15m").isoformat(),
        )

    report.reject_reasons = dict(reasons)
    report.n_trades = len(report.trades)
    report.sum_r_after_costs = equity
    report.max_drawdown_r = max_dd
    if r_closed:
        report.avg_r = sum(r_closed) / len(r_closed)
        decided = report.wins + report.losses
        report.wr_pct = (report.wins / decided * 100.0) if decided else None
    return report

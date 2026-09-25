"""T8: повний шлях WATCHING→результат + сесії, офлайн, без ордерів.

Якщо файлу OHLCV немає — DATA_UNAVAILABLE, без вигаданої торгової статистики.
Контрольний фікстурний прогін не є live WR.
Пороги ATR 80/90 і Edge 85 не змінює.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT, T0_ENTRY_BLOCK_PCT
from office_lifecycle import (
    LifecycleStep,
    LifecycleTrace,
    next_lifecycle_state,
    record_next_opportunity,
)
from office_session_radar import evaluate_session_radar, independent_flip_ok, session_at_utc
from office_t6_backtest import (
    BacktestDataError,
    closed_asof,
    close_time,
    load_ohlcv_file,
    simulate_exit_on_bar,
)
from office_t7_health import diagnose_force_order_snapshot, probe_fstream_tcp
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT, price_in_watching_zone

DISCLAIMER = (
    "T8 офлайн: картки сетапів, не ордери. CONTROL_FIXTURE не є торговою статистикою. "
    "DATA_UNAVAILABLE — чесна відсутність історичних свічок, не WR=0."
)
DATA_OK = "OK"
DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
DATA_CONTROL = "CONTROL_FIXTURE_NOT_LIVE"


@dataclass
class T8Report:
    data_status: str
    disclaimer: str = DISCLAIMER
    symbol: str = ""
    source: str = ""
    stats_are_live_trading: bool = False
    opens_orders: bool = False
    atr_80: float = GERCHIK_TREND_ENTRY_BLOCK_PCT
    atr_90: float = T0_ENTRY_BLOCK_PCT
    traces: List[LifecycleTrace] = field(default_factory=list)
    n_watching: int = 0
    n_zone_reached: int = 0
    n_confirmed: int = 0
    n_invalidated: int = 0
    n_expired: int = 0
    n_next_after_skip: int = 0
    n_flip_blocked: int = 0
    n_trades_sim: int = 0
    wins: int = 0
    losses: int = 0
    wr_pct: Optional[float] = None
    avg_r_after_costs: Optional[float] = None
    max_drawdown_r: Optional[float] = None
    skip_reasons: Dict[str, int] = field(default_factory=dict)
    by_session: Dict[str, int] = field(default_factory=dict)
    t7_health: Dict[str, Any] = field(default_factory=dict)
    note: str = ""


def _unavailable(reason: str) -> T8Report:
    return T8Report(
        data_status=DATA_UNAVAILABLE,
        note=reason,
        wr_pct=None,
        avg_r_after_costs=None,
        max_drawdown_r=None,
        stats_are_live_trading=False,
    )


def run_t8_backtest(path: str | Path | None = None) -> T8Report:
    env_path = (os.getenv("T8_OHLCV_PATH") or "").strip()
    raw_path = path if path is not None else (env_path or None)
    if not raw_path:
        return _unavailable("немає T8_OHLCV_PATH і не передано файл — свічки не генеруємо")
    p = Path(raw_path)
    if not p.is_file():
        return _unavailable(f"немає файлу OHLCV: {p} — DATA_UNAVAILABLE, не WR=0")
    try:
        data = load_ohlcv_file(p)
    except BacktestDataError as exc:
        return _unavailable(str(exc))

    symbol = str(data["symbol"])
    source = str(data.get("source") or "")
    daily_all = data["timeframes"]["1d"]
    h1_all = data["timeframes"]["1h"]
    m15_all = data["timeframes"]["15m"]
    m5_all = data["timeframes"].get("5m") or []
    m1_all = data["timeframes"].get("1m") or []
    control = "control_fixture" in source or "not_live" in source
    report = T8Report(
        data_status=DATA_CONTROL if control else DATA_OK,
        symbol=symbol,
        source=source,
        stats_are_live_trading=False,
    )
    reasons: Counter[str] = Counter()
    sessions: Counter[str] = Counter()
    traces: List[LifecycleTrace] = []
    active: Optional[LifecycleTrace] = None
    watch_low: Optional[float] = None
    watch_high: Optional[float] = None
    watch_created: Optional[datetime] = None
    prev_dir = ""
    sim_open: Optional[Dict[str, Any]] = None
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    r_closed: List[float] = []
    commission = 0.0004

    for i, bar in enumerate(m15_all):
        asof = close_time(bar, "15m")
        daily = closed_asof(daily_all, "1d", asof)
        h1 = closed_asof(h1_all, "1h", asof)
        m15 = closed_asof(m15_all, "15m", asof)
        m5 = closed_asof(m5_all, "5m", asof) if m5_all else []
        m1 = closed_asof(m1_all, "1m", asof) if m1_all else []
        sess = session_at_utc(asof)
        sessions[sess] += 1
        px = float(bar["close"])
        lvl = float((daily[-1] or {}).get("low") or px) if daily else px

        if sim_open is not None:
            hit = simulate_exit_on_bar(
                side=sim_open["direction"],
                sl=sim_open["sl"],
                tp=sim_open["tp"],
                high=float(bar["high"]),
                low=float(bar["low"]),
            )
            if hit:
                risk = abs(sim_open["entry"] - sim_open["sl"])
                costs = abs(sim_open["entry"]) * 2.0 * commission
                costs_r = (costs / risk) if risk > 0 else 0.0
                if str(hit).startswith("SL"):
                    r_val = -1.0 - costs_r
                    report.losses += 1
                    stop_hit = True
                else:
                    reward = abs(sim_open["tp"] - sim_open["entry"])
                    r_val = (reward / risk if risk > 0 else 0.0) - costs_r
                    report.wins += 1
                    stop_hit = False
                r_closed.append(r_val)
                equity += r_val
                peak = max(peak, equity)
                max_dd = max(max_dd, peak - equity)
                prev_dir = sim_open["direction"]
                sim_open = None
            else:
                stop_hit = False
                continue
        else:
            stop_hit = False

        if not daily or not h1 or not m15:
            continue
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
            stop_hit=stop_hit,
        )
        if "переворот без незалежного" in (res.reason or ""):
            report.n_flip_blocked += 1
            reasons["SKIP_FLIP_NO_CONFIRM"] += 1
        elif res.status == "WATCHING":
            reasons["WATCHING"] += 1
        elif res.status == "SIGNAL":
            reasons["SIGNAL"] += 1
        else:
            reasons[res.status or "NONE"] += 1

        if res.status in ("WATCHING", "SIGNAL") and active is None:
            active = LifecycleTrace(symbol=symbol)
            watch_low = float(res.level_price or px)
            watch_high = watch_low * 1.004
            watch_created = asof
            active.steps.append(
                LifecycleStep(
                    ts=asof.isoformat(),
                    state="WATCHING",
                    reason=res.reason or "старт сліду",
                    session=sess,
                    setup_type=res.setup_type,
                    direction=res.direction,
                )
            )
            report.n_watching += 1

        if active is not None and watch_low is not None:
            in_zone = price_in_watching_zone(px, watch_low, watch_high)
            confirmed = res.status == "SIGNAL" and not res.entry_blocked
            invalidated = bool(
                flip_invalid := (
                    prev_dir
                    and res.direction
                    and prev_dir != res.direction
                    and not independent_flip_ok(
                        previous_direction=prev_dir,
                        new_direction=res.direction,
                        sweep=(res.extras or {}).get("sweep") or {},
                        m5_ok=True if res.status == "SIGNAL" else False,
                        m1_ok=False,
                        stop_hit=stop_hit,
                    )
                )
            )
            atr_ex = (res.extras or {}).get("atr") if isinstance(res.extras, dict) else None
            day_used = None
            if isinstance(atr_ex, dict):
                day_used = atr_ex.get("day_used_pct")
            step = next_lifecycle_state(
                current=active.terminal or "WATCHING",
                price=px,
                entry_low=watch_low,
                entry_high=watch_high,
                created_ts=watch_created,
                now_ts=asof,
                confirmed=confirmed,
                entry_blocked=bool(res.entry_blocked),
                day_used_pct=day_used,
                invalidated=invalidated,
            )
            if step["state"] != active.terminal:
                active.steps.append(
                    LifecycleStep(
                        ts=asof.isoformat(),
                        state=step["state"],
                        reason=step["reason"],
                        session=sess,
                        setup_type=res.setup_type,
                        direction=res.direction,
                    )
                )
                if step["state"] == "ZONE_REACHED":
                    report.n_zone_reached += 1
                if step["state"] == "CONFIRMED":
                    report.n_confirmed += 1
                    if res.card and sim_open is None:
                        c = res.card
                        if c.get("tp") and c.get("sl"):
                            sim_open = {
                                "direction": res.direction,
                                "entry": float(c["entry"]),
                                "sl": float(c["sl"]),
                                "tp": float(c["tp"]),
                            }
                            report.n_trades_sim += 1
                    traces.append(active)
                    prev_dir = res.direction
                    active = None
                    watch_low = None
                elif step["state"] in ("EXPIRED", "INVALIDATED"):
                    if step["state"] == "EXPIRED":
                        report.n_expired += 1
                    else:
                        report.n_invalidated += 1
                    traces.append(active)
                    active = None
                    watch_low = None
            elif in_zone and active.terminal == "WATCHING":
                pass

        if active is None and res.status in ("WATCHING", "SIGNAL") and traces:
            last = traces[-1]
            if last.next_opportunity is None and last.terminal in (
                "EXPIRED",
                "INVALIDATED",
                "CONFIRMED",
            ):
                record_next_opportunity(
                    last,
                    ts=asof.isoformat(),
                    setup_type=res.setup_type,
                    direction=res.direction,
                    session=sess,
                    reason="наступна можливість після закриття сліду",
                )
                report.n_next_after_skip += 1

    if active is not None:
        traces.append(active)
    report.traces = traces
    report.skip_reasons = dict(reasons)
    report.by_session = dict(sessions)
    if r_closed:
        report.avg_r_after_costs = sum(r_closed) / len(r_closed)
        decided = report.wins + report.losses
        report.wr_pct = (report.wins / decided * 100.0) if decided else None
        report.max_drawdown_r = max_dd
    report.t7_health = {
        "probe": probe_fstream_tcp(),
        "idle_example": diagnose_force_order_snapshot(
            {"connected": False, "reconnects": 0, "last_error": "", "loop_started": False}
        ),
    }
    if control:
        report.note = "CONTROL_FIXTURE_NOT_LIVE — не торгова статистика, лише трасування шляху"
    return report


def traces_to_rows(report: T8Report) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for tr in report.traces:
        rows.append(
            {
                "symbol": tr.symbol,
                "path": " → ".join(s.state for s in tr.steps),
                "terminal": tr.terminal,
                "next_opportunity": bool(tr.next_opportunity),
                "opens_position": tr.opens_position,
                "steps": [
                    {"ts": s.ts, "state": s.state, "reason": s.reason, "session": s.session}
                    for s in tr.steps
                ],
            }
        )
    return rows

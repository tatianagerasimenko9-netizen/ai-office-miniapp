"""Одноразова shadow-перевірка воронки скану на ЖИВИХ даних production (результат — у БД, подія LAUNCH_DIAG, task=funnel_check; без змінних).

Лише читання й запис події в журнал: Telegram, ордерів і записів сигналів немає. Показує:
  · скільки РІЗНИХ монет реально проходять глибокий аналіз (за цикл і за N циклів ротації) — Gainers і Losers окремо;
  · скільки монет у PULLBACK WATCH (по статусах) і скільки звичайних WATCHING;
  · реальний прохід одного циклу глибокого аналізу (дії Лева, скільки відхилено через RR/T0, скільки зупинив напрям після сильного руху);
  · чи технічно проходить увесь шлях до READY сценарій з RR ≥ 1,5 після комісій (тестовий сценарій через ті самі гейти)."""
from __future__ import annotations

import json
import time
import urllib.request
from collections import Counter
from typing import Any, Dict, List

VERSION = "funnel-check-2026-10-01"


def _done(db: str) -> bool:
    from office_bridge import _fetchall

    try:
        rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT 300", ("LAUNCH_DIAG",))
    except Exception:  # noqa: BLE001
        return False
    for r in rows or []:
        try:
            p = json.loads(r[0]) if isinstance(r[0], str) else dict(r[0])
        except (TypeError, ValueError):
            continue
        if p.get("version") == VERSION and p.get("task") == "funnel_check_done":
            return True
    return False


def ready_path_proof() -> Dict[str, Any]:
    """Тестовий валідний сценарій (структурні цілі) проходить ті самі гейти, що й READY: RR після комісій ≥ 1,5."""
    from datetime import datetime, timezone

    import office_alert_gate as G
    import office_lev_targets as LT
    import office_scenario_state as S
    from office_lev_watch import check_plan

    e, sl = 100.0, 98.0
    legacy = e + 1.5 * (e - sl)
    pick = LT.pick_targets(direction="LONG", entry=e, sl=sl, levels=[(102.4, "свінг H1"), (106.0, "рівень попереднього дня")], min_tp1_pct=1.2)
    plan = {"entry": e, "sl": sl, "tp1": pick.get("tp1"), "tp2": pick.get("tp2")}
    import office_calendar as cal

    saved = cal.entry_block
    cal.entry_block = lambda *a, **k: None   # перевірка шляху не залежить від календаря
    try:
        bad = check_plan("BTCUSDT", "LONG", plan, 99.6, 100.4)
        bad_legacy = check_plan("BTCUSDT", "LONG", {"entry": e, "sl": sl, "tp1": legacy, "tp2": None}, 99.6, 100.4)
        now = datetime.now(timezone.utc)
        row = {"signal_id": "SCN|DEMO|1", "symbol": "BTCUSDT", "direction": "LONG", "entry_low": 99.6, "entry_high": 100.4, "sl": sl, "tp1": plan["tp1"], "tp2": plan["tp2"],
               "status": "CONFIRMED", "ts_created": now.isoformat(), "ts_updated": now.isoformat(),
               "analysis_note": f"ЛЕВ cancel={sl} confirm_sent=1 confirmed_px={e} tf=H1"}
        v = S.build(row, thesis={"invalidation": "закриття нижче стопа", "confirmation": "M15"},
                    price={"price": e, "as_of": now.isoformat(), "fresh": True, "source": "binance_futures"}, plan_check=check_plan, now=now)
    finally:
        cal.entry_block = saved
    g = G.rr_gate(e, sl, plan["tp1"], plan["tp2"])
    return {"targets_ok": bool(pick.get("ok")), "tp1": plan["tp1"], "tp2": plan["tp2"], "rr_weighted_net": round(g.get("rr_weighted") or 0, 2), "rr_tp1_net": round(g.get("rr_net") or 0, 2),
            "final_gate_pass": bad is None, "ready_state": v.get("state"), "legacy_1_5R_gross_rejected": bad_legacy is not None,
            "legacy_reason": bad_legacy}


def _tickers() -> List[Dict[str, Any]]:
    req = urllib.request.Request("https://fapi.binance.com/fapi/v1/ticker/24hr", headers={"User-Agent": "office-funnel-check"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
        return json.loads(r.read().decode())


def run_once(db: str, printer=print, deep_limit: int = 36) -> bool:
    if _done(db):
        return False
    from office_bridge import log_event

    def put(task: str, payload: Dict[str, Any]) -> None:
        log_event(db, "LAUNCH_DIAG", {"version": VERSION, "task": task, "at": time.time(), **payload})

    import office_scan_funnel as F
    from office_market_scout import screen_futures_market

    try:
        put("funnel_ready_path", ready_path_proof())
    except Exception as exc:  # noqa: BLE001
        put("funnel_ready_path", {"error": f"{type(exc).__name__}: {exc}"})
    try:
        screen = screen_futures_market(_tickers())
        if screen.data_status != "DATA_OK":
            put("funnel_check", {"error": "немає знімка ticker/24hr"})
            return False
        now = time.time()
        st = F.FunnelState()
        st.pullbacks = {k: dict(v) for k, v in F.STATE.pullbacks.items()}   # як у живому реєстрі
        for r in screen.rows:
            if abs(float(r.get("change_pct") or 0.0)) >= F.EXTENDED_PCT:
                F.register_pullback(r["symbol"], r, reason="сильний рух", now=now, state=st)
        F.update_pullbacks(screen.rows, now, st)
        watching: List[str] = []
        try:
            from office_bridge import signal_get_active

            watching = [str(a.get("symbol")) for a in (signal_get_active(db) or []) if isinstance(a, dict) and a.get("symbol")]
        except Exception:  # noqa: BLE001
            watching = []
        # 1) Симуляція ротації: скільки циклів, щоб весь universe пройшов глибокий аналіз; без запитів до біржі
        sim = F.FunnelState(pullbacks=st.pullbacks)
        seen, tiers_first, t, cycles = set(), None, now, 0
        distinct_per_cycle: List[int] = []
        while cycles < 80:
            ch = F.select_deep(screen.rows, screen.gainers, screen.losers, active_watching=watching, now=t, state=sim)
            if tiers_first is None:
                tiers_first = F.counts_report(ch, sim)
                first_sel = ch
            for c in ch:
                F.mark_deep(c["symbol"], t, sim)
                seen.add(c["symbol"])
            distinct_per_cycle.append(len(seen))
            cycles += 1
            t += 600
            if len(seen) >= screen.screened - len(sim.pullbacks):
                break
        gain = [c["symbol"] for c in first_sel if c["tier"] == "gainers"]
        lose = [c["symbol"] for c in first_sel if c["tier"] == "losers"]
        put("funnel_check", {"universe": screen.screened, "cap": F.CAP, "first_cycle": tiers_first, "gainers_first_cycle": gain, "losers_first_cycle": lose,
                             "cycles_to_cover_universe": cycles, "covered_distinct": len(seen), "distinct_after_cycles": distinct_per_cycle[:12],
                             "pullback_watch": {"total": len(st.pullbacks), "by_status": F.counts_report(first_sel, st)["pullback_by_status"], "symbols": sorted(st.pullbacks)[:30]},
                             "watching_ordinary": len({w for w in watching if w not in st.pullbacks}), "watching_total": len(set(watching))})
        # 2) Реальний прохід ОДНОГО циклу глибокого аналізу (як у скауті), без записів сигналів
        from office_market_data import fetch_atr_context, fetch_candles
        from office_lev_verdict import lev_cycle
        from office_trade_steer import atr_from_candles

        rows_by = {str(r["symbol"]): r for r in screen.rows}
        actions: Counter = Counter()
        reasons: Counter = Counter()
        gate_hold = 0
        analyzed: List[str] = []
        for c in first_sel[:deep_limit]:
            sym = c["symbol"]
            try:
                d1, h4, h1 = fetch_candles(sym, "1d", 30), fetch_candles(sym, "4h", 30), fetch_candles(sym, "1h", 30)
                m15, m5 = fetch_candles(sym, "15m", 96), fetch_candles(sym, "5m", 20)
                if not isinstance(h1, list) or len(h1) < 8:
                    actions["NO_DATA"] += 1
                    continue
                used = None
                try:
                    used = float((fetch_atr_context(sym) or {}).get("day_used_pct"))
                except (TypeError, ValueError):
                    used = None
                cyc = lev_cycle(symbol=sym, price=float(h1[-1].get("close") or 0), timeframe="H1", candles_m5=m5, candles_m15=m15, candles_h1=h1, candles_h4=h4,
                                candles_d1=d1, candles_ltf=m5 if isinstance(m5, list) else m15, atr_h1=atr_from_candles(h1), day_used_pct=used,
                                market_context={"data_status": "DATA_UNAVAILABLE"})
                analyzed.append(sym)
                act = str(cyc.get("action") or "?")
                imp = F.impulse_of(rows_by.get(sym) or {})
                if imp and cyc.get("direction") in ("LONG", "SHORT") and act in ("SEND", "WAIT", "WATCHING"):
                    ok, _w = F.direction_gate(str(cyc["direction"]), imp, reversal_ok=F.reversal_confirmed(h1, imp))
                    if not ok:
                        gate_hold += 1
                        act = "WATCHING(напрям після сильного руху)"
                actions[act] += 1
                if act in ("SKIP",):
                    reasons[str(cyc.get("reason") or "")[:60]] += 1
            except Exception as exc:  # noqa: BLE001
                actions[f"ERR_{type(exc).__name__}"] += 1
        put("funnel_deep_pass", {"analyzed_distinct": len(set(analyzed)), "actions": dict(actions), "skip_reasons": dict(reasons.most_common(8)), "direction_gate_hold": gate_hold})
    except Exception as exc:  # noqa: BLE001
        put("funnel_check", {"error": f"{type(exc).__name__}: {exc}"})
    put("funnel_check_done", {})
    printer("[funnel-check] виконано")
    return True

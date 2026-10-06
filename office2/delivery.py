"""Доставка Office2 READY у Telegram через ті самі канали, що й старий READY (send_proactive: ідемпотентність, ledger), і запис у lifecycle (SIGNAL_PLAN).

Після доставки office_signal_track/monitor_scenario_milestones самі ведуть ENTRY/TP1/TP2/TP3/SL/EXPIRED для цього плану (за confirm_msg_id).
Функції приймають залежності аргументами (send, fetch, render), тож весь ланцюг перевіряється офлайн.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

LABEL = "OFFICE2 · LIVE BETA"
# Окремий пул потоків: загальний пул asyncio.to_thread у worker зайнятий хвилинними запитами старого трекера до Binance,
# і доставка Office2 стояла в черзі 10–14 хв (рішення о 14:32, відправка о 14:53). Власний пул не залежить від чужих задач.
import concurrent.futures as _cf
import functools as _ft

O2_EXECUTOR = _cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="o2-live")


async def run_o2(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    import asyncio

    return await asyncio.get_running_loop().run_in_executor(O2_EXECUTOR, _ft.partial(fn, *args, **kw))
STALE_PENDING_SEC = 25 * 60       # READY, не доставлений за 25 хв, уже неактуальний: не шлемо із запізненням
MAX_PER_PASS = 3


def delivery_enabled() -> bool:
    import os

    return os.getenv("OFFICE2_LIVE_DELIVERY", "").strip().lower() in ("1", "true", "yes", "on")


def build_caption(snap: Dict[str, Any]) -> str:
    """Telegram: за 3–5 секунд. Лише числа з рішення; без «ринок сильний». Рівні — з office2.levels (та сама математика, що в Mini App)."""
    import office_ready_card as card
    import office_ready_core as rc
    from office_user_messages import ticker
    from office2 import levels as LVL

    th = snap["thesis"]
    sym = snap["symbol"]
    v = LVL.view_from_thesis(th)
    if not v:
        raise ValueError("немає рівнів тези")
    n = lambda x: card._num(x, sym)  # noqa: E731
    L = [LABEL, f"{'🟢 LONG' if snap['direction'] == 'LONG' else '🔴 SHORT'} · {ticker(sym)}"]
    if snap.get("why"):
        L.append(f"Чому: {snap['why']}")
    L.append("")
    L.append(f"READY: {n(v['ready_price'])}")
    if v["zone"]:
        L.append(f"Зона входу: {n(v['zone'][0])}–{n(v['zone'][1])}")
    L.append(f"Стоп: {n(v['sl'])}" + LVL.pct_txt(v["sl_pct"], "−"))
    for i, t in enumerate(v["targets"][:3], 1):
        L.append(f"TP{i}: {n(t['p'])}" + LVL.pct_txt(t["pct"], "+"))
    if (th.get("sizing") or {}).get("risk_usd"):
        L.append(f"Ризик: {float(th['sizing']['risk_usd']):.0f} $" + (" (від READY-ціни)" if v["zone"] else ""))
    L.append(f"⏳ до {rc.kyiv_stamp(snap['valid_until_ts'])}")
    return "\n".join(L)


def build_gate(snap: Dict[str, Any]) -> Dict[str, Any]:
    import office_ready_core as rc

    th = snap["thesis"]
    tg = th.get("targets") or []
    t = lambda i: (tg[i]["p"] if len(tg) > i else None)  # noqa: E731
    trig = float(th.get("trigger_level") or th["entry"])
    g = rc.gate_snapshot(direction=snap["direction"], entry=th["entry"], sl=th["sl"], tp1=t(0), tp2=t(1), tp3=t(2), zone_lo=min(trig, th["entry"]), zone_hi=max(trig, th["entry"]))
    g["office2"] = {"label": LABEL, "brain": snap.get("brain"), "evidence_status": snap.get("evidence_status"), "scenario": th.get("id"), "trace": snap.get("trace"), "why": snap.get("why")}
    return g


def _late_reason(snap: Dict[str, Any], fetch: Callable[[str, str, int], Any], sym: str, direction: str) -> Optional[str]:
    """Свіжа ціна (1m) перед відправкою: якщо вона за структурним SL або втекла далі за MAX_CHASE_R від рівня тригера — READY не шлемо."""
    from office2 import brain as B

    th = snap["thesis"]
    try:
        rows = fetch(sym, "1m", 2)
        px = float(rows[-1]["close"]) if isinstance(rows, list) and rows else None
    except Exception:  # noqa: BLE001
        px = None
    if px is None:
        return None   # немає свіжої ціни: рішення за закритим баром лишається в силі (стале за часом відсікається окремо)
    sl, entry = float(th["sl"]), float(th["entry"])
    risk = abs(entry - sl)
    long_ = direction == "LONG"
    if (long_ and px <= sl) or ((not long_) and px >= sl):
        return f"ціна {px:.6g} уже за структурним SL {sl:.6g}"
    trig = float(th.get("trigger_level") or entry)
    chase = ((px - trig) if long_ else (trig - px)) / risk if risk > 0 else 0.0
    if chase > B.MAX_CHASE_R:
        return f"на момент доставки ціна {px:.6g} уже {chase:.2f} R від рівня {trig:.6g}: вхід пізній (MISSED)"
    return None


async def deliver_pending(db: str, send: Callable[..., Awaitable[Optional[int]]], fetch: Callable[[str, str, int], Any], render: Callable[..., Dict[str, Any]],
                          event_type: str, now: Optional[float] = None, log: Callable[[str], None] = print) -> int:
    """Один прохід по outbox. Повертає число доставлених. Помилка одного сигналу не зачіпає інші."""
    import asyncio
    import tempfile
    import os

    import office_signal_track as trk
    from office_bridge import _execute, _fetchall, log_event

    t = time.time() if now is None else now
    rows = await run_o2(_fetchall, db, "SELECT scenario_id, symbol, direction, created_ts, valid_until_ts, snapshot_json FROM office2_live_signal WHERE status = 'PENDING' ORDER BY created_ts ASC LIMIT ?", (MAX_PER_PASS,))
    sent = 0
    for sid, sym, d, created, valid, sj in rows:
        if t - float(created) > STALE_PENDING_SEC or t > float(valid):
            await run_o2(_execute, db, "UPDATE office2_live_signal SET status = 'SUPPRESSED', last_error = ? WHERE scenario_id = ?", ("не доставлено вчасно", sid))
            log(f"[office2] suppressed stale {sid}")
            continue
        try:
            snap = json.loads(sj)
            snap["valid_until_ts"] = float(valid)
            why_late = await run_o2(_late_reason, snap, fetch, sym, d)
            if why_late:   # no-chase і структурна інвалідація перевіряються ще раз у момент доставки (рішення могло застаріти за час циклу)
                await run_o2(_execute, db, "UPDATE office2_live_signal SET status = 'SUPPRESSED', last_error = ? WHERE scenario_id = ?", (why_late[:300], sid))
                log(f"[office2] suppressed at delivery {sym} {d}: {why_late}")
                continue
            cap = build_caption(snap)
            th = snap["thesis"]
            tg = th.get("targets") or []
            candles = await run_o2(fetch, sym, "15m", 96)
            import office_ready_evidence as evd

            chart = evd.freeze_chart(candles if isinstance(candles, list) else [], t, "15m", symbol=sym)
            trig = float(th.get("trigger_level") or th["entry"])
            img: Dict[str, Any] = {}
            try:
                img = await run_o2(render, symbol=sym, direction=d, candles=evd.candles_from_chart(chart) if chart.get("candles") else (candles if isinstance(candles, list) else []),
                                              entry=th["entry"], zone=[min(trig, th["entry"]), max(trig, th["entry"])], sl=th["sl"], tp1=(tg[0]["p"] if tg else None), tp2=(tg[1]["p"] if len(tg) > 1 else None),
                                              tp3=(tg[2]["p"] if len(tg) > 2 else None), ready_price=th["entry"], key_level=trig, key_label="пробій" if th["kind"] == "PULLBACK_BREAK" else "рівень",
                                              path=os.path.join(tempfile.gettempdir(), f"o2ready_{sym}_{int(t)}.png"))
            except Exception as exc_img:  # noqa: BLE001
                img = {"ok": False, "reason": f"{type(exc_img).__name__}: {exc_img}"}
            mid = await send(event_type, cap, symbol=sym, kind="CONFIRM", intent="CONFIRM", canonical_id=sid, scenario_event="CONFIRM", photo_path=str(img.get("path") or "") if img.get("ok") else "")
            if not mid:
                await run_o2(_execute, db, "UPDATE office2_live_signal SET last_error = ? WHERE scenario_id = ?", ("Telegram не підтвердив доставку", sid))
                log(f"[office2] delivery not verified {sid}: лишаю для повтору")
                continue
            gate = build_gate(snap)
            gate["chart"] = chart
            tf = "M15"
            await run_o2(trk.record_plan, db, scenario_id=sid, symbol=sym, direction=d, tf=tf, entry=th["entry"], sl=th["sl"], tp1=(tg[0]["p"] if tg else None),
                                    tp2=(tg[1]["p"] if len(tg) > 1 else None), tp3=(tg[2]["p"] if len(tg) > 2 else None), max_entry=None, confirmed_ts=float(created),
                                    valid_until_ts=float(valid), rejected=False, confirm_msg_id=mid, gate=gate)
            await run_o2(_execute, db, "UPDATE office2_live_signal SET status = 'DELIVERED', msg_id = ?, delivered_ts = ?, last_error = NULL WHERE scenario_id = ?", (int(mid), t, sid))
            await run_o2(log_event, db, "OFFICE2_READY_SENT", {"scenario_id": sid, "symbol": sym, "direction": d, "text": cap, "telegram_msg_id": mid, "image_ok": bool(img.get("ok")),
                                                                         "image_error": None if img.get("ok") else img.get("reason"), "chart_sha256": chart.get("sha256")}, sid)
            sent += 1
            log(f"[office2] READY delivered {sym} {d} id={mid}")
        except Exception as exc:  # noqa: BLE001
            log(f"[office2] delivery error {sid}: {type(exc).__name__}: {exc}")
            try:
                await run_o2(_execute, db, "UPDATE office2_live_signal SET last_error = ? WHERE scenario_id = ?", (f"{type(exc).__name__}: {exc}"[:300], sid))
            except Exception:  # noqa: BLE001
                pass
    return sent

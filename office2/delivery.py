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
MAX_PER_PASS = 6
_INFLIGHT: set = set()             # сигнали, що вже відправляються: наступні проходи (кожні 2 с) їх не чіпають і не чекають на них
LATE_NOTE_SEC = 150               # доставка пізніше за 2,5 хв від закриття бару — у підписі є позначка про запізнення


def delivery_enabled() -> bool:
    import os

    return os.getenv("OFFICE2_LIVE_DELIVERY", "").strip().lower() in ("1", "true", "yes", "on")


def build_caption(snap: Dict[str, Any], now: Optional[float] = None) -> str:
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
    entry, sl = float(v["ready_price"]), float(v["sl"])
    risk = abs(entry - sl)
    pc = lambda p: f"{abs(p - entry) / entry * 100:.2f}".replace(".", ",")    # noqa: E731  один відсоток — від ціни READY
    rr = lambda p: f"{abs(p - entry) / risk:.2f}".replace(".", ",") if risk > 0 else "—"    # noqa: E731
    L.append(f"READY: {n(entry)}")
    if v["zone"]:
        L.append(f"Зона входу: {n(v['zone'][0])}–{n(v['zone'][1])}")
    L.append(f"SL: {n(sl)} (−{pc(sl)}%)")
    for i, t in enumerate(v["targets"][:3], 1):
        L.append(f"TP{i}: {n(t['p'])} (+{pc(t['p'])}%; {rr(t['p'])}R)")
    if (th.get("sizing") or {}).get("risk_usd"):
        L.append(f"Ризик моделі: {float(th['sizing']['risk_usd']):.0f} $")
    decided = float(snap.get("decided_ts") or 0.0)
    if now and decided and now - decided >= LATE_NOTE_SEC:      # чесно про запізнення доставки (сигнал не подається як свіжий)
        L.append(f"⏱ Рішення було о {rc.kyiv_stamp(decided)}; доставлено через {int((now - decided) // 60)} хв")
    L.append(f"⏳ до {rc.kyiv_stamp(snap['valid_until_ts'])}")
    return "\n".join(L)


def build_gate(snap: Dict[str, Any]) -> Dict[str, Any]:
    import office_ready_core as rc

    th = snap["thesis"]
    tg = th.get("targets") or []
    t = lambda i: (tg[i]["p"] if len(tg) > i else None)  # noqa: E731
    from office2 import levels as LVL

    zl, zh = LVL.zone_of(th)
    g = rc.gate_snapshot(direction=snap["direction"], entry=th["entry"], sl=th["sl"], tp1=t(0), tp2=t(1), tp3=t(2), zone_lo=zl, zone_hi=zh)
    g["office2"] = {"label": LABEL, "brain": snap.get("brain"), "evidence_status": snap.get("evidence_status"), "scenario": th.get("id"), "trace": snap.get("trace"), "why": snap.get("why")}
    return g


def _late_reason(snap: Dict[str, Any], fetch: Callable[[str, str, int], Any], sym: str, direction: str, now: Optional[float] = None) -> Optional[str]:
    """Перед відправкою: що сталося з цінею ВІД МОМЕНТУ РІШЕННЯ (1m-свічки, їхні high/low, а не лише остання ціна).
    SL торкнули після рішення → сценарій зламано (не шлемо); ціна пішла далі за MAX_CHASE_R від рівня тригера → вхід пізній (MISSED)."""
    from office2 import brain as B
    from office_patterns import _ts as _iso

    def _ts(v: Any) -> Optional[float]:
        if isinstance(v, (int, float)):
            return float(v / 1000.0 if v > 1e11 else v)
        return _iso(v)

    th = snap["thesis"]
    t = time.time() if now is None else now
    decided = float(snap.get("decided_ts") or 0.0)
    n = 2 if not decided else max(2, min(1000, int((t - decided) // 60) + 3))
    try:
        rows = fetch(sym, "1m", n)
    except Exception:  # noqa: BLE001
        rows = None
    if not isinstance(rows, list) or not rows:
        return "DATA_UNAVAILABLE: missing 1m candles"
    since = [r for r in rows if isinstance(r, dict) and (not decided or (_ts(r.get("ts")) is not None and float(_ts(r["ts"])) >= decided - 1))]
    if not since:
        return "DATA_UNAVAILABLE: no candles since decision"
    try:
        px = float(rows[-1]["close"])
        hi = max(float(r["high"]) for r in since)
        lo = min(float(r["low"]) for r in since)
    except (KeyError, TypeError, ValueError):
        return "DATA_UNAVAILABLE: malformed 1m candles"
    sl, entry = float(th["sl"]), float(th["entry"])
    risk = abs(entry - sl)
    long_ = direction == "LONG"
    if (long_ and lo <= sl) or ((not long_) and hi >= sl):
        ext = lo if long_ else hi
        return f"після рішення ціна вже торкнулась структурного SL {sl:.6g} (екстремум {ext:.6g}): сценарій зламано до відправки (INVALIDATED)"
    trig = float(th.get("trigger_level") or entry)
    fav = hi if long_ else lo
    chase = max(((px - trig) if long_ else (trig - px)), ((fav - trig) if long_ else (trig - fav))) / risk if risk > 0 else 0.0
    if chase > B.MAX_CHASE_R:
        return f"на момент доставки ціна {px:.6g} (екстремум {fav:.6g}) уже {chase:.2f} R від рівня {trig:.6g}: вхід пізній (MISSED)"
    return None


def _close_scenario(db: str, sid: str, state: str, reason: str, now: float) -> None:
    """Сценарій, який не можна слати як свіжий READY (ціна втекла / SL торкнуто / застарів), закривається з причиною: Radar і статистика бачать MISSED/INVALIDATED, а не «READY, який не дійшов»."""
    from office_bridge import _execute, _fetchone
    from office2.webview import parent_id

    parent = parent_id(sid)
    row = _fetchone(db, "SELECT state FROM office2_live_scenario WHERE scenario_id = ?", (parent,))
    if not row:
        return
    _execute(db, "UPDATE office2_live_scenario SET state = ?, reason = ?, updated_ts = ? WHERE scenario_id = ?", (state, reason[:400], now, parent))
    _execute(db, "INSERT INTO office2_live_transition(scenario_id, ts, from_state, to_state, reason, version) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING", (parent, now, row[0], state, reason[:400], "o2-delivery"))


async def deliver_pending(db: str, send: Callable[..., Awaitable[Optional[int]]], fetch: Callable[[str, str, int], Any], render: Callable[..., Dict[str, Any]],
                          event_type: str, now: Optional[float] = None, log: Callable[[str], None] = print) -> int:
    """Один прохід по outbox. Повертає число доставлених. Помилка одного сигналу не зачіпає інші."""
    import asyncio
    import tempfile
    import os

    import office_signal_track as trk
    from office_bridge import _execute, _fetchall, log_event

    clk = (lambda: float(now)) if now is not None else time.time     # у тестах «зараз» фіксоване
    rows = await run_o2(_fetchall, db, "SELECT scenario_id, symbol, direction, created_ts, valid_until_ts, snapshot_json FROM office2_live_signal WHERE status = 'PENDING' ORDER BY created_ts ASC LIMIT ?", (MAX_PER_PASS,))
    rows = [r for r in rows if r[0] not in _INFLIGHT]
    _INFLIGHT.update(r[0] for r in rows)

    async def _one_guarded(row: tuple) -> int:
        try:
            return await _one(row)
        finally:
            _INFLIGHT.discard(row[0])

    async def _one(row: tuple) -> int:
        sid, sym, d, created, valid, sj = row
        t_pick = clk()
        if t_pick - float(created) > STALE_PENDING_SEC or t_pick > float(valid):
            why = f"STALE: не доставлено за {int(t_pick - float(created))} с (ліміт {STALE_PENDING_SEC} с) або строк дії вийшов"
            await run_o2(_execute, db, "UPDATE office2_live_signal SET status = 'SUPPRESSED', last_error = ? WHERE scenario_id = ?", (why[:300], sid))
            await run_o2(_close_scenario, db, sid, "MISSED", why, t_pick)
            log(f"[office2] suppressed stale {sid}")
            return 0
        try:
            snap = json.loads(sj)
            snap["valid_until_ts"] = float(valid)
            lat = snap.get("latency") or {}
            emitted = float(snap.get("emitted_wall_ts") or 0.0) or None
            tm: Dict[str, Any] = {"pickup_s": round(t_pick - emitted, 1) if emitted else None}
            # 1) свічки для знімка графіка: беремо з рішення (ctx циклу); REST лише для старих знімків без chart_candles
            t_a = time.time()
            candles = snap.get("chart_candles")
            if not (isinstance(candles, list) and candles):
                candles = await run_o2(fetch, sym, "15m", 96)
            tm["chart_ms"] = int((time.time() - t_a) * 1000)
            import office_ready_evidence as evd

            chart = evd.freeze_chart(candles if isinstance(candles, list) else [], t_pick, "15m", symbol=sym)
            from office2 import levels as LVL

            th = snap["thesis"]
            tg = th.get("targets") or []
            zl, zh = LVL.zone_of(th)
            trig = float(th.get("trigger_level") or th["entry"])

            async def _render() -> Dict[str, Any]:
                t_r = time.time()
                try:
                    out = await run_o2(render, symbol=sym, direction=d, candles=evd.candles_from_chart(chart) if chart.get("candles") else (candles if isinstance(candles, list) else []),
                                       entry=th["entry"], zone=[zl, zh], sl=th["sl"], tp1=(tg[0]["p"] if tg else None), tp2=(tg[1]["p"] if len(tg) > 1 else None),
                                       tp3=(tg[2]["p"] if len(tg) > 2 else None), ready_price=th["entry"], key_level=trig, key_label="пробій" if th["kind"] == "PULLBACK_BREAK" else "рівень",
                                       path=os.path.join(tempfile.gettempdir(), f"o2ready_{sym}_{int(t_pick)}.png"))
                except Exception as exc_img:  # noqa: BLE001
                    out = {"ok": False, "reason": f"{type(exc_img).__name__}: {exc_img}"}
                tm["render_ms"] = int((time.time() - t_r) * 1000)
                return out

            # 2) перевірка «ціна вже втекла / SL торкнуто» і малювання картки йдуть паралельно (картка відкидається, якщо сигнал уже неактуальний)
            t_a = time.time()
            img_task = asyncio.ensure_future(_render())
            why_late = await run_o2(_late_reason, snap, fetch, sym, d, clk())
            tm["late_check_ms"] = int((time.time() - t_a) * 1000)
            if why_late and why_late.startswith("DATA_UNAVAILABLE:"):
                img_task.cancel()
                await run_o2(_execute, db, "UPDATE office2_live_signal SET last_error = ? WHERE scenario_id = ?", (why_late[:300], sid))
                log(f"[office2] retry pending {sid}: {why_late}")
                return 0
            if why_late:   # no-chase і структурна інвалідація перевіряються ще раз у момент доставки (рішення могло застаріти за час циклу)
                img_task.cancel()
                state = "INVALIDATED" if "(INVALIDATED)" in why_late else "MISSED"
                await run_o2(_execute, db, "UPDATE office2_live_signal SET status = 'SUPPRESSED', last_error = ? WHERE scenario_id = ?", (f"{state}: {why_late}"[:300], sid))
                await run_o2(_close_scenario, db, sid, state, why_late, clk())
                log(f"[office2] suppressed at delivery {sym} {d}: {why_late}")
                return 0
            img = await img_task
            cap = build_caption(snap, now=clk())
            t_a = time.time()
            mid = await send(event_type, cap, symbol=sym, kind="CONFIRM", intent="CONFIRM", canonical_id=sid, scenario_event="CONFIRM", photo_path=str(img.get("path") or "") if img.get("ok") else "")
            t_sent = time.time()
            tm["send_ms"] = int((t_sent - t_a) * 1000)
            if not mid:
                await run_o2(_execute, db, "UPDATE office2_live_signal SET last_error = ? WHERE scenario_id = ?", ("Telegram не підтвердив доставку", sid))
                log(f"[office2] delivery not verified {sid}: лишаю для повтору")
                return 0
            # повна хронологія в мс: закриття бару → пробудження → бар доступний → старт → дані → рішення → черга → Telegram
            bar_close = lat.get("bar_close") or snap.get("decided_ts")
            ms = lambda a_, b_: (int((float(b_) - float(a_)) * 1000) if a_ is not None and b_ is not None else None)  # noqa: E731
            tm.update(bar_close_ts=bar_close, wake_ms=ms(bar_close, lat.get("wake")), bar_wait_ms=ms(lat.get("wake"), lat.get("bar_ready")), fetch_ms=ms(lat.get("cycle_start"), lat.get("fetch_done")),
                      brain_ms=ms(lat.get("fetch_done"), emitted), queue_ms=ms(emitted, t_pick), sent_wall_ts=t_sent,
                      bar_to_sent_ms=ms(bar_close, t_sent), decision_to_sent_ms=ms(emitted, t_sent))
            tm["fetch_s"] = round(tm["chart_ms"] / 1000, 1)
            tm["late_check_s"] = round(tm["late_check_ms"] / 1000, 1)
            tm["render_s"] = round(tm.get("render_ms", 0) / 1000, 1)
            tm["send_s"] = round(tm["send_ms"] / 1000, 1)
            tm["emit_to_sent_s"] = round(t_sent - emitted, 1) if emitted else None
            gate = build_gate(snap)
            gate["chart"] = chart
            tf = "M15"
            await run_o2(trk.record_plan, db, scenario_id=sid, symbol=sym, direction=d, tf=tf, entry=th["entry"], sl=th["sl"], tp1=(tg[0]["p"] if tg else None),
                                    tp2=(tg[1]["p"] if len(tg) > 1 else None), tp3=(tg[2]["p"] if len(tg) > 2 else None), max_entry=None, confirmed_ts=float(created),
                                    valid_until_ts=float(valid), rejected=False, confirm_msg_id=mid, gate=gate)
            await run_o2(_execute, db, "UPDATE office2_live_signal SET status = 'DELIVERED', msg_id = ?, delivered_ts = ?, last_error = NULL WHERE scenario_id = ?", (int(mid), t_sent, sid))
            await run_o2(log_event, db, "OFFICE2_READY_SENT", {"scenario_id": sid, "symbol": sym, "direction": d, "text": cap, "telegram_msg_id": mid, "image_ok": bool(img.get("ok")),
                                                                         "image_error": None if img.get("ok") else img.get("reason"), "chart_sha256": chart.get("sha256"), "timing": tm}, sid)
            log(f"[office2] READY delivered {sym} {d} id={mid} timing={tm}")
            return 1
        except Exception as exc:  # noqa: BLE001
            log(f"[office2] delivery error {sid}: {type(exc).__name__}: {exc}")
            try:
                await run_o2(_execute, db, "UPDATE office2_live_signal SET last_error = ? WHERE scenario_id = ?", (f"{type(exc).__name__}: {exc}"[:300], sid))
            except Exception:  # noqa: BLE001
                pass
            return 0
    # сигнали з одного проходу доставляються паралельно: повільна відправка одного (Telegram іноді 2–3 хв) не затримує інші
    results = await asyncio.gather(*[_one_guarded(r) for r in rows], return_exceptions=True)
    sent = sum(r for r in results if isinstance(r, int))
    return sent

"""Office 2.0 LIVE: рушій сценаріїв. Тримає стан у часі (WATCH → WAIT → READY | NO_TRADE | MISSED | INVALIDATED), портфельний ризик, заморожений знімок рішення, outbox для Telegram.

Нічого не шле сам: READY кладе у office2_live_signal (PENDING); доставку й запис у lifecycle робить office2/delivery.py у процесі worker.
Знімок READY заморожений (snapshot_json) і ніколи не переписується; поточний стан порівнюється з ним у Mini App ('ринок зараз' окремо).
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

import os

from office2 import brain as B
from office2 import brain2 as B2
from office2 import risk as RK

BRAIN_V2 = os.environ.get("OFFICE2_BRAIN", "2") != "1"   # OFFICE2_BRAIN=1 — відкат до brain v1 (thesis A/B)

VERSION = "o2-live-1"
TTL_SEC = {"WATCH": 8 * 3600, "WAIT": 6 * 3600}
READY_VALID_SEC = 6 * 3600     # строк дії READY (≈ H1-плану старого Лева 6 год)
RISK_USD = 10.0
MAX_READY_PER_DAY = 8
LIVE_STATES = ("WATCH", "WAIT")
ALL_STATES = ("WATCH", "WAIT", "READY", "NO_TRADE", "MISSED", "INVALIDATED", "EXPIRED")
COOLDOWN_SEC = 12 * 3600       # завершений сценарій тієї ж тези не відновлюється раніше за 12 год

DDL = (
    """CREATE TABLE IF NOT EXISTS office2_live_scenario (
        scenario_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
        created_ts DOUBLE PRECISION NOT NULL, updated_ts DOUBLE PRECISION NOT NULL, expires_ts DOUBLE PRECISION, reason TEXT, thesis_json TEXT NOT NULL, version TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS office2_live_transition (
        scenario_id TEXT NOT NULL, ts DOUBLE PRECISION NOT NULL, from_state TEXT, to_state TEXT NOT NULL, reason TEXT, version TEXT NOT NULL,
        PRIMARY KEY (scenario_id, ts, to_state))""",
    """CREATE TABLE IF NOT EXISTS office2_live_signal (
        scenario_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, created_ts DOUBLE PRECISION NOT NULL, valid_until_ts DOUBLE PRECISION NOT NULL,
        status TEXT NOT NULL, msg_id BIGINT, delivered_ts DOUBLE PRECISION, last_error TEXT, snapshot_json TEXT NOT NULL, version TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS office2_brain_funnel (
        ts BIGINT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, stage TEXT NOT NULL, code TEXT, version TEXT NOT NULL,
        PRIMARY KEY (ts, symbol, direction, version))""",
)

FUNNEL_KEEP_SEC = 7 * 86400


def funnel_stage(th: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """Етап воронки Brain для (символ, напрям) на цьому циклі: (stage, code відсіву). Лише з поля тези, без вигадок."""
    if not th:
        return "NO_EVENT", ""
    st, rs = th.get("state"), str(th.get("reason") or "")
    if st == "WAIT":
        if rs.startswith("WAIT 1/3"):
            return "WAIT_1_SHIFT", "нога замала" if "нога зміщення" in rs else "чекаємо зсув"
        if rs.startswith("WAIT 2/3"):
            return "WAIT_2_ZONE", "глибокий ретрейс" if "глибокий ретрейс" in rs else "чекаємо ретрейс"
        if rs.startswith("WAIT 3/3"):
            return "ARMED_3", "чекаємо тригер M15"
        return "WAIT_OTHER", rs[:40]
    if st == "NO_TRADE":
        code = ("простір до цілі" if "першої реальної цілі" in rs else "стоп у шумі" if "всередині нормального шуму" in rs else "стоп поза %-діапазоном" if "поза допустимим" in rs
                else "немає цілі" if "немає реальної цілі" in rs else "ціна за інвалідацією" if "за структурною інвалідацією" in rs else "ємність/портфель" if "ємність" in rs else "інше")
        return "NO_TRADE", code
    if st == "MISSED":
        return "MISSED", "пішла без ретрейсу"
    if st == "INVALIDATED":
        return "INVALIDATED", "ретрейс зламав структуру" if "ретрейс зламав" in rs else "умови тези зникли"
    return str(st or "?"), ""


def init_db(db: str) -> None:
    from office_bridge import _execute

    for d in DDL:
        _execute(db, d)


def _j(o: Any) -> str:
    return json.dumps(_clean(o), ensure_ascii=False)


def _clean(o: Any) -> Any:
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def load_scenarios(db: str, symbol: Optional[str] = None, states: Tuple[str, ...] = LIVE_STATES) -> Dict[str, Dict[str, Any]]:
    from office_bridge import _fetchall

    q = "SELECT scenario_id, symbol, direction, kind, state, created_ts, updated_ts, expires_ts, reason, thesis_json FROM office2_live_scenario WHERE state IN (%s)" % ",".join("?" for _ in states)
    args: list = list(states)
    if symbol:
        q += " AND symbol = ?"
        args.append(symbol)
    out = {}
    for r in _fetchall(db, q, tuple(args)):
        out[r[0]] = {"scenario_id": r[0], "symbol": r[1], "direction": r[2], "kind": r[3], "state": r[4], "created_ts": r[5], "updated_ts": r[6], "expires_ts": r[7], "reason": r[8],
                     "thesis": json.loads(r[9] or "{}")}
    return out


def save_scenario(db: str, sym: str, th: Dict[str, Any], state: str, now: float, created: Optional[float], prev: Optional[str], reason: str) -> None:
    from office_bridge import _execute

    exp = now + TTL_SEC.get(state, 0) if state in TTL_SEC else None
    _execute(db, """INSERT INTO office2_live_scenario(scenario_id, symbol, direction, kind, state, created_ts, updated_ts, expires_ts, reason, thesis_json, version)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT (scenario_id) DO UPDATE SET state=excluded.state, updated_ts=excluded.updated_ts, expires_ts=excluded.expires_ts, reason=excluded.reason, thesis_json=excluded.thesis_json""",
             (th["id"], sym, th["dir"], th["kind"], state, created or now, now, exp, reason[:400], _j(th), brain_version()))
    if prev != state:
        _execute(db, "INSERT INTO office2_live_transition(scenario_id, ts, from_state, to_state, reason, version) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                 (th["id"], now, prev, state, reason[:400], brain_version()))


# ------------------------------------------------------------------ портфельний ризик
def open_signals(db: str, now: float) -> List[Dict[str, Any]]:
    """ЄМНІСТЬ СЦЕНАРІЇВ Office2 (скільки сценаріїв Office показує одночасно), а НЕ особистий ризик власниці: той починається лише після «Я відкрила угоду».
    Рахуємо лише реально живі: ДОСТАВЛЕНІ (строк не вийшов, немає SL/TP3/EXPIRED у lifecycle) і свіжі PENDING, що ще чекають доставки (≤ STALE_PENDING_SEC).
    SUPPRESSED, а також PENDING, які вчасно не доставлені (призраки), місця не займають."""
    from office_bridge import _fetchall
    from office2.delivery import STALE_PENDING_SEC

    rows = _fetchall(db, "SELECT scenario_id, symbol, direction, created_ts, valid_until_ts, snapshot_json FROM office2_live_signal "
                         "WHERE valid_until_ts > ? AND (status = 'DELIVERED' OR (status = 'PENDING' AND created_ts > ?))", (now, now - STALE_PENDING_SEC))
    done = set()
    try:
        for (sid,) in _fetchall(db, "SELECT DISTINCT signal_id FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id LIKE 'O2|%' AND (payload_json LIKE '%\"level\": \"SL\"%' OR payload_json LIKE '%\"level\": \"TP3\"%' OR payload_json LIKE '%\"level\": \"EXPIRED\"%')"):
            done.add(sid)
    except Exception:  # noqa: BLE001
        pass
    out = []
    for sid, sym, d, ct, vu, sj in rows:
        if sid in done:
            continue
        lvl = (json.loads(sj or "{}").get("thesis") or {}).get("level") or {}
        out.append({"scenario_id": sid, "symbol": sym, "direction": d, "created_ts": ct, "valid_until_ts": vu, "lvl_key": f"{sym}|{d}|{round(float(lvl.get('p') or 0), 6)}" if lvl.get("p") else None})
    return out


def day_stops(db: str, now: float) -> int:
    from office_bridge import _fetchall

    t0 = now - (now % 86400)
    n = 0
    try:
        for (pj,) in _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = 'SCENARIO_MILESTONE' AND signal_id LIKE 'O2|%' ORDER BY id DESC LIMIT 200"):
            p = json.loads(pj or "{}")
            if p.get("level") == "SL" and float(p.get("sent_ts") or 0) >= t0:
                n += 1
    except Exception:  # noqa: BLE001
        return 0
    return n


def portfolio_gate(db: str, sym: str, direction: str, lvl_key: Optional[str], now: float, cfg: RK.RiskConfig = RK.RiskConfig()) -> Optional[str]:
    """None = можна; інакше причина відмови (NO_TRADE). Ті самі правила, що в Risk Manager (shadow-перевірений код)."""
    op = open_signals(db, now)
    risk_open = len(op) * cfg.risk_usd
    if risk_open + cfg.risk_usd > cfg.max_open_risk_usd:
        return f"ємність сценаріїв Office2: {risk_open + cfg.risk_usd:.0f}$ > {cfg.max_open_risk_usd:.0f}$ (не твій особистий ризик)"
    cl = RK.cluster_of(sym)
    same_cluster = [o for o in op if RK.cluster_of(o["symbol"]) == cl]
    if (len(same_cluster) + 1) * cfg.risk_usd > cfg.max_cluster_open_risk_usd:
        return f"ємність сценаріїв кластера {cl}: {(len(same_cluster) + 1) * cfg.risk_usd:.0f}$ > {cfg.max_cluster_open_risk_usd:.0f}$ ({len(same_cluster)} активних сценаріїв Office2; не твій особистий ризик)"
    if cl == "ALT" and sum(1 for o in same_cluster if o["direction"] == direction) + 1 > cfg.max_same_direction_alts:
        return f"вже {cfg.max_same_direction_alts} альтів у напрямі {direction}"
    if any(o["symbol"] == sym for o in op):
        return "по цій монеті вже є живий сигнал Office2"
    if lvl_key and any(o["lvl_key"] == lvl_key for o in op):
        return "та сама ідея/рівень уже в роботі"
    if day_stops(db, now) >= int(cfg.daily_loss_r):
        return f"денний ліміт: {int(cfg.daily_loss_r)} стопи за добу UTC"
    from office_bridge import _fetchone

    t0 = now - (now % 86400)
    r = _fetchone(db, "SELECT COUNT(*) FROM office2_live_signal WHERE created_ts >= ? AND status <> 'SUPPRESSED'", (t0,))
    if r and int(r[0]) >= MAX_READY_PER_DAY:
        return f"денний ліміт кількості: {MAX_READY_PER_DAY} READY за добу UTC (READY не має бути частим заради активності)"
    return None


# ------------------------------------------------------------------ знімок і крок
def market_for_signal(mc: Dict[str, Any], st: Dict[str, Any], rel: Dict[str, Any]) -> Dict[str, Any]:
    return {"market": mc, "coin": {k: st.get(k) for k in ("price", "ret_1h", "ret_4h", "ret_24h", "atr15_pct", "vol_regime_7d", "pos_24h_range")}, "relative": rel}


def why_text(th: Dict[str, Any], mc: Dict[str, Any], rel: Dict[str, Any], symbol: str) -> str:
    """1–2 числові причини для Telegram (без прикрас)."""
    def n(x: Any, d: int = 2) -> str:
        return f"{x:.{d}f}".replace(".", ",")

    def px(x: float) -> str:
        from office_price_format import format_px

        return format_px(x, symbol).replace(".", ",")

    parts = []
    if th["kind"] in ("SWEEP_SEQ", "ORIGIN_SEQ"):
        ok = [x for x in (th.get("sequence") or []) if x.get("ok")]
        ez = th.get("entry_zone") or th.get("zone")
        lv = th.get("level") or {}
        parts.append(f"{'Sweep' if th['kind'] == 'SWEEP_SEQ' else 'Захист зони'} {lv.get('kind', '')} {px(lv['p']) if lv.get('p') else ''} → зсув структури → ретрейс у зону {px(ez[0])}–{px(ez[1])} → тригер M15 ({len(ok)} кроків пройдено).")
    elif th["kind"] == "PULLBACK_BREAK":
        z = th["zone"]
        a = th["attacks"]
        parts.append(f"Після імпульсу +{n(th['impulse']['size_pct'], 1)}% відкат {n(th['retrace'] * 100, 0)}% тримається в зоні {px(z[0])}–{px(z[1])} ({a['n']} атак); "
                     f"M15 закрився вище {px(th['break']['level'])} (свічка {n(th['break']['body_atr'], 1)} ATR) і втримав {th['break']['bars_held']} бар.")
        if th["dir"] == "SHORT":
            parts[0] = parts[0].replace("Після імпульсу +", "Після імпульсу −").replace("закрився вище", "закрився нижче")
    else:
        lv = th["level"]
        parts.append(f"Sweep {lv['kind']} {px(lv['p'])} (до {px(th['sweep']['extreme'])}) і повернення M15 {'вище' if th['dir'] == 'LONG' else 'нижче'} рівня, утримано {th['bars_held'] if 'bars_held' in th else 1} бар.")
    b, c, r = mc.get("btc_ret_1h"), rel.get("coin_ret_1h"), rel.get("rs_vs_btc_1h")
    if b is not None and c is not None and r is not None:
        sg = lambda v: ("+" if v >= 0 else "−") + n(abs(v), 2)  # noqa: E731
        parts.append(f"BTC {sg(b)}% / 1г; монета {sg(c)}%; відносно {sg(r)} п.п.")
    return " ".join(parts[:2])


def scoped_id(sym: str, tid: str) -> str:
    """Стабільний id сценарію В МЕЖАХ СИМВОЛУ: той самий thesis-id на різних монетах (однаковий напрям/вид/час події) не повинен збігатися."""
    import hashlib

    return "O2|" + hashlib.sha256(f"{sym}|{tid}".encode()).hexdigest()[:12]


def brain_version() -> str:
    return B2.VERSION if BRAIN_V2 else B.VERSION


def stage_tag(reason: Any) -> str:
    """«WAIT 2/3» з тексту причини brain2 (порожньо для v1/інших станів)."""
    import re

    m = re.match(r"^WAIT (\d)/3", str(reason or ""))
    return f"WAIT {m.group(1)}/3" if m else ""


def record_funnel(db: str, sym: str, rows: list, now: float) -> None:
    """Один INSERT на символ (кожне Postgres-з'єднання дороге); ts = закритий бар. Старе чистимо раз на цикл (на BTC)."""
    from office_bridge import _execute

    ts = int(now)
    vals, args = [], []
    for d, stage, code in rows:
        vals.append("(?,?,?,?,?,?)")
        args += [ts, sym, d, stage, code, brain_version()]
    _execute(db, "INSERT INTO office2_brain_funnel(ts, symbol, direction, stage, code, version) VALUES " + ",".join(vals) + " ON CONFLICT DO NOTHING", tuple(args))
    if sym == "BTCUSDT":
        _execute(db, "DELETE FROM office2_brain_funnel WHERE ts < ?", (ts - FUNNEL_KEEP_SEC,))


def step_symbol(db: str, sym: str, ctx: Dict[str, Any], st: Dict[str, Any], mc: Dict[str, Any], rel: Dict[str, Any], now: float, old_lev: Optional[Dict[str, Any]] = None,
                allow_ready: bool = True, flow_fetch: Optional[Callable[[], Dict[str, Any]]] = None, m5_fetch: Optional[Callable[[], Any]] = None) -> Dict[str, int]:
    """Один символ на закритому барі: детектори → переходи. Повертає лічильники переходів."""
    res = {"watch": 0, "wait": 0, "ready": 0, "no_trade": 0, "missed": 0, "invalidated": 0, "expired": 0}
    allsc = load_scenarios(db, sym, ALL_STATES)
    live = {k: v for k, v in allsc.items() if v["state"] in LIVE_STATES}
    levels = B.all_levels(ctx, now)
    found: Dict[str, Dict[str, Any]] = {}
    funnel: list = []
    for d in ("LONG", "SHORT"):
        if BRAIN_V2:
            th = B2.thesis(ctx, d, now, levels, RISK_USD)
            if th:
                th = dict(th, id=scoped_id(sym, th["id"]), symbol=sym)   # id теза-незалежний від монети збігався б між символами на одному барі → перезапис чужих сценаріїв
                found[th["id"]] = th
            funnel.append((d, *funnel_stage(th)))
            continue
        for th in (B.pullback_break(ctx, d, now), B.reclaim_thesis(ctx, d, now, levels)):
            if th:
                found[th["id"]] = B.decide(th, ctx, now, RISK_USD)
    if funnel:
        try:
            record_funnel(db, sym, funnel, now)
        except Exception as exc:  # noqa: BLE001
            print(f"[funnel] {sym}: {type(exc).__name__}: {str(exc)[:100]}", flush=True)
    # один живий сценарій на (символ, напрям, вид): якщо детектор бачить новий id цього ж виду — старий WATCH/WAIT закривається як застарілий
    for sid, sc in list(live.items()):
        if sid not in found:
            if now > float(sc["expires_ts"] or 0):
                save_scenario(db, sym, sc["thesis"], "EXPIRED", now, sc["created_ts"], sc["state"], "час очікування минув")
                res["expired"] += 1
            elif not any(f["dir"] == sc["direction"] and f["kind"] == sc["kind"] for f in found.values()):
                save_scenario(db, sym, sc["thesis"], "INVALIDATED", now, sc["created_ts"], sc["state"], "умови тези більше не виконуються")
                res["invalidated"] += 1
    for sid, th in found.items():
        prev = live.get(sid)
        old = allsc.get(sid)
        if prev is None and old is not None and now - float(old["updated_ts"]) < COOLDOWN_SEC:
            continue   # цю тезу вже завершено (READY/NO_TRADE/MISSED/...): не відкриваємо повторно
        state = th["state"]
        if prev is None and state in ("INVALIDATED",):
            continue   # мертву тезу не створюємо
        if state in ("WATCH", "WAIT"):
            if prev is None or prev["state"] != state or prev["thesis"].get("reason") != th.get("reason"):
                save_scenario(db, sym, th, state, now, prev["created_ts"] if prev else None, prev["state"] if prev else None, th.get("reason", ""))
                if prev is not None and prev["state"] == state == "WAIT":   # перехід етапу всередині WAIT (1/3 → 2/3 → 3/3) лишає слід: потрібен для конверсії воронки
                    a, b = stage_tag(prev.get("reason") or prev["thesis"].get("reason")), stage_tag(th.get("reason"))
                    if a and b and a != b:
                        from office_bridge import _execute

                        _execute(db, "INSERT INTO office2_live_transition(scenario_id, ts, from_state, to_state, reason, version) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                                 (th["id"], now, a, b, str(th.get("reason", ""))[:400], brain_version()))
                res[state.lower()] += 1 if (prev is None or prev["state"] != state) else 0
            continue
        if prev is None and state in ("READY", "NO_TRADE", "MISSED"):
            # тези, що одразу «готові» без WATCH/WAIT у БД, фіксуємо з історією: створюємо WAIT-запис, потім перехід
            save_scenario(db, sym, th, "WAIT", now - 1, None, None, "теза сформована")
            prev = {"state": "WAIT", "created_ts": now - 1}
        if state == "READY":
            if not allow_ready:
                save_scenario(db, sym, th, "NO_TRADE", now, prev["created_ts"], prev["state"], "READY заблоковано перемикачем доставки")
                res["no_trade"] += 1
                continue
            lvl_key = f"{sym}|{th['dir']}|{round(float((th.get('level') or {}).get('p') or th.get('trigger_level') or 0), 6)}"
            deny = portfolio_gate(db, sym, th["dir"], lvl_key, now)
            if deny:
                th = dict(th, state="NO_TRADE", reason="ємність сценаріїв: " + deny)
                save_scenario(db, sym, th, "NO_TRADE", now, prev["created_ts"], prev["state"], th["reason"])
                res["no_trade"] += 1
                continue
            emit_ready(db, sym, th, ctx, st, mc, rel, now, old_lev, flow_fetch, m5_fetch)
            save_scenario(db, sym, th, "READY", now, prev["created_ts"], prev["state"], th.get("reason", ""))
            res["ready"] += 1
        else:
            save_scenario(db, sym, th, {"NO_TRADE": "NO_TRADE", "MISSED": "MISSED", "INVALIDATED": "INVALIDATED"}[state], now, prev["created_ts"], prev["state"], th.get("reason", ""))
            res[state.lower()] += 1
    return res


def emit_ready(db: str, sym: str, th: Dict[str, Any], ctx: Dict[str, Any], st: Dict[str, Any], mc: Dict[str, Any], rel: Dict[str, Any], now: float, old_lev: Optional[Dict[str, Any]],
               flow_fetch: Optional[Callable[[], Dict[str, Any]]] = None, m5_fetch: Optional[Callable[[], Any]] = None) -> None:
    from office_bridge import _execute

    pack = B.context_pack(ctx, now)
    if callable(old_lev):
        try:
            old_lev = old_lev()
        except Exception:  # noqa: BLE001
            old_lev = None
    why = why_text(th, mc, rel, sym)
    from office2 import align as AL

    aligned = AL.alignment(th["dir"], mc, rel, pack.get("htf"))
    evid = []
    if th.get("kind") in ("SWEEP_SEQ", "ORIGIN_SEQ"):
        try:
            from office2 import evidence as EV

            evid = EV.collect(ctx, th, th["dir"], now, B.all_levels(ctx, now), flow_fetch=flow_fetch, m5_fetch=m5_fetch)
        except Exception as exc:  # noqa: BLE001
            evid = [{"module": "evidence", "role": "EVIDENCE", "status": "UNAVAILABLE", "finding": f"{type(exc).__name__}: {str(exc)[:80]}", "supports": 0, "data": None}]
    snap = {"version": VERSION, "brain": brain_version(), "version_id": brain_version(), "evidence": evid, "evidence_counts": (__import__("office2.evidence", fromlist=["summary"]).summary(evid) if evid else None),
            "sequence": th.get("sequence"), "evidence_status": B.EVIDENCE_STATUS, "label": "OFFICE2 · LIVE BETA", "decided_ts": now, "emitted_wall_ts": time.time(), "decided_utc": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
            "symbol": sym, "direction": th["dir"], "thesis": th, "why": why, "context": pack, "market_at_signal": market_for_signal(mc, st, rel), "alignment": aligned, "alignment_summary": AL.summary(aligned), "old_lev": old_lev,
            "trace": [
                {"step": "HTF context", "value": {k: (v.get("trend") if isinstance(v, dict) else v) for k, v in pack["htf"].items()}},
                {"step": "BTC/ETH/market", "value": mc},
                {"step": "узгодженість факторів з напрямом (ЗА/ПРОТИ)", "value": aligned},
                {"step": "key levels / liquidity", "value": pack["liquidity"]},
                {"step": "послідовність (подія → зсув → ретрейс → тригер)", "value": th.get("sequence")},
                {"step": "модулі: ЗА/ПРОТИ/недоступно (GATE/CONTEXT/EVIDENCE/RESEARCH)", "value": evid},
                {"step": "POI / зона входу", "value": th.get("entry_zone") or th.get("zone")},
                {"step": "price behaviour", "value": {"attacks": th.get("attacks"), "compression": th.get("compression"), "sweep": th.get("sweep"), "reclaim": th.get("reclaim")}},
                {"step": "local structure/trigger", "value": th.get("break") or th.get("reclaim")},
                {"step": "structural invalidation", "value": th.get("invalidation")},
                {"step": "SL", "value": th.get("sl")},
                {"step": "targets", "value": th.get("targets")},
                {"step": "перевірки якості (стоп vs шум M15, запас до першої реальної цілі)", "value": th.get("quality")},
                {"step": "risk", "value": th.get("sizing")},
                {"step": "decision", "value": "READY (LIVE BETA, UNPROVEN)"}]}
    _execute(db, """INSERT INTO office2_live_signal(scenario_id, symbol, direction, created_ts, valid_until_ts, status, snapshot_json, version) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
             (th["id"] + f"|{int(now)}", sym, th["dir"], now, now + READY_VALID_SEC, "PENDING", _j(snap), brain_version()))

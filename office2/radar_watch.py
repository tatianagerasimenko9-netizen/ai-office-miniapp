"""Живий WATCH/PAPER-радар: видимі торгові картки з ринку «зараз», окремо від LIVE READY.

Що це: Brain v2.1 щоцикла веде сценарії WAIT 1/3→3/3. Для 2/3 і 3/3 (ціна біля зони входу) і для would-be READY, відсічених лімітом ємності (BLOCKED),
фіксується КАРТКА з планом-орієнтиром: зона, вхід (середина зони), SL, TP1–TP3 від реальних рівнів, причина, строк дії. Нічого з цього не READY і не ордер:
  WATCH   — сценарій ще не завершив послідовність (чекає ретрейс/тригер M15); план проходить ті самі геометричні фільтри READY (ризик %, шум ATR, простір до цілі);
  BLOCKED — READY-рівень, який відсік захист (ліміт стопів/ємність): показуємо, чому, і ведемо paper «що було б»; захист не послаблюється;
  READY   — окремий LIVE-потік (office2.delivery), тут лише позначка PROMOTED.
Супровід: paper-симуляція за свічками Binance ПІСЛЯ появи картки (вхід — лише лімітом на ціні входу, SL першим у спірній свічці, витрати 0.15 %), без заглядання в майбутнє.
У Telegram іде короткий WATCH-пост лише для ARMED 3/3 і BLOCKED (антиспам: ≤ N/год, ≤ M/добу, 1 картка на монету/4 год), з позначкою «не вхід».
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

VERSION = "radar-1"
TTL_SEC = 4 * 3600
TRACK_MAX_AGE_SEC = 48 * 3600
TG_PER_HOUR = 4
TG_PER_DAY = 12
TG_SYMBOL_COOLDOWN_SEC = 4 * 3600
TG_MAX_TRIES = 3
BLOCK_PREFIX = "ємність сценаріїв"

DDL = ("""CREATE TABLE IF NOT EXISTS office2_radar_card (
    card_id TEXT PRIMARY KEY, kind TEXT NOT NULL, scenario_id TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, stage TEXT,
    created_ts DOUBLE PRECISION NOT NULL, updated_ts DOUBLE PRECISION, expires_ts DOUBLE PRECISION, zone_lo DOUBLE PRECISION, zone_hi DOUBLE PRECISION,
    entry DOUBLE PRECISION, sl DOUBLE PRECISION, tp1 DOUBLE PRECISION, tp2 DOUBLE PRECISION, tp3 DOUBLE PRECISION, risk_pct DOUBLE PRECISION,
    level_kind TEXT, level_price DOUBLE PRECISION, need_text TEXT, reason TEXT, plan_ok INTEGER DEFAULT 0, reject TEXT, scen_state TEXT,
    tg_status TEXT DEFAULT 'NEW', tg_tries INTEGER DEFAULT 0, msg_id BIGINT, sent_ts DOUBLE PRECISION, last_error TEXT, notified TEXT,
    paper_status TEXT, entry_ts DOUBLE PRECISION, exit_ts DOUBLE PRECISION, reached TEXT, r_net DOUBLE PRECISION, gate_reason TEXT, version TEXT)""",)
_COLS = ("card_id", "kind", "scenario_id", "symbol", "direction", "stage", "created_ts", "updated_ts", "expires_ts", "zone_lo", "zone_hi", "entry", "sl", "tp1", "tp2", "tp3", "risk_pct",
         "level_kind", "level_price", "need_text", "reason", "plan_ok", "reject", "scen_state", "tg_status", "tg_tries", "msg_id", "sent_ts", "last_error", "notified",
         "paper_status", "entry_ts", "exit_ts", "reached", "r_net", "gate_reason", "version")
_READY: set = set()
_TMP = tempfile.gettempdir()      # один раз при імпорті: у циклі подій виклик gettempdir блокував його на 3 с (loop-lag у production)


def tg_enabled() -> bool:
    return os.getenv("OFFICE2_RADAR_TG", "1").strip().lower() not in ("0", "false", "no", "off")


def _ensure(db: str) -> None:
    if db in _READY:
        return
    from office_bridge import _execute

    for d in DDL:
        _execute(db, d)
    _READY.add(db)


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def stage_of(state: str, reason: Any) -> Optional[str]:
    if state == "NO_TRADE" and str(reason or "").startswith(BLOCK_PREFIX):
        return "BLOCKED"
    m = re.match(r"^WAIT (\d)/3", str(reason or ""))
    if state == "WAIT" and m:
        return {"3": "ARMED", "2": "RETRACE"}.get(m.group(1))        # 1/3 (ще немає структури) карток не створює
    return None


def plan_of(th: Dict[str, Any]) -> Dict[str, Any]:
    """План картки: повний (READY-рівень, відсічений ємністю/знижений до WAIT) або preview Brain (орієнтир). Нічого не вигадуємо: немає цілей → plan_ok=0."""
    tg = th.get("targets") or []
    if th.get("entry") is not None and th.get("sl") is not None and tg:
        entry, sl, tgs, risk_pct, ok, rej = _f(th["entry"]), _f(th["sl"]), tg, _f(th.get("risk_pct")), True, None
    else:
        pv = th.get("preview") or {}
        ok = bool(pv.get("ok"))
        entry, sl, tgs, risk_pct, rej = _f(pv.get("entry")), _f(pv.get("sl")), pv.get("targets") or [], _f(pv.get("risk_pct")), pv.get("reject") or ("preview відсутній" if not pv else None)
    z = th.get("entry_zone") or th.get("zone") or [None, None]
    tp = lambda i: _f(tgs[i]["p"]) if len(tgs) > i else None  # noqa: E731
    ok = bool(ok and entry and sl and tp(0))
    return {"entry": entry, "sl": sl, "tp1": tp(0), "tp2": tp(1), "tp3": tp(2), "risk_pct": risk_pct, "plan_ok": 1 if ok else 0, "reject": None if ok else (rej or "план неповний"),
            "zone_lo": _f(min(z)) if z and None not in z else None, "zone_hi": _f(max(z)) if z and None not in z else None}


def sync(db: str, now: Optional[float] = None) -> Dict[str, int]:
    """Створює/оновлює картки зі стану сценаріїв Brain. План зафіксований (не повзе за ціною) після відправки в Telegram або входу paper."""
    from office_bridge import _execute, _fetchall

    t = time.time() if now is None else now
    _ensure(db)
    out = {"new": 0, "updated": 0}
    rows = _fetchall(db, "SELECT scenario_id, symbol, direction, kind, state, reason, updated_ts, thesis_json FROM office2_live_scenario "
                         "WHERE (state = 'WAIT' AND updated_ts > ?) OR (state = 'NO_TRADE' AND reason LIKE ? AND updated_ts > ?) ORDER BY updated_ts", (t - 2400, BLOCK_PREFIX + "%", t - 3 * 3600))
    for sid, sym, d, kind, state, reason, upd, tj in rows:
        st = stage_of(state, reason)
        if not st:
            continue
        try:
            th = json.loads(tj or "{}")
        except ValueError:
            continue
        pl = plan_of(th)
        lvl = th.get("level") or {}
        need = (th.get("need") or {}).get("text")
        k = "BLOCKED" if st == "BLOCKED" else "WATCH"
        cid = ("B|" if k == "BLOCKED" else "W|") + sid
        ex = _fetchall(db, "SELECT tg_status, paper_status FROM office2_radar_card WHERE card_id = ?", (cid,))
        if not ex:
            vals = {"card_id": cid, "kind": k, "scenario_id": sid, "symbol": sym, "direction": d, "stage": st, "created_ts": float(upd), "updated_ts": float(upd), "expires_ts": float(upd) + TTL_SEC,
                    **pl, "level_kind": lvl.get("kind"), "level_price": _f(lvl.get("p")), "need_text": need, "reason": str(reason or "")[:400], "scen_state": state,
                    "tg_status": "NEW", "tg_tries": 0, "gate_reason": str(reason or "")[:160] if k == "BLOCKED" else None, "version": VERSION}
            _execute(db, f"INSERT INTO office2_radar_card({','.join(_COLS)}) VALUES ({','.join('?' for _ in _COLS)}) ON CONFLICT (card_id) DO NOTHING", tuple(vals.get(c) for c in _COLS))
            out["new"] += 1
            continue
        tg_status, paper = ex[0]
        if tg_status == "NEW" and not paper:      # план ще не опублікований і не в paper — оновлюємо до найточнішого (ARMED точніший за RETRACE)
            _execute(db, "UPDATE office2_radar_card SET stage=?, updated_ts=?, zone_lo=?, zone_hi=?, entry=?, sl=?, tp1=?, tp2=?, tp3=?, risk_pct=?, plan_ok=?, reject=?, need_text=?, reason=?, scen_state=? WHERE card_id=?",
                     (st, float(upd), pl["zone_lo"], pl["zone_hi"], pl["entry"], pl["sl"], pl["tp1"], pl["tp2"], pl["tp3"], pl["risk_pct"], pl["plan_ok"], pl["reject"], need, str(reason or "")[:400], state, cid))
        else:
            _execute(db, "UPDATE office2_radar_card SET updated_ts=?, scen_state=?, need_text=?, reason=?, stage=? WHERE card_id=?", (float(upd), state, need, str(reason or "")[:400], st, cid))
        out["updated"] += 1
    # сценарії, що пішли далі (READY / скасовано / запізно / строк): лише позначка стану
    for cid, sid in _fetchall(db, "SELECT card_id, scenario_id FROM office2_radar_card WHERE created_ts > ? AND kind = 'WATCH'", (t - TRACK_MAX_AGE_SEC,)):
        r = _fetchall(db, "SELECT state FROM office2_live_scenario WHERE scenario_id = ?", (sid,))
        if r and r[0][0] in ("READY", "INVALIDATED", "MISSED", "EXPIRED"):
            _execute(db, "UPDATE office2_radar_card SET scen_state = ? WHERE card_id = ?", (r[0][0], cid))
    return out


# ------------------------------------------------------------------ paper-супровід
def _candles(rows: Any) -> List[Dict[str, Any]]:
    return [c for c in rows if isinstance(c, dict)] if isinstance(rows, list) else []


def evaluate_card(card: Dict[str, Any], candles: List[Dict[str, Any]], now: float) -> Dict[str, Any]:
    """Результат картки за свічками після її появи (office_signal_track.simulate: ліміт на ціні входу; SL першим у свічці зі стопом і ціллю).
    paper_status: WAITING_ENTRY / ENTERED / TP1 / TP2 / TP3 / SL / NO_ENTRY / TIMEOUT. r_net — модель A (усе на TP1) мінус витрати 0.15 % кола."""
    import office_signal_track as T
    from office2.learning import costs as C

    vis = float(card.get("sent_ts") or card["created_ts"])
    vis = (vis // 900 + 1) * 900.0        # вхід можливий лише в барі, що ПОЧАВСЯ після появи картки (бар, у якому картка з'явилась, ціну якого ми вже могли не встигнути взяти, пропускається)
    plan = {"direction": card["direction"], "entry": card["entry"], "sl": card["sl"], "tp1": card["tp1"], "tp2": card.get("tp2"), "tp3": card.get("tp3"),
            "confirmed_ts": vis, "valid_until_ts": float(card["expires_ts"])}
    res = T.simulate(plan, candles, now_ts=now)
    reached = res.get("reached") or []
    risk_pct = card.get("risk_pct") or (abs(card["entry"] - card["sl"]) / card["entry"] * 100.0)
    cr = C.cost_r(risk_pct) or 0.0
    r1 = abs(card["tp1"] - card["entry"]) / abs(card["entry"] - card["sl"])
    st = res["status"]
    out: Dict[str, Any] = {"reached": ",".join(reached) or None, "entry_ts": res.get("filled_at"), "exit_ts": None, "r_net": None}
    at = res.get("at") or {}
    if st in ("STOP", "TP1", "TP2", "TP3", "OPEN_TIMEOUT") and res.get("filled_at") is not None:
        out["exit_ts"] = res.get("result_at")
    if st == "PENDING":
        out["paper_status"] = "ENTERED" if res.get("filled_at") is not None else "WAITING_ENTRY"
        if "TP1" in reached:
            out["r_net"] = round(r1 - cr, 3)
    elif st == "NOT_FILLED":
        out["paper_status"] = "NO_ENTRY"
    elif st == "INVALID":
        out["paper_status"] = "NO_ENTRY"
    elif st == "OPEN_TIMEOUT":
        out["paper_status"] = reached[-1] if reached else "TIMEOUT"
        out["r_net"] = round(r1 - cr, 3) if reached else None
    elif st == "STOP":
        out["paper_status"] = reached[-1] if reached else "SL"
        out["r_net"] = round(r1 - cr, 3) if reached else round(-1.0 - cr, 3)
        out["exit_ts"] = at.get("SL") or out["exit_ts"]
    else:                                                 # TP1/TP2/TP3 — досягнута найвища ціль; результат моделі A фіксується на TP1
        out["paper_status"] = st
        out["r_net"] = round(r1 - cr, 3)
    return out


def track(db: str, fetch: Callable[[str, str, int], Any], now: Optional[float] = None, log: Callable[[str], None] = print, limit: int = 12) -> int:
    from office_bridge import _execute, _fetchall

    t = time.time() if now is None else now
    _ensure(db)
    cols = ",".join(_COLS)
    rows = _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE plan_ok = 1 AND created_ts > ? AND COALESCE(paper_status,'') NOT IN ('SL','TP1','TP2','TP3','NO_ENTRY','TIMEOUT') "
                         "ORDER BY created_ts DESC LIMIT ?", (t - TRACK_MAX_AGE_SEC, limit))
    n = 0
    for r in rows:
        c = dict(zip(_COLS, r))
        try:
            cl = _candles(fetch(c["symbol"], "15m", 300))
            if not cl:
                continue
            ev = evaluate_card(c, cl, t)
            _execute(db, "UPDATE office2_radar_card SET paper_status=?, entry_ts=?, exit_ts=?, reached=?, r_net=? WHERE card_id=?",
                     (ev["paper_status"], ev["entry_ts"], ev["exit_ts"], ev["reached"], ev["r_net"], c["card_id"]))
            n += 1
        except Exception as exc:  # noqa: BLE001
            log(f"[radar] супровід {c['card_id']}: {type(exc).__name__}: {str(exc)[:100]}")
    return n


# ------------------------------------------------------------------ Telegram
def format_card(c: Dict[str, Any], base_url: str = "https://ai-office-miniapp.onrender.com") -> str:
    import office_ready_card as card
    import office_ready_core as rc
    from urllib.parse import quote
    from office_user_messages import ticker

    sym = c["symbol"]
    n = lambda x: card._num(x, sym)  # noqa: E731
    long_ = c["direction"] == "LONG"
    blocked = c["kind"] == "BLOCKED"
    L = ["🚫 ЗАБЛОКОВАНО · не вхід (paper)" if blocked else "👀 WATCH · не вхід (paper)", f"{'🟢 LONG' if long_ else '🔴 SHORT'} · {ticker(sym)}"]
    if blocked:
        L.append(f"Чому не READY: {str(c.get('gate_reason') or c.get('reason') or '')[len(BLOCK_PREFIX) + 2:].strip() or 'ліміт захисту'}")
    elif c.get("need_text"):
        L.append(f"Стан: 3/3 — ціна в зоні, чекаю: {c['need_text']}" if c.get("stage") == "ARMED" else f"Стан: 2/3 — {c['need_text']}")
    if c.get("level_kind") and c.get("level_price"):
        L.append(f"Рівень: {c['level_kind']} {n(c['level_price'])}")
    if c.get("zone_lo") and c.get("zone_hi"):
        L.append(f"Зона входу: {n(c['zone_lo'])}–{n(c['zone_hi'])}")
    e, sl = c["entry"], c["sl"]
    pc = lambda p: f"{abs(p - e) / e * 100:.2f}".replace(".", ",")    # noqa: E731
    rr = lambda p: f"{abs(p - e) / abs(e - sl):.2f}".replace(".", ",")  # noqa: E731
    L.append(f"Вхід (орієнтир): {n(e)}")
    L.append(f"SL: {n(sl)} (−{pc(sl)}%)")
    for i, k in enumerate(("tp1", "tp2", "tp3"), 1):
        if c.get(k):
            L.append(f"TP{i}: {n(c[k])} (+{pc(c[k])}%; {rr(c[k])}R)")
    L.append(f"⏳ актуально до {rc.kyiv_stamp(c['expires_ts'])} (Київ)")
    L.append("Це спостереження за ринком, не сигнал і не ордер. Супровід і результат — у Mini App.")
    L.append(f"{base_url.rstrip('/')}/v2?tab=radar&card={quote(c['card_id'], safe='')}")
    return "\n".join(L)


def pick_for_tg(db: str, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Картки, що йдуть у Telegram: plan_ok, ARMED або BLOCKED, строк не вийшов, ще не відправлені; ліміти антиспаму."""
    from office_bridge import _fetchall

    t = time.time() if now is None else now
    _ensure(db)
    if not tg_enabled():
        return []
    sent_h = _fetchall(db, "SELECT COUNT(*) FROM office2_radar_card WHERE sent_ts > ?", (t - 3600,))[0][0] or 0
    sent_d = _fetchall(db, "SELECT COUNT(*) FROM office2_radar_card WHERE sent_ts > ?", (t - 86400,))[0][0] or 0
    room = min(TG_PER_HOUR - sent_h, TG_PER_DAY - sent_d)
    if room <= 0:
        return []
    recent_syms = {r[0] for r in _fetchall(db, "SELECT symbol FROM office2_radar_card WHERE sent_ts > ?", (t - TG_SYMBOL_COOLDOWN_SEC,))}
    cols = ",".join(_COLS)
    rows = _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE tg_status = 'NEW' AND plan_ok = 1 AND expires_ts > ? AND (stage IN ('ARMED','BLOCKED')) AND scen_state IN ('WAIT','NO_TRADE') "
                         "AND COALESCE(paper_status,'') IN ('','WAITING_ENTRY') AND tg_tries < ? ORDER BY CASE kind WHEN 'BLOCKED' THEN 0 ELSE 1 END, created_ts", (t, TG_MAX_TRIES))
    out, seen = [], set(recent_syms)
    for r in rows:
        c = dict(zip(_COLS, r))
        if c["symbol"] in seen:
            continue
        seen.add(c["symbol"])
        out.append(c)
        if len(out) >= room:
            break
    return out


def mark_sent(db: str, cid: str, msg_id: Optional[int], now: float) -> None:
    from office_bridge import _execute

    _execute(db, "UPDATE office2_radar_card SET tg_status='SENT', msg_id=?, sent_ts=?, last_error=NULL, notified='SENT' WHERE card_id=?", (msg_id, now, cid))


def mark_failed(db: str, cid: str, err: str) -> None:
    from office_bridge import _execute

    _execute(db, "UPDATE office2_radar_card SET tg_tries = COALESCE(tg_tries,0) + 1, last_error = ?, tg_status = CASE WHEN COALESCE(tg_tries,0) + 1 >= ? THEN 'FAILED' ELSE 'NEW' END WHERE card_id = ?", (err[:200], TG_MAX_TRIES, cid))


MILESTONE_TEXT = {"ENTERED": "вхід за ціною плану торкнуто", "TP1": "TP1 досягнуто", "TP2": "TP2 досягнуто", "TP3": "TP3 досягнуто", "SL": "SL торкнуто", "NO_ENTRY": "вхід не відбувся до кінця строку", "TIMEOUT": "строк вийшов"}


def pending_followups(db: str) -> List[Dict[str, Any]]:
    """Відправлені картки, у яких з'явилася нова віха paper (вхід/TP/SL/кінець строку), про яку ще не повідомляли."""
    from office_bridge import _fetchall

    _ensure(db)
    cols = ",".join(_COLS)
    out = []
    for r in _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE tg_status = 'SENT' AND msg_id IS NOT NULL AND paper_status IS NOT NULL ORDER BY created_ts LIMIT 40"):
        c = dict(zip(_COLS, r))
        done = set(str(c.get("notified") or "").split(","))
        ms = []
        if c.get("entry_ts") is not None or c["paper_status"] in ("ENTERED", "TP1", "TP2", "TP3", "SL"):
            ms.append("ENTERED")
        for k in str(c.get("reached") or "").split(","):
            if k:
                ms.append(k)
        if c["paper_status"] in ("SL", "NO_ENTRY", "TIMEOUT"):
            ms.append(c["paper_status"])
        new = [m for m in dict.fromkeys(ms) if m not in done]
        if new:
            c["_new"] = new
            out.append(c)
    return out


def followup_text(c: Dict[str, Any]) -> str:
    from office_user_messages import ticker

    parts = [MILESTONE_TEXT.get(m, m) for m in c["_new"]]
    r = f" · модельний результат {c['r_net']:+.2f} R (з витратами)" if c.get("r_net") is not None and c["paper_status"] in ("SL", "TP1", "TP2", "TP3") else ""
    return f"👀 WATCH {ticker(c['symbol'])} {c['direction']}: {'; '.join(parts)}{r}. Paper, не ордер."


def mark_notified(db: str, cid: str, new: List[str], prev: Optional[str]) -> None:
    from office_bridge import _execute

    allm = ",".join([x for x in str(prev or "").split(",") if x] + new)
    _execute(db, "UPDATE office2_radar_card SET notified = ? WHERE card_id = ?", (allm, cid))


async def send_pass(db: str, send_photo: Callable[..., Any], send_text: Callable[..., Any], fetch: Callable[[str, str, int], Any], render: Callable[..., Dict[str, Any]],
                    now: Optional[float] = None, log: Callable[[str], None] = print) -> Dict[str, int]:
    """Один прохід: нові WATCH/BLOCKED-картки (з графіком) і follow-up за віхами. Помилка однієї картки не зачіпає інші."""
    from office2.delivery import run_o2, run_o2_pick

    t = time.time() if now is None else now
    res = {"sent": 0, "followups": 0, "failed": 0}
    if not tg_enabled():
        return res
    await run_o2_pick(sync, db, t)
    for c in await run_o2_pick(pick_for_tg, db, t):
        try:
            text = format_card(c)
            img: Dict[str, Any] = {"ok": False}
            try:
                import office_ready_evidence as evd

                cds = await run_o2(fetch, c["symbol"], "15m", 96)
                chart = evd.freeze_chart(cds if isinstance(cds, list) else [], t, "15m", symbol=c["symbol"])
                img = await run_o2(render, symbol=c["symbol"], direction=c["direction"], candles=evd.candles_from_chart(chart) if chart.get("candles") else (cds if isinstance(cds, list) else []),
                                   entry=c["entry"], zone=[c["zone_lo"], c["zone_hi"]], sl=c["sl"], tp1=c["tp1"], tp2=c.get("tp2"), tp3=c.get("tp3"), ready_price=c["entry"],
                                   key_level=c.get("level_price"), key_label="рівень", path=os.path.join(_TMP, f"radar_{c['symbol']}_{int(t)}.png"))
            except Exception as exc_img:  # noqa: BLE001
                img = {"ok": False, "reason": f"{type(exc_img).__name__}: {exc_img}"}
            mid = await (send_photo(str(img["path"]), text, symbol=c["symbol"], direction=c["direction"]) if img.get("ok") else send_text(text, symbol=c["symbol"], direction=c["direction"]))
            if mid:
                await run_o2_pick(mark_sent, db, c["card_id"], int(mid), time.time())
                res["sent"] += 1
                log(f"[radar] WATCH надіслано {c['symbol']} {c['direction']} {c['stage']} id={mid}")
            else:
                await run_o2_pick(mark_failed, db, c["card_id"], "Telegram не підтвердив доставку")
                res["failed"] += 1
        except Exception as exc:  # noqa: BLE001
            await run_o2_pick(mark_failed, db, c["card_id"], f"{type(exc).__name__}: {exc}")
            res["failed"] += 1
            log(f"[radar] помилка {c['card_id']}: {type(exc).__name__}: {str(exc)[:120]}")
    for c in await run_o2_pick(pending_followups, db):
        try:
            mid = await send_text(followup_text(c), reply_to=c["msg_id"], symbol=c["symbol"], direction=c["direction"])
            if mid:
                await run_o2_pick(mark_notified, db, c["card_id"], c["_new"], c.get("notified"))
                res["followups"] += 1
        except Exception as exc:  # noqa: BLE001
            log(f"[radar] follow-up {c['card_id']}: {type(exc).__name__}: {str(exc)[:100]}")
    return res


# ------------------------------------------------------------------ Mini App
STATUS_UA = {"WAITING_ENTRY": "чекаємо вхід", "ENTERED": "вхід був, позиція відкрита (paper)", "TP1": "TP1 досягнуто", "TP2": "TP2 досягнуто", "TP3": "TP3 досягнуто", "SL": "SL",
             "NO_ENTRY": "вхід не відбувся", "TIMEOUT": "строк вийшов"}


def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    done = [x for x in rows if x["paper_status"] in ("SL", "TP1", "TP2", "TP3") and x["r_net"] is not None]
    tp = [x for x in done if x["paper_status"] != "SL"]
    s = sum(x["r_net"] for x in done)
    return {"cards": len(rows), "resolved": len(done), "tp": len(tp), "sl": len(done) - len(tp), "no_entry": sum(1 for x in rows if x["paper_status"] == "NO_ENTRY"),
            "open": sum(1 for x in rows if x["paper_status"] in ("ENTERED",)), "sum_r_net": round(s, 2), "usd_at_10": round(s * 10.0, 2),
            "note": "paper-модель (не гроші): ризик $10, вхід лімітом після появи картки, витрати 0.15 %; n<30 — лише спостереження"}


def summary(db: str, now: Optional[float] = None, card_id: Optional[str] = None) -> Dict[str, Any]:
    from office_bridge import _fetchall

    t = time.time() if now is None else now
    out: Dict[str, Any] = {"ok": True, "now": t, "version": VERSION, "tg_enabled": tg_enabled(), "cards": [], "stats": {}, "why_no_ready": {}}
    try:
        _ensure(db)
        cols = ",".join(_COLS)
        if card_id:
            r = _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE card_id = ?", (card_id,))
            out["card"] = dict(zip(_COLS, r[0])) if r else None
            return out
        rows = [dict(zip(_COLS, r)) for r in _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE created_ts > ? ORDER BY created_ts DESC LIMIT 120", (t - 3 * 86400,))]
        for x in rows:
            x["active"] = bool(x["expires_ts"] and x["expires_ts"] > t and x["scen_state"] in ("WAIT", "NO_TRADE") and x["paper_status"] in (None, "", "WAITING_ENTRY", "ENTERED"))
            x["status_ua"] = STATUS_UA.get(x["paper_status"] or "", "") or ("актуальна" if x["active"] else "неактуальна")
        out["cards"] = rows
        out["stats"] = {"watch": _stats([x for x in rows if x["kind"] == "WATCH" and x["plan_ok"]]), "blocked": _stats([x for x in rows if x["kind"] == "BLOCKED" and x["plan_ok"]])}
        cnt = _fetchall(db, "SELECT state, COUNT(*) FROM office2_live_scenario WHERE updated_ts > ? GROUP BY state", (t - 3600,))
        stg = _fetchall(db, "SELECT COUNT(*) FROM office2_live_scenario WHERE state='WAIT' AND updated_ts > ? AND reason LIKE 'WAIT 3/3%'", (t - 3600,))
        last = _fetchall(db, "SELECT MAX(updated_ts) FROM office2_live_scenario")
        wr = {"last_scan_ts": last[0][0] if last else None, "scenarios_last_hour": {a: b for a, b in cnt}, "armed_now": stg[0][0] if stg else 0}
        try:
            from office2 import paper as P

            g = P.gate_status(db, t)
            wr["gate"] = {"locked": g.get("locked"), "stops_today": len(g.get("stops") or []), "lock_ends_ts": g.get("lock_ends_ts"), "candidates_blocked_today": g.get("candidates_blocked_today")}
        except Exception as exc:  # noqa: BLE001
            wr["gate_error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        out["why_no_ready"] = wr
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out

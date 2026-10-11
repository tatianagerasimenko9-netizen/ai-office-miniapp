"""Живий WATCH/PAPER-радар: видимі торгові картки з ринку «зараз», окремо від LIVE READY.

Що це: Brain v2.1 щоцикла веде сценарії WAIT 1/3→3/3. Для 2/3 і 3/3 (ціна біля зони входу) і для would-be READY, відсічених лімітом ємності (BLOCKED),
фіксується КАРТКА з планом-орієнтиром: зона, вхід (середина зони), SL, TP1–TP3 від реальних рівнів, причина, строк дії. Нічого з цього не READY і не ордер:
  WATCH   — сценарій ще не завершив послідовність (чекає ретрейс/тригер M15); план проходить ті самі геометричні фільтри READY (ризик %, шум ATR, простір до цілі);
  BLOCKED — READY-рівень, який відсік захист (ліміт стопів/ємність): показуємо, чому, і ведемо paper «що було б»; захист не послаблюється;
  READY   — окремий LIVE-потік (office2.delivery), тут лише позначка PROMOTED.
Супровід: paper-симуляція за свічками Binance ПІСЛЯ появи картки (вхід — лише лімітом на ціні входу, SL першим у спірній свічці, витрати 0.15 %), без заглядання в майбутнє.
У Telegram йдуть навчальні спостереження RETRACE 2/3, ARMED 3/3 та BLOCKED (антиспам: ≤ N/год, ≤ M/добу, 1 картка на монету/4 год), з позначкою «не вхід».
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
TG_PER_HOUR = 12
TG_PER_DAY = 60
TG_SYMBOL_COOLDOWN_SEC = 3600
MAX_TP_PCT = 8.0              # ціль далі за 8 % від входу за 4-годинний строк не вважаємо короткостроковою: показуємо як «далеку», у paper не враховуємо
MAX_TP_MULT = 8.0
TG_MAX_TRIES = 3
BLOCK_PREFIX = "ємність сценаріїв"

DDL = ("""CREATE TABLE IF NOT EXISTS office2_radar_card (
    card_id TEXT PRIMARY KEY, kind TEXT NOT NULL, scenario_id TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, stage TEXT,
    created_ts DOUBLE PRECISION NOT NULL, updated_ts DOUBLE PRECISION, expires_ts DOUBLE PRECISION, zone_lo DOUBLE PRECISION, zone_hi DOUBLE PRECISION,
    entry DOUBLE PRECISION, sl DOUBLE PRECISION, tp1 DOUBLE PRECISION, tp2 DOUBLE PRECISION, tp3 DOUBLE PRECISION, risk_pct DOUBLE PRECISION,
    level_kind TEXT, level_price DOUBLE PRECISION, need_text TEXT, reason TEXT, plan_ok INTEGER DEFAULT 0, reject TEXT, scen_state TEXT,
    tg_status TEXT DEFAULT 'NEW', tg_tries INTEGER DEFAULT 0, msg_id BIGINT, sent_ts DOUBLE PRECISION, last_error TEXT, notified TEXT,
    paper_status TEXT, entry_ts DOUBLE PRECISION, exit_ts DOUBLE PRECISION, reached TEXT, r_net DOUBLE PRECISION, gate_reason TEXT, version TEXT, far_targets TEXT, entry_note TEXT, stops_json TEXT, stop_eval TEXT)""",)
_COLS = ("card_id", "kind", "scenario_id", "symbol", "direction", "stage", "created_ts", "updated_ts", "expires_ts", "zone_lo", "zone_hi", "entry", "sl", "tp1", "tp2", "tp3", "risk_pct",
         "level_kind", "level_price", "need_text", "reason", "plan_ok", "reject", "scen_state", "tg_status", "tg_tries", "msg_id", "sent_ts", "last_error", "notified",
         "paper_status", "entry_ts", "exit_ts", "reached", "r_net", "gate_reason", "version", "far_targets", "entry_note", "stops_json", "stop_eval")
_READY: set = set()
_TMP = tempfile.gettempdir()      # один раз при імпорті: у циклі подій виклик gettempdir блокував його на 3 с (loop-lag у production)


def tg_enabled() -> bool:
    return os.getenv("OFFICE2_RADAR_TG", "1").strip().lower() not in ("0", "false", "no", "off")


def _ensure(db: str) -> None:
    if db in _READY:
        return
    from office_bridge import _execute

    try:
        for d in DDL:
            _execute(db, d)
    except Exception as exc:  # noqa: BLE001      # таблиця вже є, а ролі веб-сервісу може бракувати прав на DDL: читання від цього не залежить
        print(f"[radar] DDL пропущено ({type(exc).__name__}: {str(exc)[:100]}) — працюю з наявною таблицею", flush=True)
    for col in ("far_targets TEXT", "entry_note TEXT", "stops_json TEXT", "stop_eval TEXT"):
        try:
            _execute(db, f"ALTER TABLE office2_radar_card ADD COLUMN IF NOT EXISTS {col}")      # міграція таблиці, створеної до появи колонки (Postgres)
        except Exception:  # noqa: BLE001
            pass
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
    """План картки: повний (READY-рівень, відсічений обмеженням/знижений до WAIT) або preview Brain (орієнтир). Нічого не вигадуємо: немає цілей → plan_ok=0.
    Структурна перевірка ДО відправки: вхід лежить у зоні входу (інакше — на найближчій межі зони, з приміткою), геометрія стоп/вхід/ціль коректна,
    цілі далі за MAX_TP_PCT/MAX_TP_MULT позначаються «далекими» й не входять у paper-результат."""
    tg = th.get("targets") or []
    if th.get("entry") is not None and th.get("sl") is not None and tg:
        entry, sl, tgs, ok, rej = _f(th["entry"]), _f(th["sl"]), tg, True, None
    else:
        pv = th.get("preview") or {}
        ok = bool(pv.get("ok"))
        entry, sl, tgs, rej = _f(pv.get("entry")), _f(pv.get("sl")), pv.get("targets") or [], pv.get("reject") or ("preview відсутній" if not pv else None)
    z = th.get("entry_zone") or th.get("zone") or [None, None]
    zlo, zhi = (_f(min(z)), _f(max(z))) if z and None not in z else (None, None)
    long_ = str(th.get("dir") or "").upper() != "SHORT"
    note = None
    if ok and entry and zlo is not None and zhi is not None and not (zlo <= entry <= zhi):
        note = f"ціна підтвердження була поза зоною ({entry:.6g}); вхід лімітом на межі зони"
        entry = zlo if entry < zlo else zhi
    ps = [_f(t.get("p")) for t in tgs]
    ps = [p for p in ps if p]
    if ok and (not entry or not sl or not ps):
        ok, rej = False, rej or "план неповний"
    if ok and not ((sl < entry < ps[0]) if long_ else (ps[0] < entry < sl)):
        ok, rej = False, "геометрія плану некоректна (стоп/вхід/ціль)"
    near, far = [], []
    if ok:
        risk = abs(entry - sl)
        for i, p in enumerate(ps[:3], 1):
            d = abs(p - entry)
            item = {"n": i, "p": p, "pct": d / entry * 100.0, "mult": d / risk if risk else None}
            (far if (item["pct"] > MAX_TP_PCT or (item["mult"] or 0) > MAX_TP_MULT) else near).append(item)
        if not near or near[0]["n"] != 1:
            ok, rej = False, f"перша ціль далі за {MAX_TP_PCT:g}% від входу: за 4 години недосяжна"
    tp = lambda i: next((x["p"] for x in near if x["n"] == i), None)  # noqa: E731
    stops_json = None
    st = th.get("stops") or (th.get("preview") or {}).get("stops")
    if ok and st:
        try:
            from office2 import stops as SV

            stops_json = json.dumps(SV.finalize_for_entry(st, "LONG" if long_ else "SHORT", entry))
        except Exception:  # noqa: BLE001
            stops_json = None
    risk_pct = abs(entry - sl) / entry * 100.0 if ok else _f(th.get("risk_pct"))
    return {"entry": entry, "sl": sl, "tp1": tp(1), "tp2": tp(2), "tp3": tp(3), "risk_pct": risk_pct, "plan_ok": 1 if ok else 0, "reject": None if ok else (rej or "план неповний"),
            "zone_lo": zlo, "zone_hi": zhi, "far_targets": json.dumps(far) if far else None, "entry_note": note, "stops_json": stops_json}


def sync(db: str, now: Optional[float] = None) -> Dict[str, int]:
    """Створює/оновлює картки зі стану сценаріїв Brain. План зафіксований (не повзе за ціною) після відправки в Telegram або входу paper."""
    from office_bridge import _execute, _fetchall

    t = time.time() if now is None else now
    _ensure(db)
    out = {"new": 0, "updated": 0}
    rows = _fetchall(db, "SELECT scenario_id, symbol, direction, kind, state, reason, updated_ts, thesis_json FROM office2_live_scenario "
                         "WHERE (state = 'WAIT' AND updated_ts > ?) OR (state = 'NO_TRADE' AND reason LIKE ? AND reason NOT LIKE ? AND updated_ts > ?) ORDER BY updated_ts",
                   (t - 2400, BLOCK_PREFIX + "%", "%живий сигнал%", t - 3 * 3600))      # «вже є живий сигнал по монеті» — не навчальна ідея, а дубль справжнього READY
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
            dup = _fetchall(db, "SELECT 1 FROM office2_radar_card WHERE symbol = ? AND direction = ? AND scenario_id <> ? AND expires_ts > ? AND kind = ? "
                                "AND COALESCE(paper_status,'') NOT IN ('SL','TP1','TP2','TP3','NO_ENTRY','TIMEOUT') LIMIT 1", (sym, d, sid, t, k))
            if dup:
                continue         # одна активна ідея на монету й напрям: нова теза з'явиться після завершення попередньої
            vals = {"card_id": cid, "kind": k, "scenario_id": sid, "symbol": sym, "direction": d, "stage": st, "created_ts": float(upd), "updated_ts": float(upd), "expires_ts": float(upd) + TTL_SEC,
                    **pl, "level_kind": lvl.get("kind"), "level_price": _f(lvl.get("p")), "need_text": need, "reason": str(reason or "")[:400], "scen_state": state,
                    "tg_status": "NEW", "tg_tries": 0, "gate_reason": str(reason or "")[:160] if k == "BLOCKED" else None, "version": VERSION}
            _execute(db, f"INSERT INTO office2_radar_card({','.join(_COLS)}) VALUES ({','.join('?' for _ in _COLS)}) ON CONFLICT (card_id) DO NOTHING", tuple(vals.get(c) for c in _COLS))
            out["new"] += 1
            if k == "BLOCKED":
                _execute(db, "UPDATE office2_radar_card SET scen_state = 'SUPERSEDED' WHERE card_id = ?", ("W|" + sid,))      # спостереження перетворилось на навчальну угоду
            continue
        tg_status, paper = ex[0]
        if tg_status == "NEW" and not paper:      # план ще не опублікований і не в paper — оновлюємо до найточнішого (ARMED точніший за RETRACE)
            _execute(db, "UPDATE office2_radar_card SET stage=?, updated_ts=?, zone_lo=?, zone_hi=?, entry=?, sl=?, tp1=?, tp2=?, tp3=?, risk_pct=?, plan_ok=?, reject=?, need_text=?, reason=?, scen_state=?, far_targets=?, entry_note=?, stops_json=? WHERE card_id=?",
                     (st, float(upd), pl["zone_lo"], pl["zone_hi"], pl["entry"], pl["sl"], pl["tp1"], pl["tp2"], pl["tp3"], pl["risk_pct"], pl["plan_ok"], pl["reject"], need, str(reason or "")[:400], state,
                      pl["far_targets"], pl["entry_note"], pl["stops_json"], cid))
        else:
            _execute(db, "UPDATE office2_radar_card SET updated_ts=?, scen_state=?, need_text=?, reason=?, stage=? WHERE card_id=?", (float(upd), state, need, str(reason or "")[:400], st, cid))
        out["updated"] += 1
    # сценарії, що пішли далі (READY / скасовано / запізно / строк): лише позначка стану
    for cid, sid in _fetchall(db, "SELECT card_id, scenario_id FROM office2_radar_card WHERE created_ts > ? AND kind = 'WATCH'", (t - TRACK_MAX_AGE_SEC,)):
        r = _fetchall(db, "SELECT state FROM office2_live_scenario WHERE scenario_id = ?", (sid,))
        if r and r[0][0] in ("READY", "INVALIDATED", "MISSED", "EXPIRED") and r[0][0] != "NO_TRADE":
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


def evaluate_variants(card: Dict[str, Any], candles: List[Dict[str, Any]], now: float) -> Optional[Dict[str, Any]]:
    """Окрема оцінка трьох стопів (той самий вхід і цілі, інший SL) + аналіз руху ПІСЛЯ спрацювання стопа. Фактичний результат картки (поточний стоп) не підміняється."""
    from office2 import stops as SV

    try:
        st = json.loads(card.get("stops_json") or "null")
    except ValueError:
        st = None
    if not st:
        return None
    out: Dict[str, Any] = {}
    for k in ("v1", "v2", "v3"):
        v = st.get(k)
        if not v or v.get("side_ok") is False:
            out[k] = {"status": "INVALID"}
            continue
        c2 = dict(card, sl=v["sl"], risk_pct=v.get("risk_pct"))
        ev = evaluate_card(c2, candles, now)
        item = {"sl": v["sl"], "risk_pct": v.get("risk_pct"), "status": ev["paper_status"], "r_net": ev["r_net"], "entry_ts": ev["entry_ts"], "exit_ts": ev["exit_ts"], "reached": ev["reached"]}
        if ev["paper_status"] == "SL" and ev.get("exit_ts"):
            item["after"] = SV.after_stop(card["direction"], candles, float(ev["exit_ts"]), card["entry"], v["sl"], card["tp1"], st.get("extreme"))
        out[k] = item
    return out


def backfill_stops(db: str, now: Optional[float] = None) -> int:
    """Контрольний перерахунок трьох стопів для карток, створених ДО появи stops_json (#207). Лише допоміжна колонка для порівняння:
    план картки (вхід/SL/цілі) не змінюється. Екстремум події й ATR беруться з preview сценарію Brain; «Стоп 1» = фактичний стоп картки (заморожений).
    Позначка stops.backfill фіксує, що це перерахунок, а не розрахунок у момент створення."""
    from office_bridge import _execute, _fetchall
    from office2 import stops as SV

    t = time.time() if now is None else now
    n = 0
    rows = _fetchall(db, "SELECT c.card_id, c.direction, c.entry, c.sl, s.thesis_json FROM office2_radar_card c JOIN office2_live_scenario s ON s.scenario_id = c.scenario_id "
                         "WHERE c.plan_ok = 1 AND c.stops_json IS NULL AND c.created_ts > ?", (t - TRACK_MAX_AGE_SEC,))
    for cid, d, entry, sl, tj in rows:
        try:
            th = json.loads(tj or "{}")
            st = th.get("stops") or (th.get("preview") or {}).get("stops")
            if not st or entry is None or sl is None or not st.get("extreme"):
                continue
            ext = float(st["extreme"])
            if (d == "LONG" and not sl <= ext) or (d == "SHORT" and not sl >= ext):
                continue       # фактичний стоп не за екстремумом події — цю картку не порівнюємо, нічого не вигадуємо
            st = {k: (dict(v) if isinstance(v, dict) else v) for k, v in st.items()}
            st["v1"] = dict(st.get("v1") or {}, sl=float(sl), name=SV.NAMES["v1"], beyond_extreme=True)
            fin = SV.finalize_for_entry(st, d, float(entry))
            fin["backfill"] = {"ts": t, "basis": "екстремум і ATR зі сценарію Brain; Стоп 1 = фактичний стоп картки; план картки не змінювався"}
            _execute(db, "UPDATE office2_radar_card SET stops_json = ? WHERE card_id = ? AND stops_json IS NULL", (json.dumps(fin), cid))
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[radar] backfill стопів {cid}: {type(exc).__name__}: {str(exc)[:100]}", flush=True)
    return n


def track(db: str, fetch: Callable[[str, str, int], Any], now: Optional[float] = None, log: Callable[[str], None] = print, limit: int = 80) -> int:
    from office_bridge import _execute, _fetchall

    t = time.time() if now is None else now
    _ensure(db)
    try:
        backfill_stops(db, t)
    except Exception as exc:  # noqa: BLE001
        log(f"[radar] backfill стопів: {type(exc).__name__}: {str(exc)[:100]}")
    cols = ",".join(_COLS)
    rows = _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE plan_ok = 1 AND created_ts > ? ORDER BY created_ts DESC LIMIT ?", (t - TRACK_MAX_AGE_SEC, limit * 2))
    final = ("SL", "TP1", "TP2", "TP3", "NO_ENTRY", "TIMEOUT", "INVALID")

    def _open(r: tuple) -> bool:
        c0 = dict(zip(_COLS, r))
        if (c0.get("paper_status") or "") not in final:
            return True
        if c0.get("stops_json") and not c0.get("stop_eval"):
            return True
        try:
            ev0 = json.loads(c0.get("stop_eval") or "null") or {}
        except ValueError:
            return False
        return any((v or {}).get("status") not in final for v in ev0.values())

    rows = [r for r in rows if _open(r)][:limit]
    n = 0
    cache: Dict[str, List[Dict[str, Any]]] = {}      # одна вибірка свічок на монету за прохід (мало запитів до біржі)
    for r in rows:
        c = dict(zip(_COLS, r))
        try:
            if c["symbol"] not in cache:
                cache[c["symbol"]] = _candles(fetch(c["symbol"], "15m", 300))
            cl = cache[c["symbol"]]
            if not cl:
                continue
            ev = evaluate_card(c, cl, t)
            vv = evaluate_variants(c, cl, t)
            _execute(db, "UPDATE office2_radar_card SET paper_status=?, entry_ts=?, exit_ts=?, reached=?, r_net=?, stop_eval=? WHERE card_id=?",
                     (ev["paper_status"], ev["entry_ts"], ev["exit_ts"], ev["reached"], ev["r_net"], json.dumps(vv) if vv else None, c["card_id"]))
            n += 1
        except Exception as exc:  # noqa: BLE001
            log(f"[radar] супровід {c['card_id']}: {type(exc).__name__}: {str(exc)[:100]}")
    return n


# ------------------------------------------------------------------ Telegram
def format_card(c: Dict[str, Any], base_url: str = "https://ai-office-miniapp.onrender.com") -> str:
    from office2 import radar_text as RT

    return RT.card_text(c, base_url)


def pick_for_tg(db: str, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Картки в Telegram: plan_ok, ранній RETRACE / ARMED / BLOCKED, актуальні, ще не відправлені; ліміти антиспаму."""
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
    rows = _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE tg_status = 'NEW' AND plan_ok = 1 AND expires_ts > ? AND (stage IN ('RETRACE','ARMED','BLOCKED')) AND scen_state IN ('WAIT','NO_TRADE') "
                         "AND COALESCE(paper_status,'') IN ('','WAITING_ENTRY') AND tg_tries < ? ORDER BY CASE stage WHEN 'BLOCKED' THEN 0 WHEN 'ARMED' THEN 1 ELSE 2 END, created_ts", (t, TG_MAX_TRIES))
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
    from office2 import radar_text as RT

    return RT.followup_text(c)


def mark_notified(db: str, cid: str, new: List[str], prev: Optional[str]) -> None:
    from office_bridge import _execute

    allm = ",".join([x for x in str(prev or "").split(",") if x] + new)
    _execute(db, "UPDATE office2_radar_card SET notified = ? WHERE card_id = ?", (allm, cid))


def _extra_stops(c: Dict[str, Any]) -> List[Any]:
    try:
        st = json.loads(c.get("stops_json") or "null") or {}
        return [(st[k]["sl"], f"Стоп {i}") for i, k in ((2, "v2"), (3, "v3")) if st.get(k) and st[k].get("side_ok") is not False]
    except (ValueError, KeyError, TypeError):
        return []


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
                                   key_level=c.get("level_price"), key_label="рівень", learning=True, extra_stops=_extra_stops(c), path=os.path.join(_TMP, f"radar_{c['symbol']}_{int(t)}.png"))
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
STATUS_UA = {"WAITING_ENTRY": "чекаємо, поки ціна дійде до входу", "ENTERED": "навчальна угода відкрита", "TP1": "ціль 1 досягнута", "TP2": "ціль 2 досягнута", "TP3": "ціль 3 досягнута",
             "SL": "стоп спрацював", "NO_ENTRY": "вхід не відбувся", "TIMEOUT": "строк вийшов"}


def _stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    done = [x for x in rows if x["paper_status"] in ("SL", "TP1", "TP2", "TP3") and x["r_net"] is not None]
    tp = [x for x in done if x["paper_status"] != "SL"]
    s = sum(x["r_net"] for x in done)
    return {"cards": len(rows), "resolved": len(done), "tp": len(tp), "sl": len(done) - len(tp), "win_rate": round(len(tp) / len(done) * 100.0, 1) if done else None,
            "no_entry": sum(1 for x in rows if x["paper_status"] == "NO_ENTRY"), "open": sum(1 for x in rows if x["paper_status"] in ("ENTERED",)),
            "waiting": sum(1 for x in rows if x["paper_status"] in (None, "", "WAITING_ENTRY")), "sum_r_net": round(s, 2), "usd_at_10": round(s * 10.0, 2),
            "note": "Навчальний результат без реальних грошей: ризик 10 $ на угоду, вхід лише після появи картки, комісії й проковзування 0,15 % враховано; менше 30 завершених угод — це лише спостереження."}


def stop_study(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Порівняння трьох стопів на навчальних угодах (той самий вхід і цілі). Не підміняє фактичний результат; вердикт лише за n ≥ 30 завершених."""
    final = ("SL", "TP1", "TP2", "TP3")
    per = {k: {"n": 0, "sl": 0, "tp": 0, "sum_r": 0.0, "loss_r": 0.0, "risk_pct": 0.0, "hunt": 0, "broken": 0} for k in ("v1", "v2", "v3")}
    used = 0
    for x in rows:
        try:
            ev = json.loads(x.get("stop_eval") or "null") or {}
        except ValueError:
            continue
        if not ev or any((ev.get(k) or {}).get("status") not in final for k in ("v1", "v2", "v3")):
            continue          # у порівняння входять лише угоди, де всі три варіанти вже мають завершений результат (однакова база)
        used += 1
        for k in per:
            v = ev[k]
            p = per[k]
            p["n"] += 1
            p["sl" if v["status"] == "SL" else "tp"] += 1
            p["sum_r"] += v["r_net"] or 0.0
            p["loss_r"] += min(v["r_net"] or 0.0, 0.0)
            p["risk_pct"] += v.get("risk_pct") or 0.0
            a = (v.get("after") or {}).get("verdict")
            p["hunt"] += a == "STOP_HUNT"
            p["broken"] += a == "BROKEN"
    out: Dict[str, Any] = {"n": used, "variants": {}}
    for k, p in per.items():
        n = p["n"] or 1
        out["variants"][k] = {"n": p["n"], "sl": p["sl"], "tp": p["tp"], "win_rate": round(p["tp"] / n * 100.0, 1) if p["n"] else None, "sum_r": round(p["sum_r"], 2), "loss_r": round(p["loss_r"], 2),
                              "avg_risk_pct": round(p["risk_pct"] / n, 2) if p["n"] else None, "after_stop_hunt": p["hunt"], "after_stop_broken": p["broken"]}
    base = out["variants"]["v1"]
    for k in ("v2", "v3"):
        v = out["variants"][k]
        v["delta_sum_r_vs_current"] = round(v["sum_r"] - base["sum_r"], 2)
        v["delta_loss_r_vs_current"] = round(v["loss_r"] - base["loss_r"], 2)
    if used < 30:
        out["verdict"] = f"Замало даних: завершених угод {used} із 30 потрібних. Це спостереження, а не висновок; поточний стоп у навчальних угодах не змінюється."
    else:
        best = max(("v1", "v2", "v3"), key=lambda k: out["variants"][k]["sum_r"])
        out["verdict"] = f"За {used} завершеними угодами найкращий сумарний результат дає {best}. Перед будь-якою зміною потрібна перевірка на незалежному періоді."
    return out


def scanner_diag(db: str, now: Optional[float] = None) -> Dict[str, Any]:
    """Чому немає нових карток: що саме бачив сканер за останні 40 хв (без вигаданих причин — лише лічильники з БД)."""
    from office_bridge import _fetchall

    t = time.time() if now is None else now
    rows = _fetchall(db, "SELECT scenario_id, symbol, direction, reason FROM office2_live_scenario WHERE state = 'WAIT' AND updated_ts > ?", (t - 2400,))
    own = {r[0] for r in _fetchall(db, "SELECT scenario_id FROM office2_radar_card WHERE created_ts > ?", (t - 86400,))}
    d = {"wait_total": len(rows), "no_structure": 0, "with_card": 0, "without_card": 0}
    for sid, _sym, _dr, reason in rows:
        m = re.match(r"^WAIT (\d)/3", str(reason or ""))
        if not m or m.group(1) == "1":
            d["no_structure"] += 1
        elif sid in own or ("W|" + sid) in own or ("B|" + sid) in own:
            d["with_card"] += 1
        else:
            d["without_card"] += 1
    lc = _fetchall(db, "SELECT MAX(created_ts) FROM office2_radar_card")
    d["last_card_ts"] = lc[0][0] if lc and lc[0][0] else None
    d["new_cards_hour"] = _fetchall(db, "SELECT COUNT(*) FROM office2_radar_card WHERE created_ts > ?", (t - 3600,))[0][0] or 0
    if d["without_card"]:
        d["message"] = f"Є {d['without_card']} ідей без картки — вони з'являться після наступної синхронізації (або це дубль активної ідеї по тій самій монеті й напряму)."
    elif d["with_card"]:
        d["message"] = f"Нових незалежних ідей немає: усі {d['with_card']} поточні ідеї вже мають картки. Ще {d['no_structure']} лише на першому кроці (структури поки немає) — картки для них не створюються."
    else:
        d["message"] = f"Підтверджених кроків структури зараз немає: {d['no_structure']} ідей лише на першому кроці."
    return d


def summary(db: str, now: Optional[float] = None, card_id: Optional[str] = None) -> Dict[str, Any]:
    from office_bridge import _fetchall

    t = time.time() if now is None else now
    out: Dict[str, Any] = {"ok": True, "now": t, "version": VERSION, "tg_enabled": tg_enabled(), "cards": [], "stats": {}, "why_no_ready": {}}
    try:
        _ensure(db)
        cols = ",".join(_COLS)
        if card_id:
            from office2 import radar_text as RT

            r = []
            for cand in RT.parse_link_id(card_id):      # переживає подвійне кодування й старий формат посилання (W|O2|…)
                r = _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE card_id = ?", (cand,))
                if r:
                    break
            if not r:
                m = re.search(r"([0-9a-f]{8,})\s*$", str(card_id).lower())
                if m:
                    r = _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE card_id LIKE ? ORDER BY created_ts DESC LIMIT 1", ("%" + m.group(1),))
            c = dict(zip(_COLS, r[0])) if r else None
            if c:
                c["active"] = bool(c["expires_ts"] and c["expires_ts"] > t and c["scen_state"] in ("WAIT", "NO_TRADE") and c["paper_status"] in (None, "", "WAITING_ENTRY", "ENTERED"))
                c["h"] = RT.present(c)
            out["card"] = c
            print(f"[radar] картка за посиланням «{str(card_id)[:40]}»: {'знайдено ' + c['card_id'] if c else 'НЕ знайдено'}", flush=True)
            return out
        rows = [dict(zip(_COLS, r)) for r in _fetchall(db, f"SELECT {cols} FROM office2_radar_card WHERE created_ts > ? ORDER BY created_ts DESC LIMIT 120", (t - 3 * 86400,))]
        from office2 import radar_text as RT

        for x in rows:
            x["h"] = RT.present(x)
            x["active"] = bool(x["expires_ts"] and x["expires_ts"] > t and x["scen_state"] in ("WAIT", "NO_TRADE") and x["paper_status"] in (None, "", "WAITING_ENTRY", "ENTERED"))
            x["status_ua"] = STATUS_UA.get(x["paper_status"] or "", "") or ("актуальна" if x["active"] else "неактуальна")
        out["cards"] = rows
        from datetime import datetime
        from zoneinfo import ZoneInfo

        k0 = datetime.fromtimestamp(t, ZoneInfo("Europe/Kyiv")).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()      # «сьогодні» — за київською добою
        ok_rows = [x for x in rows if x["plan_ok"]]
        out["stats"] = {"watch": _stats([x for x in ok_rows if x["kind"] == "WATCH"]), "blocked": _stats([x for x in ok_rows if x["kind"] == "BLOCKED"]),
                        "learning": _stats([x for x in ok_rows if x["kind"] == "BLOCKED"]), "stop_study": stop_study(ok_rows), "today": _stats([x for x in ok_rows if x["created_ts"] >= k0]), "all": _stats(ok_rows)}
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
        g = wr.get("gate") or {}
        wr["message"] = (f"Сьогодні нових дозволених входів немає: спрацював денний ліміт ризику (до {RT.kyiv(g.get('lock_ends_ts'))}). Навчальні сигнали без реальних грошей продовжують надходити."
                         if g.get("locked") else "Нових дозволених входів зараз немає: умови підтвердження ще не зібралися. Навчальні сигнали без реальних грошей надходять далі.")
        try:
            wr["scanner"] = scanner_diag(db, t)
        except Exception as exc:  # noqa: BLE001
            wr["scanner_error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        out["why_no_ready"] = wr
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        print(f"[radar] summary помилка (card={card_id}): {out['error']}", flush=True)       # у логах Render видно причину, а не лише «200»
    return out

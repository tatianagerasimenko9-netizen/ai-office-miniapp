"""Мовчазне відстеження кожного «Плану готовий» (і відхилених планів) для навчання Офісу. Не залежить від кнопки «Я відкрила угоду».

Події в БД (без нових таблиць): SIGNAL_PLAN — план у момент підтвердження/відмови; SIGNAL_RESULT — підсумок за реальними свічками:
вхід заповнено чи ні за час дії, далі TP1/TP2/TP3/стоп, MFE/MAE, час до результату. Жодних повідомлень у Telegram.
Відхилені плани (не пройшли перевірки) рахуються так само гіпотетично — щоб бачити, чи Лев не надто суворий.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

EV_PLAN = "SIGNAL_PLAN"
EV_RESULT = "SIGNAL_RESULT"
EV_EXPIRY = "SCENARIO_TIME_EXPIRY"
EV_FALSE = "FALSE_EXPIRY_CHECK"
EV_MILESTONE = "SCENARIO_MILESTONE"   # досягнення рівня сценарію (TP1/TP2/TP3/SL) вже ПОКАЗАНОЇ в Telegram ідеї; не залежить від «Я відкрила угоду»
EV_MILESTONE_ON = "SCENARIO_MILESTONE_ENABLED"
FALSE_EXPIRY_WINDOW_SEC = 48 * 3600
MAX_TRACK_SEC = 72 * 3600
TF_SEC = 900


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except (TypeError, ValueError):
        return None


def record_plan(db: str, *, scenario_id: str, symbol: str, direction: str, tf: str, entry: Any, sl: Any, tp1: Any, tp2: Any = None, tp3: Any = None,
                max_entry: Any = None, confirmed_ts: float, valid_until_ts: float, rejected: bool = False, reason: str = "",
                confirm_msg_id: Any = None, gate: Optional[Dict[str, Any]] = None) -> None:
    from office_bridge import log_event

    log_event(db, EV_PLAN, {"scenario_id": scenario_id, "symbol": str(symbol).upper(), "direction": str(direction).upper(), "tf": tf,
                            "entry": _f(entry), "sl": _f(sl), "tp1": _f(tp1), "tp2": _f(tp2), "tp3": _f(tp3), "max_entry": _f(max_entry),
                            "confirmed_ts": float(confirmed_ts), "valid_until_ts": float(valid_until_ts), "rejected": bool(rejected),
                            "reason": reason, "confirm_msg_id": confirm_msg_id, "gate": gate or None}, scenario_id)


def simulate(plan: Dict[str, Any], candles: Any, now_ts: Optional[float] = None) -> Dict[str, Any]:
    """Результат плану за свічками (за зростанням часу). Консервативно: у свічці, що зачепила і стоп, і ціль, — спершу стоп;
    у свічці заповнення входу цілі не зараховуються. status: PENDING (ще йде), NOT_FILLED, STOP, TP1/TP2/TP3 (найвища досягнута), OPEN_TIMEOUT."""
    now = time.time() if now_ts is None else now_ts
    long_ = str(plan.get("direction") or "LONG").upper() != "SHORT"
    e, sl = _f(plan.get("entry")), _f(plan.get("sl"))
    tps = [(n, _f(plan.get(k))) for n, k in (("TP1", "tp1"), ("TP2", "tp2"), ("TP3", "tp3")) if _f(plan.get(k)) is not None]
    t_conf, t_valid = float(plan["confirmed_ts"]), float(plan["valid_until_ts"])
    out: Dict[str, Any] = {"status": "PENDING", "filled_at": None, "result_at": None, "mfe_pct": None, "mae_pct": None, "reached": [], "stopped": False}
    if not e or sl is None or not tps:
        return {**out, "status": "INVALID"}
    filled = False
    mfe = mae = 0.0
    for c in candles if isinstance(candles, list) else []:
        t0 = _ts((c or {}).get("ts"))
        hi, lo = _f(c.get("high")), _f(c.get("low"))
        if t0 is None or hi is None or lo is None or t0 + TF_SEC <= t_conf or t0 + TF_SEC > now:
            continue   # до підтвердження або свічка ще не закрита
        if not filled:
            if t0 >= t_valid:
                return {**out, "status": "NOT_FILLED", "result_at": t_valid}
            if lo <= e <= hi:
                filled = True
                out["filled_at"] = t0
                stop_hit = (lo <= sl) if long_ else (hi >= sl)
                mfe = max(mfe, ((hi - e) if long_ else (e - lo)) / e * 100.0)
                mae = max(mae, ((e - lo) if long_ else (hi - e)) / e * 100.0)
                if stop_hit:
                    return {**out, "status": "STOP", "stopped": True, "result_at": t0 + TF_SEC, "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)}
            continue
        mfe = max(mfe, ((hi - e) if long_ else (e - lo)) / e * 100.0)
        mae = max(mae, ((e - lo) if long_ else (hi - e)) / e * 100.0)
        stop_hit = (lo <= sl) if long_ else (hi >= sl)
        if stop_hit:
            res = out["reached"][-1] if out["reached"] else "STOP"
            return {**out, "status": res, "stopped": True, "result_at": t0 + TF_SEC, "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)}
        for name, lvl in tps:
            if name not in out["reached"] and ((hi >= lvl) if long_ else (lo <= lvl)):
                out["reached"].append(name)
        if tps and tps[-1][0] in out["reached"]:
            return {**out, "status": tps[-1][0], "result_at": t0 + TF_SEC, "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)}
        if now - float(out["filled_at"]) > MAX_TRACK_SEC:
            return {**out, "status": out["reached"][-1] if out["reached"] else "OPEN_TIMEOUT", "result_at": now,
                    "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)}
    if not filled and now > t_valid + TF_SEC:
        return {**out, "status": "NOT_FILLED", "result_at": t_valid}
    out.update(mfe_pct=round(mfe, 3) if filled else None, mae_pct=round(mae, 3) if filled else None)
    return out


def _events(db: str, etype: str) -> List[Dict[str, Any]]:
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT id, ts_utc, signal_id, payload_json FROM office_events WHERE event_type = ? ORDER BY id", (etype,))
    out = []
    for r in rows or []:
        try:
            p = json.loads(r[3]) if isinstance(r[3], str) else dict(r[3] or {})
        except (TypeError, ValueError):
            continue
        out.append({"id": r[0], "ts": r[1], "signal_id": r[2], "p": p})
    return out


def tick(db: str, fetch: Optional[Callable[[str, str, int], Any]] = None, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Один прохід: для планів без підсумку рахуємо результат; фінальні пишемо один раз (SIGNAL_RESULT). Повертає записані підсумки."""
    from office_bridge import log_event

    if fetch is None:
        from office_market_data import fetch_candles as fetch  # type: ignore[assignment]
    now = time.time() if now_ts is None else now_ts
    done = {(e["p"].get("scenario_id"), e["p"].get("confirmed_ts")) for e in _events(db, EV_RESULT)}
    written: List[Dict[str, Any]] = []
    for ev in _events(db, EV_PLAN):
        p = ev["p"]
        key = (p.get("scenario_id"), p.get("confirmed_ts"))
        if key in done:
            continue
        try:
            candles = fetch(p["symbol"], "15m", 300)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(candles, list) or not candles:
            continue
        res = simulate(p, candles, now)
        if res["status"] in ("PENDING", "INVALID"):
            continue
        payload = {"scenario_id": p.get("scenario_id"), "confirmed_ts": p.get("confirmed_ts"), "symbol": p.get("symbol"), "direction": p.get("direction"),
                   "rejected": bool(p.get("rejected")), "outcome": res["status"], "reached": res["reached"], "mfe_pct": res["mfe_pct"], "mae_pct": res["mae_pct"],
                   "filled": res["filled_at"] is not None,
                   "time_to_result_sec": (res["result_at"] - p["confirmed_ts"]) if res.get("result_at") else None}
        log_event(db, EV_RESULT, payload, p.get("scenario_id"))
        written.append(payload)
    return written


def milestone_since(db: str) -> float:
    """Момент першого запуску відстеження подій сценарію: старіші READY історичні — по них повідомлень не шлемо (без лавини після деплою)."""
    from office_bridge import log_event

    ev = _events(db, EV_MILESTONE_ON)
    if ev:
        return float(ev[0]["p"].get("since") or 0.0)
    now = time.time()
    log_event(db, EV_MILESTONE_ON, {"since": now}, "")
    return now


_MS_DONE: set = set()   # плани, що завершені й повністю відпрацьовані в цьому процесі (не тягнемо свічки знову)


def pending_milestones(db: str, fetch: Optional[Callable[[str, str, int], Any]] = None, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Нові події рівнів для доставлених READY (від появи функції): TP1/TP2/TP3 і SL, кожна — один раз. Це подія СЦЕНАРІЮ за ринком, а не закриття угоди."""
    if fetch is None:
        from office_market_data import fetch_candles as fetch  # type: ignore[assignment]
    now = time.time() if now_ts is None else now_ts
    since = milestone_since(db)
    seen = {(e["p"].get("scenario_id"), e["p"].get("confirmed_ts"), e["p"].get("level")) for e in _events(db, EV_MILESTONE)}
    out: List[Dict[str, Any]] = []
    for ev in _events(db, EV_PLAN):
        p = ev["p"]
        if p.get("rejected") or not p.get("confirm_msg_id") or float(p.get("confirmed_ts") or 0) < since:
            continue
        sid, ct = p.get("scenario_id"), p.get("confirmed_ts")
        if (sid, ct) in _MS_DONE:
            continue
        if all((sid, ct, lv) in seen for lv in ("TP1", "TP2", "TP3", "SL")):
            continue
        if now > float(p.get("valid_until_ts") or 0) + MAX_TRACK_SEC + 3600:
            continue
        try:
            candles = fetch(p["symbol"], "15m", 300)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(candles, list) or not candles:
            continue
        res = simulate(p, candles, now)
        levels = list(res.get("reached") or []) + (["SL"] if res.get("stopped") else [])
        if res["status"] not in ("PENDING", "INVALID") and all((sid, ct, lv) in seen for lv in levels):
            _MS_DONE.add((sid, ct))
            continue
        for lv in levels:
            if (sid, ct, lv) in seen:
                continue
            price = p.get({"TP1": "tp1", "TP2": "tp2", "TP3": "tp3", "SL": "sl"}[lv])
            out.append({"scenario_id": sid, "confirmed_ts": ct, "symbol": p.get("symbol"), "direction": p.get("direction"), "level": lv,
                        "price": price, "confirm_msg_id": p.get("confirm_msg_id")})
    return out


def record_milestone(db: str, m: Dict[str, Any], msg_id: Any = None) -> None:
    from office_bridge import log_event

    log_event(db, EV_MILESTONE, {"scenario_id": m.get("scenario_id"), "confirmed_ts": m.get("confirmed_ts"), "level": m.get("level"),
                                 "symbol": m.get("symbol"), "price": m.get("price"), "msg_id": msg_id, "sent_ts": time.time()}, str(m.get("scenario_id") or ""))


def report(db: str, min_sample: int = 20) -> Dict[str, Any]:
    """Окремо: підсумки сигналів Лева (відстежено мовчки) і гіпотетичні результати відхилених планів. Без вигаданих відсотків при малій вибірці."""
    plans = _events(db, EV_PLAN)
    results = {(e["p"].get("scenario_id"), e["p"].get("confirmed_ts")): e["p"] for e in _events(db, EV_RESULT)}

    def block(rejected: bool) -> Dict[str, Any]:
        ps = [e["p"] for e in plans if bool(e["p"].get("rejected")) == rejected]
        rs = [results[(p.get("scenario_id"), p.get("confirmed_ts"))] for p in ps if (p.get("scenario_id"), p.get("confirmed_ts")) in results]
        n_filled = [r for r in rs if r.get("filled")]
        cnt: Dict[str, int] = {}
        for r in rs:
            cnt[r["outcome"]] = cnt.get(r["outcome"], 0) + 1
        out: Dict[str, Any] = {"plans": len(ps), "finished": len(rs), "pending": len(ps) - len(rs), "outcomes": cnt, "filled": len(n_filled)}
        if len(rs) >= min_sample:
            out["fill_rate_pct"] = round(len(n_filled) / len(rs) * 100, 1)
            if n_filled:
                out["tp_rate_pct"] = round(sum(1 for r in n_filled if r["outcome"] in ("TP1", "TP2", "TP3")) / len(n_filled) * 100, 1)
                out["stop_rate_pct"] = round(sum(1 for r in n_filled if r["outcome"] == "STOP") / len(n_filled) * 100, 1)
                out["avg_mfe_pct"] = round(sum(r["mfe_pct"] or 0 for r in n_filled) / len(n_filled), 2)
                out["avg_mae_pct"] = round(sum(r["mae_pct"] or 0 for r in n_filled) / len(n_filled), 2)
        else:
            out["note"] = f"n={len(rs)} < {min_sample} — відсотки не показуємо"
        return out

    fx = [e["p"] for e in _events(db, EV_FALSE)]
    exp_n = len(_events(db, EV_EXPIRY))
    return {"ok": True, "readonly": True, "kind": "signals", "signals": block(False), "rejected": block(True),
            "time_expiry": {"expired_by_time": exp_n, "checked": len(fx), "false_expiry": sum(1 for x in fx if x.get("false_expiry"))},
            "note": "Результати сигналів Лева — за ринком, без повідомлень і не залежать від кнопки «Я відкрила угоду». Мої угоди — окремо."}


def confirm_msg_for(db: str, scenario_id: str) -> Optional[int]:
    """id повідомлення з готовим сигналом (щоб вести угоду відповіддю на нього)."""
    for e in reversed(_events(db, EV_PLAN)):
        if e["p"].get("scenario_id") == scenario_id and not e["p"].get("rejected"):
            try:
                return int(e["p"].get("confirm_msg_id")) if e["p"].get("confirm_msg_id") else None
            except (TypeError, ValueError):
                return None
    return None


def record_expiry(db: str, *, scenario_id: str, symbol: str, direction: str, zone_lo: Any, zone_hi: Any, sl: Any, tp1: Any, expired_ts: float) -> None:
    """Зняття сценарію ЗА ЧАСОМ (не за причиною): запам'ятовуємо, щоб згодом перевірити заднім числом, чи ідея не відпрацювала (FALSE_EXPIRY)."""
    from office_bridge import log_event

    log_event(db, EV_EXPIRY, {"scenario_id": scenario_id, "symbol": str(symbol).upper(), "direction": str(direction).upper(), "zone_lo": _f(zone_lo),
                              "zone_hi": _f(zone_hi), "sl": _f(sl), "tp1": _f(tp1), "expired_ts": float(expired_ts)}, scenario_id)


def check_false_expiry(db: str, fetch: Optional[Callable[[str, str, int], Any]] = None, now_ts: Optional[float] = None) -> List[Dict[str, Any]]:
    """Для кожного зняття за часом: після зняття ціна зайшла в зону й дійшла до TP1 раніше за стоп у межах 48 год → FALSE_EXPIRY. Пишемо один раз."""
    from office_bridge import log_event

    if fetch is None:
        from office_market_data import fetch_candles as fetch  # type: ignore[assignment]
    now = time.time() if now_ts is None else now_ts
    done = {e["p"].get("scenario_id") for e in _events(db, EV_FALSE)}
    out: List[Dict[str, Any]] = []
    for ev in _events(db, EV_EXPIRY):
        p = ev["p"]
        if p.get("scenario_id") in done or now < float(p["expired_ts"]) + 3600:
            continue
        lo, hi = _f(p.get("zone_lo")), _f(p.get("zone_hi"))
        if lo is None or hi is None or _f(p.get("sl")) is None or _f(p.get("tp1")) is None:
            continue
        try:
            candles = fetch(p["symbol"], "15m", 300)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(candles, list) or not candles:
            continue
        plan = {"direction": p["direction"], "entry": (lo + hi) / 2.0, "sl": p["sl"], "tp1": p["tp1"], "confirmed_ts": float(p["expired_ts"]),
                "valid_until_ts": float(p["expired_ts"]) + FALSE_EXPIRY_WINDOW_SEC}
        res = simulate(plan, candles, now)
        if res["status"] == "PENDING" and now < float(p["expired_ts"]) + FALSE_EXPIRY_WINDOW_SEC:
            continue
        payload = {"scenario_id": p["scenario_id"], "symbol": p["symbol"], "direction": p["direction"], "false_expiry": res["status"] in ("TP1", "TP2", "TP3"),
                   "after_expiry_outcome": res["status"]}
        log_event(db, EV_FALSE, payload, p["scenario_id"])
        out.append(payload)
    return out

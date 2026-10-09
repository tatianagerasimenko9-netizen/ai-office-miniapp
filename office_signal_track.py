"""Мовчазне відстеження кожного «Плану готовий» (і відхилених планів) для навчання Офісу. Не залежить від кнопки «Я відкрила угоду».

Події в БД (без нових таблиць): SIGNAL_PLAN — план у момент підтвердження/відмови; SIGNAL_RESULT — підсумок за реальними свічками:
вхід заповнено чи ні за час дії, далі TP1/TP2/TP3/стоп, MFE/MAE, час до результату. Жодних повідомлень у Telegram.
Відхилені плани (не пройшли перевірки) рахуються так само гіпотетично — щоб бачити, чи Лев не надто суворий.
"""
from __future__ import annotations

import json
import os
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


def simulate(plan: Dict[str, Any], candles: Any, now_ts: Optional[float] = None, tf_sec: float = TF_SEC, live_tail: bool = False) -> Dict[str, Any]:
    """Результат плану за свічками (за зростанням часу). Консервативно: у свічці, що зачепила і стоп, і ціль, — спершу стоп;
    у свічці заповнення входу цілі не зараховуються. status: PENDING (ще йде), NOT_FILLED, STOP, TP1/TP2/TP3 (найвища досягнута), OPEN_TIMEOUT."""
    now = time.time() if now_ts is None else now_ts
    long_ = str(plan.get("direction") or "LONG").upper() != "SHORT"
    e, sl = _f(plan.get("entry")), _f(plan.get("sl"))
    tps = [(n, _f(plan.get(k))) for n, k in (("TP1", "tp1"), ("TP2", "tp2"), ("TP3", "tp3")) if _f(plan.get(k)) is not None]
    t_conf, t_valid = float(plan["confirmed_ts"]), float(plan["valid_until_ts"])
    out: Dict[str, Any] = {"status": "PENDING", "filled_at": None, "result_at": None, "mfe_pct": None, "mae_pct": None, "reached": [], "stopped": False, "at": {}}
    if not e or sl is None or not tps:
        return {**out, "status": "INVALID"}
    filled = False
    mfe = mae = 0.0
    for c in candles if isinstance(candles, list) else []:
        t0 = _ts((c or {}).get("ts"))
        hi, lo = _f(c.get("high")), _f(c.get("low"))
        if t0 is None or hi is None or lo is None or t0 + tf_sec <= t_conf or (tf_sec <= 300 and t0 < t_conf):
            continue
        if t0 + tf_sec > now and not (live_tail and filled):   # свічка ще формується: для вже відкритого входу її high/low (торкання TP/SL) беремо одразу — торкання не скасовується
            continue   # до підтвердження або свічка ще не закрита
        if not filled:
            if t0 >= t_valid:
                return {**out, "status": "NOT_FILLED", "result_at": t_valid}
            if lo <= e <= hi:
                filled = True
                out["filled_at"] = t0
                out["at"]["ENTRY"] = t0
                stop_hit = (lo <= sl) if long_ else (hi >= sl)
                mfe = max(mfe, ((hi - e) if long_ else (e - lo)) / e * 100.0)
                mae = max(mae, ((e - lo) if long_ else (hi - e)) / e * 100.0)
                if stop_hit:
                    out["at"]["SL"] = t0
                    return {**out, "status": "STOP", "stopped": True, "result_at": t0 + tf_sec, "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)}
            continue
        mfe = max(mfe, ((hi - e) if long_ else (e - lo)) / e * 100.0)
        mae = max(mae, ((e - lo) if long_ else (hi - e)) / e * 100.0)
        stop_hit = (lo <= sl) if long_ else (hi >= sl)
        if stop_hit:
            out["at"]["SL"] = t0
            res = out["reached"][-1] if out["reached"] else "STOP"
            return {**out, "status": res, "stopped": True, "result_at": t0 + tf_sec, "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)}
        for name, lvl in tps:
            if name not in out["reached"] and ((hi >= lvl) if long_ else (lo <= lvl)):
                out["reached"].append(name)
                out["at"][name] = t0
        if tps and tps[-1][0] in out["reached"]:
            return {**out, "status": tps[-1][0], "result_at": t0 + tf_sec, "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)}
        if now - float(out["filled_at"]) > MAX_TRACK_SEC:
            return {**out, "status": out["reached"][-1] if out["reached"] else "OPEN_TIMEOUT", "result_at": now,
                    "mfe_pct": round(mfe, 3), "mae_pct": round(mae, 3)}
    if not filled and now > t_valid + tf_sec:
        return {**out, "status": "NOT_FILLED", "result_at": t_valid}
    out.update(mfe_pct=round(mfe, 3) if filled else None, mae_pct=round(mae, 3) if filled else None)
    return out


_BAR_MEMO: Dict[tuple, int] = {}   # (вид, ключ) -> номер 15m-бару, на якому план уже оцінено без підсумку


def _bar_idx(now: float, tf_sec: float = TF_SEC) -> int:
    return int(now // tf_sec)


def _skip_same_bar(kind: str, key: Any, now: float, tf_sec: float = TF_SEC) -> bool:
    """simulate() бере лише ЗАКРИТІ свічки, тож доки не закрилась нова, повторна оцінка дає ту саму відповідь — запит свічок зайвий (результат не змінюється)."""
    return _BAR_MEMO.get((kind, key)) == _bar_idx(now, tf_sec)


def _remember_bar(kind: str, key: Any, candles: Any, now: float, tf_sec: float = TF_SEC) -> None:
    """Запамʼятовуємо бар лише якщо вибірка вже містила останню закриту свічку; інакше наступний прохід спробує знову (затримка даних не повинна відкладати результат)."""
    try:
        last = candles[-1]
        t0 = _ts((last or {}).get("ts"))
        if t0 is not None and t0 >= (_bar_idx(now, tf_sec) - 1) * tf_sec:
            _BAR_MEMO[(kind, key)] = _bar_idx(now, tf_sec)
            if len(_BAR_MEMO) > 5000:
                _BAR_MEMO.clear()
    except Exception:  # noqa: BLE001
        pass


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
        if _skip_same_bar("tick", key, now):
            continue   # нова 15m-свічка ще не закрилась: результат не може змінитись
        try:
            candles = fetch(p["symbol"], "15m", 300)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(candles, list) or not candles:
            continue
        res = simulate(p, candles, now)
        if res["status"] in ("PENDING", "INVALID"):
            _remember_bar("tick", key, candles, now)
            continue
        payload = {"scenario_id": p.get("scenario_id"), "confirmed_ts": p.get("confirmed_ts"), "symbol": p.get("symbol"), "direction": p.get("direction"),
                   "rejected": bool(p.get("rejected")), "outcome": res["status"], "reached": res["reached"], "mfe_pct": res["mfe_pct"], "mae_pct": res["mae_pct"],
                   "filled": res["filled_at"] is not None,
                   "time_to_result_sec": (res["result_at"] - p["confirmed_ts"]) if res.get("result_at") else None}
        log_event(db, EV_RESULT, payload, p.get("scenario_id"))
        written.append(payload)
    return written


def rejected_recently(db: str, scenario_id: str, reason: str, within_sec: float = 6 * 3600, now: Optional[float] = None) -> bool:
    """Той самий відхилений план (та сама причина) цього сценарію вже записано нещодавно — не дублюємо запис після кожного рестарту."""
    from office_bridge import _fetchall

    now = time.time() if now is None else now
    try:
        rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? AND signal_id = ? ORDER BY id DESC LIMIT 5", (EV_PLAN, scenario_id))
    except Exception:  # noqa: BLE001
        return False
    for r in rows or []:
        try:
            p = json.loads(r[0]) if isinstance(r[0], str) else dict(r[0] or {})
        except (TypeError, ValueError):
            continue
        if p.get("rejected") and str(p.get("reason") or "")[:200] == str(reason or "")[:200] and now - float(p.get("confirmed_ts") or 0) < within_sec:
            return True
    return False


def plan_for(db: str, scenario_id: str) -> Optional[Dict[str, Any]]:
    """Канонічний знімок готового плану сценарію: останній НЕвідхилений доставлений SIGNAL_PLAN (єдине джерело для Telegram, Mini App і статистики)."""
    from office_bridge import _fetchall

    try:
        rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? AND signal_id = ? ORDER BY id DESC LIMIT 20", (EV_PLAN, scenario_id))
    except Exception:  # noqa: BLE001
        return None
    for r in rows or []:
        try:
            p = json.loads(r[0]) if isinstance(r[0], str) else dict(r[0] or {})
        except (TypeError, ValueError):
            continue
        if not p.get("rejected") and p.get("confirm_msg_id"):
            return p
    return None


_PROC_START = time.time()
MILESTONE_GRACE_SEC = 900   # READY, підтверджені незадовго до запуску відстеження (доставка могла затриматись), теж відстежуємо


def milestone_since(db: str) -> float:
    """Момент першого запуску відстеження подій сценарію: старіші READY історичні — по них повідомлень не шлемо (без лавини після деплою)."""
    from office_bridge import log_event

    ev = _events(db, EV_MILESTONE_ON)
    if ev:
        return float(ev[0]["p"].get("since") or 0.0)
    now = min(time.time(), _PROC_START)   # момент старту процесу, а не першого циклу: цикл може стартувати із запізненням
    log_event(db, EV_MILESTONE_ON, {"since": now}, "")
    return now


_MS_DONE: set = set()   # плани, що завершені й повністю відпрацьовані в цьому процесі (не тягнемо свічки знову)
_MS_LAST: Dict[Any, float] = {}   # останній огляд плану (для рідшого огляду старих планів)
FRESH_SEC = 6 * 3600            # молодші плани дивимось по 1m свічках (≤ ~375 шт., вага запиту 2), старші — по 5m (до 1000 шт. ≈ 83 год)
OLD_RECHECK_SEC = 600
OLD_RECHECK_LEGACY_SEC = 1800         # старий Лев після cutover (OFFICE_OLD_READY_DELIVERY=0) — лише статистика: перегляд раз на 30 хв (раніше 10 хв давало до 725 ваги Binance за хвилину)
OLD_RECHECK_O2_SEC = 120          # Office2: активних планів одиниці — перевіряємо частіше (TP/SL старшого плану не чекає до 10 хв)
SILENT_LEVELS = ("ENTRY", "EXPIRED")   # лише запис у БД (життя сценарію й статистика); у Telegram не йдуть


def _levels_of(res: Dict[str, Any]) -> List[str]:
    lv: List[str] = []
    if res.get("filled_at") is not None:
        lv.append("ENTRY")
    lv += list(res.get("reached") or [])
    if res.get("stopped"):
        lv.append("SL")
    if res.get("status") == "NOT_FILLED":
        lv.append("EXPIRED")
    return lv


def _prio():
    try:
        from office_market_data import priority

        return priority()
    except Exception:  # noqa: BLE001
        import contextlib

        return contextlib.nullcontext()


def pending_milestones(db: str, fetch: Optional[Callable[[str, str, int], Any]] = None, now_ts: Optional[float] = None, scope: str = "all") -> List[Dict[str, Any]]:
    """Нові події життя доставлених READY (для КОЖНОГО, незалежно від кнопки «Я відкрила угоду»): ENTRY (вхід торкнуто), TP1/TP2/TP3, SL, EXPIRED (вхід так і не торкнуто до кінця строку).
    Кожна — один раз. Свічки 1m для свіжих планів (затримка ≤ ~1 хв замість ≤ 15), 5m для старших. Це рух ринку за планом, а не стан угоди користувача.
    scope: "all" — усі плани; "o2" — лише Office2 (scenario_id «O2|…»), швидкий цикл; "other" — усі, крім Office2 (повільний цикл по сотнях старих планів не затримує Office2)."""
    if fetch is None:
        from office_market_data import fetch_candles as fetch  # type: ignore[assignment]
    now = time.time() if now_ts is None else now_ts
    since = milestone_since(db)
    seen = {(e["p"].get("scenario_id"), e["p"].get("confirmed_ts"), e["p"].get("level")) for e in _events(db, EV_MILESTONE)}
    out: List[Dict[str, Any]] = []
    for ev in _events(db, EV_PLAN):
        p = ev["p"]
        if p.get("rejected") or not p.get("confirm_msg_id") or float(p.get("confirmed_ts") or 0) < since - MILESTONE_GRACE_SEC:
            continue
        sid, ct = p.get("scenario_id"), p.get("confirmed_ts")
        is_o2 = str(sid or "").startswith("O2|")
        if (scope == "o2" and not is_o2) or (scope == "other" and is_o2):
            continue
        if (sid, ct) in _MS_DONE:
            continue
        if now > float(p.get("valid_until_ts") or 0) + MAX_TRACK_SEC + 3600:
            continue
        age = now - float(ct or 0)
        fresh = age < FRESH_SEC
        if not fresh and now - _MS_LAST.get((sid, ct), 0.0) < (OLD_RECHECK_O2_SEC if is_o2 else (OLD_RECHECK_LEGACY_SEC if os.getenv("OFFICE_OLD_READY_DELIVERY", "1").strip() == "0" else OLD_RECHECK_SEC)):
            continue
        _MS_LAST[(sid, ct)] = now
        # Мінімальне навантаження на Binance REST (вага запиту росте з limit): беремо рівно стільки свічок, скільки минуло від READY (+запас)
        if fresh:
            tf, tfs = "1m", 60.0
            lim = min(1500, int(age // 60) + 15)
        else:
            tf, tfs = "5m", 300.0
            lim = min(1000, int(age // 300) + 20)
        try:
            with _prio():   # життя READY не чекає на власну паузу ваги, яку з'їли скани
                candles = fetch(p["symbol"], tf, lim)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(candles, list) or not candles:
            continue
        src = str((candles[-1] or {}).get("src") or "binance_futures") if isinstance(candles[-1], dict) else "binance_futures"
        if src != "binance_futures":   # резервний ринок (спот/Bybit) має базис: TP/SL за ним не фіксуємо, чекаємо свічки ф'ючерсів Binance
            continue
        res = simulate(p, candles, now, tf_sec=tfs, live_tail=True)
        levels = _levels_of(res)
        terminal = res["status"] not in ("PENDING", "INVALID")
        if terminal and all((sid, ct, lv) in seen for lv in levels):
            _MS_DONE.add((sid, ct))
            continue
        for lv in levels:
            if (sid, ct, lv) in seen:
                continue
            price = p.get({"ENTRY": "entry", "TP1": "tp1", "TP2": "tp2", "TP3": "tp3", "SL": "sl", "EXPIRED": "entry"}[lv])
            out.append({"scenario_id": sid, "confirmed_ts": ct, "symbol": p.get("symbol"), "direction": p.get("direction"), "level": lv,
                        "price": price, "confirm_msg_id": p.get("confirm_msg_id"), "silent": lv in SILENT_LEVELS,
                        "touched_ts": (res.get("at") or {}).get(lv), "src": src, "tf": tf})
    return out


def record_milestone(db: str, m: Dict[str, Any], msg_id: Any = None) -> None:
    from office_bridge import log_event

    log_event(db, EV_MILESTONE, {"scenario_id": m.get("scenario_id"), "confirmed_ts": m.get("confirmed_ts"), "level": m.get("level"),
                                 "symbol": m.get("symbol"), "price": m.get("price"), "msg_id": msg_id, "sent_ts": time.time(),
                                 "touched_ts": m.get("touched_ts"), "src": m.get("src"), "tf": m.get("tf")}, str(m.get("scenario_id") or ""))


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
        if _skip_same_bar("false", p.get("scenario_id"), now):
            continue   # нова 15m-свічка ще не закрилась: відповідь не зміниться
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
            _remember_bar("false", p.get("scenario_id"), candles, now)
            continue
        payload = {"scenario_id": p["scenario_id"], "symbol": p["symbol"], "direction": p["direction"], "false_expiry": res["status"] in ("TP1", "TP2", "TP3"),
                   "after_expiry_outcome": res["status"]}
        log_event(db, EV_FALSE, payload, p["scenario_id"])
        out.append(payload)
    return out

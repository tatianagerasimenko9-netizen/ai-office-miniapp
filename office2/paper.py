"""Живий paper-супровід кожного READY Office2 (не реальні ордери, не гроші; фіксований модельний ризик).

Правила (задані ДО результатів, не підганяються):
  вхід      — лише ПІСЛЯ Telegram-доставки: ціна fill = open першої 1m-свічки, що починається не раніше delivered_ts. Заднім числом входу немає.
  MISSED    — fill гірший за плановий вхід більш ніж на MAX_CHASE_R·risk, або fill уже за SL / за TP1, або немає 1m-даних про момент після доставки.
  розмір    — qty = RISK_USD / |fill − SL| (ризик $10 від фактичного входу, а не від запланованого).
  супровід  — 1m-свічки Binance після fill; у свічці з SL і ціллю — спершу SL (консервативно); після TP1 стоп у беззбиток для моделей B/C.
  витрати   — комісія 0.10% + slippage 0.05% кола від ноціоналу (office2.learning.costs).
  моделі    — A: усе на TP1; B: 50% TP1, решта TP2, BE після TP1; C: 30/40/30 на TP1/TP2/TP3, BE після TP1. Усі зберігаються окремо (порівняння, не підгонка).
Стан у БД; кожен тік перераховує позицію з fill_ts, тож рестарт Worker нічого не губить і дублів немає (PK = scenario_id).
"""
from __future__ import annotations

import json
import math
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

RISK_USD = 10.0
MAX_CHASE_R = 0.5
MAX_HOLD_SEC = 48 * 3600
MODELS = {"A": ((1.0,), False), "B": ((0.5, 0.5), True), "C": ((0.3, 0.4, 0.3), True)}

DDL = ("""CREATE TABLE IF NOT EXISTS office2_paper_position (
    scenario_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, status TEXT NOT NULL,
    generated_ts DOUBLE PRECISION, delivered_ts DOUBLE PRECISION, plan_entry DOUBLE PRECISION, sl DOUBLE PRECISION,
    tp1 DOUBLE PRECISION, tp2 DOUBLE PRECISION, tp3 DOUBLE PRECISION, fill_ts DOUBLE PRECISION, fill_price DOUBLE PRECISION,
    miss_reason TEXT, qty DOUBLE PRECISION, notional DOUBLE PRECISION, cost_usd DOUBLE PRECISION,
    tp1_ts DOUBLE PRECISION, tp2_ts DOUBLE PRECISION, tp3_ts DOUBLE PRECISION, sl_ts DOUBLE PRECISION, close_ts DOUBLE PRECISION, close_reason TEXT,
    r_a DOUBLE PRECISION, r_b DOUBLE PRECISION, r_c DOUBLE PRECISION, pnl_a DOUBLE PRECISION, pnl_b DOUBLE PRECISION, pnl_c DOUBLE PRECISION,
    mfe_r DOUBLE PRECISION, mae_r DOUBLE PRECISION, coarse INTEGER DEFAULT 0, session TEXT, btc TEXT, updated_ts DOUBLE PRECISION)""",)
_COLS = ("scenario_id", "symbol", "direction", "status", "generated_ts", "delivered_ts", "plan_entry", "sl", "tp1", "tp2", "tp3", "fill_ts", "fill_price", "miss_reason", "qty",
         "notional", "cost_usd", "tp1_ts", "tp2_ts", "tp3_ts", "sl_ts", "close_ts", "close_reason", "r_a", "r_b", "r_c", "pnl_a", "pnl_b", "pnl_c", "mfe_r", "mae_r", "coarse",
         "session", "btc", "updated_ts")
_READY = {"done": False}


def _ensure(db: str) -> None:
    if _READY["done"]:
        return
    from office_bridge import _execute

    for d in DDL:
        _execute(db, d)
    _READY["done"] = True


def _ts(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v / 1000.0 if v > 1e11 else v)
    if isinstance(v, str):
        try:
            from datetime import datetime, timezone

            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            return None
    return None


def bars_of(rows: Any) -> List[Tuple[float, float, float, float, float]]:
    """[(t, o, h, l, c)] за зростанням часу; сміття відкидається."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            t = _ts(r.get("ts"))
            o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if t is not None and all(math.isfinite(x) and x > 0 for x in (o, h, l, c)):
            out.append((t, o, h, l, c))
    out.sort()
    return out


def decide_fill(direction: str, plan_entry: float, sl: float, tp1: float, delivered_ts: float, bars: List[Tuple[float, ...]], bar_sec: float = 60.0) -> Dict[str, Any]:
    """Чи був вхід доступний ПІСЛЯ доставки. Повертає {ok, fill_ts, fill_price} або {ok False, reason}."""
    long_ = direction == "LONG"
    risk = abs(plan_entry - sl)
    if risk <= 0:
        return {"ok": False, "reason": "INVALID: нульовий ризик"}
    nxt = [b for b in bars if b[0] >= delivered_ts - 1e-6]
    if not nxt:
        return {"ok": False, "reason": "NO_DATA: немає 1m-свічок після доставки (не вигадуємо вхід)"}
    t, o = nxt[0][0], nxt[0][1]
    if t - delivered_ts > 5 * bar_sec:
        return {"ok": False, "reason": f"NO_DATA: перша свічка після доставки на {int(t - delivered_ts)} с пізніше"}
    if (long_ and o <= sl) or ((not long_) and o >= sl):
        return {"ok": False, "reason": f"MISSED: на момент доставки ціна {o:.6g} уже за SL {sl:.6g}"}
    if (long_ and o >= tp1) or ((not long_) and o <= tp1):
        return {"ok": False, "reason": f"MISSED: на момент доставки ціна {o:.6g} уже на TP1 {tp1:.6g}"}
    chase = ((o - plan_entry) if long_ else (plan_entry - o)) / risk
    if chase > MAX_CHASE_R:
        return {"ok": False, "reason": f"MISSED: вхід недоступний — ціна {o:.6g} гірша за плановий {plan_entry:.6g} на {chase:.2f}R (ліміт {MAX_CHASE_R}R)"}
    return {"ok": True, "fill_ts": t, "fill_price": o, "chase_r": chase}


def walk(direction: str, fill_ts: float, fill: float, sl: float, tps: List[Optional[float]], bars: List[Tuple[float, ...]], now: float, bar_sec: float = 60.0) -> Dict[str, Any]:
    """Хронологія за свічками ПІСЛЯ fill (свічка fill входить: вона починається після доставки). Повертає час подій і суми по моделях у R (gross, без витрат)."""
    long_ = direction == "LONG"
    risk = abs(fill - sl)
    tps = [x for x in tps if x]
    res: Dict[str, Any] = {"tp_ts": {}, "sl_ts": None, "mfe_r": 0.0, "mae_r": 0.0, "closed": {}, "last_ts": None}
    state = {m: {"left": 1.0, "r": 0.0, "stop": sl, "hit": 0, "done": False, "ts": None, "why": None} for m in MODELS}
    for t, o, h, l, c in bars:
        if t < fill_ts - 1e-6:
            continue
        if t + bar_sec > now + 1e-6 and t != fill_ts:
            continue                       # незакрита свічка
        te = min(t + bar_sec, now)
        res["last_ts"] = te
        fav = (h - fill) if long_ else (fill - l)
        adv = (fill - l) if long_ else (h - fill)
        res["mfe_r"] = max(res["mfe_r"], fav / risk)
        res["mae_r"] = max(res["mae_r"], adv / risk)
        for name, (fracs, be) in MODELS.items():
            s = state[name]
            if s["done"]:
                continue
            stop_hit = (l <= s["stop"]) if long_ else (h >= s["stop"])
            if stop_hit:                   # SL першим у спірній свічці
                s["r"] += s["left"] * (((s["stop"] - fill) if long_ else (fill - s["stop"])) / risk)
                s["done"], s["ts"], s["why"] = True, te, ("SL" if s["stop"] == sl else "BE")
                if name == "A" and s["why"] == "SL":
                    res["sl_ts"] = te
                continue
            while s["hit"] < len(fracs) and s["hit"] < len(tps):
                tp = tps[min(s["hit"], len(tps) - 1)]
                if not ((h >= tp) if long_ else (l <= tp)):
                    break
                f = fracs[s["hit"]]
                if s["hit"] == len(fracs) - 1 or s["hit"] == len(tps) - 1:
                    f = s["left"]          # остання доступна ціль забирає залишок
                s["r"] += f * (abs(tp - fill) / risk)
                s["left"] -= f
                res["tp_ts"].setdefault(f"TP{s['hit'] + 1}", te)
                s["hit"] += 1
                if be and s["hit"] == 1 and s["left"] > 1e-9:
                    s["stop"] = fill
                if s["left"] <= 1e-9:
                    s["done"], s["ts"], s["why"] = True, te, f"TP{s['hit']}"
                    break
    last_close = bars[-1][4] if bars else fill
    expired = bool(res["last_ts"]) and res["last_ts"] - fill_ts >= MAX_HOLD_SEC
    for name, s in state.items():
        if not s["done"] and expired and s["left"] > 0:
            s["r"] += s["left"] * (((last_close - fill) if long_ else (fill - last_close)) / risk)
            s["left"], s["done"], s["ts"], s["why"] = 0.0, True, res["last_ts"], "EXPIRED"
        res["closed"][name] = {"r": s["r"], "done": s["done"], "ts": s["ts"], "why": s["why"]}
    return res


def _cost_usd(notional: float) -> float:
    from office2.learning import costs as C

    return notional * C.cost_pct() / 100.0


def _rowdict(vals: tuple) -> Dict[str, Any]:
    return dict(zip(_COLS, vals))


def _save(db: str, p: Dict[str, Any]) -> None:
    from office_bridge import _execute

    p["updated_ts"] = time.time()
    ph = ",".join("?" for _ in _COLS)
    upd = ",".join(f"{c}=excluded.{c}" for c in _COLS if c != "scenario_id")
    _execute(db, f"INSERT INTO office2_paper_position({','.join(_COLS)}) VALUES ({ph}) ON CONFLICT (scenario_id) DO UPDATE SET {upd}", tuple(p.get(c) for c in _COLS))


def _from_signal(row: tuple) -> Dict[str, Any]:
    sid, sym, d, created, delivered, status, last_error, sj = row
    snap = {}
    try:
        snap = json.loads(sj)
    except Exception:  # noqa: BLE001
        pass
    th = snap.get("thesis") or {}
    tg = th.get("targets") or []
    tp = lambda i: float(tg[i]["p"]) if len(tg) > i else None  # noqa: E731
    btc = (snap.get("market_at_signal") or {}).get("btc") or (snap.get("market_at_signal") or {})
    return {"scenario_id": sid, "symbol": sym, "direction": d, "generated_ts": float(created), "delivered_ts": float(delivered) if delivered else None,
            "plan_entry": float(th["entry"]) if th.get("entry") else None, "sl": float(th["sl"]) if th.get("sl") else None, "tp1": tp(0), "tp2": tp(1), "tp3": tp(2),
            "session": ((snap.get("session_tag") or {}).get("session")), "btc": json.dumps(btc, ensure_ascii=False, default=str)[:600], "coarse": 0,
            "_status": status, "_err": last_error}


def _apply(p: Dict[str, Any], w: Dict[str, Any], now: float) -> None:
    fill = p["fill_price"]
    risk = abs(fill - p["sl"])
    p["qty"] = RISK_USD / risk if risk > 0 else 0.0
    p["notional"] = p["qty"] * fill
    p["cost_usd"] = _cost_usd(p["notional"])
    p["tp1_ts"], p["tp2_ts"], p["tp3_ts"] = (w["tp_ts"].get(k) for k in ("TP1", "TP2", "TP3"))
    p["sl_ts"] = w["sl_ts"]
    p["mfe_r"], p["mae_r"] = round(w["mfe_r"], 3), round(w["mae_r"], 3)
    cr = p["cost_usd"] / RISK_USD       # витрати в R
    done = all(w["closed"][m]["done"] for m in MODELS)
    for m, key in (("A", "a"), ("B", "b"), ("C", "c")):
        c = w["closed"][m]
        if c["done"]:
            p[f"r_{key}"] = round(c["r"] - cr, 4)
            p[f"pnl_{key}"] = round((c["r"] - cr) * RISK_USD, 2)
        else:
            p[f"r_{key}"] = p[f"pnl_{key}"] = None
    if done:
        p["status"] = "CLOSED"
        p["close_ts"] = max(w["closed"][m]["ts"] for m in MODELS)
        p["close_reason"] = w["closed"]["A"]["why"]
    else:
        p["status"] = "OPEN"


def open_position(p: Dict[str, Any], bars1: List[Tuple[float, ...]]) -> None:
    d = decide_fill(p["direction"], p["plan_entry"], p["sl"], p["tp1"], p["delivered_ts"], bars1)
    if not d["ok"]:
        p["status"], p["miss_reason"] = "MISSED", d["reason"]
        return
    p["fill_ts"], p["fill_price"], p["status"] = d["fill_ts"], d["fill_price"], "OPEN"


def tick(db: str, fetch: Callable[[str, str, int], Any], now: Optional[float] = None, log: Callable[[str], None] = print, lookback_days: int = 7) -> Dict[str, int]:
    """Один прохід: нові доставлені → вхід/MISSED; відкриті → перерахунок за свічками. Ідемпотентний."""
    from office_bridge import _fetchall

    _ensure(db)
    now = time.time() if now is None else now
    out = {"new": 0, "missed": 0, "updated": 0, "closed": 0, "errors": 0}
    known = {r[0] for r in _fetchall(db, "SELECT scenario_id FROM office2_paper_position")}
    rows = _fetchall(db, "SELECT scenario_id, symbol, direction, created_ts, delivered_ts, status, last_error, snapshot_json FROM office2_live_signal "
                         "WHERE status IN ('DELIVERED','SUPPRESSED') AND created_ts > ? ORDER BY created_ts", (now - lookback_days * 86400,))
    for row in rows:
        if row[0] in known:
            continue
        try:
            p = _from_signal(row)
            if p["_status"] == "SUPPRESSED" or not p["delivered_ts"]:
                p.update(status="MISSED", miss_reason=f"НЕ ДОСТАВЛЕНО: {str(p['_err'] or 'suppressed')[:200]}")
            elif not (p["plan_entry"] and p["sl"] and p["tp1"]):
                p.update(status="MISSED", miss_reason="INVALID: немає входу/SL/TP1 у знімку")
            else:
                n = max(5, min(1000, int((now - p["delivered_ts"]) // 60) + 5))
                open_position(p, bars_of(fetch(p["symbol"], "1m", n)))
            if p["status"] == "MISSED":
                out["missed"] += 1
            out["new"] += 1
            _save(db, {k: v for k, v in p.items() if not k.startswith("_")})
            log(f"[paper] {p['symbol']} {p['direction']} → {p['status']} {p.get('miss_reason') or ''}")
        except Exception as exc:  # noqa: BLE001
            out["errors"] += 1
            log(f"[paper] помилка відкриття {row[0]}: {type(exc).__name__}: {str(exc)[:120]}")
    for vals in _fetchall(db, f"SELECT {','.join(_COLS)} FROM office2_paper_position WHERE status = 'OPEN'"):
        p = _rowdict(vals)
        try:
            n1 = max(5, min(1000, int((now - p["fill_ts"]) // 60) + 5))
            b1 = bars_of(fetch(p["symbol"], "1m", n1))
            bars, bs, coarse = b1, 60.0, 0
            if not b1 or b1[0][0] > p["fill_ts"] + 60:       # 1m не сягає fill (довга позиція): 15m, грубіше, але SL-first
                b15 = bars_of(fetch(p["symbol"], "15m", 200))
                if b15:
                    bars, bs, coarse = [b for b in b15 if b[0] >= p["fill_ts"] - 900], 900.0, 1
            if not bars:
                continue
            p["coarse"] = coarse
            w = walk(p["direction"], p["fill_ts"], p["fill_price"], p["sl"], [p["tp1"], p["tp2"], p["tp3"]], bars, now, bs)
            _apply(p, w, now)
            _save(db, p)
            out["updated"] += 1
            out["closed"] += 1 if p["status"] == "CLOSED" else 0
        except Exception as exc:  # noqa: BLE001
            out["errors"] += 1
            log(f"[paper] помилка супроводу {p['scenario_id']}: {type(exc).__name__}: {str(exc)[:120]}")
    return out


def summary(db: str, limit: int = 30, since_ts: Optional[float] = None) -> Dict[str, Any]:
    from office_bridge import _fetchall

    out: Dict[str, Any] = {"meaning": "PAPER: модель, не реальні гроші й не ордери; ризик $10 на позицію від фактичного входу після доставки; комісія+slippage 0.15% кола", "items": [], "stats": {}}
    try:
        _ensure(db)
        w = " WHERE COALESCE(delivered_ts, generated_ts) >= ?" if since_ts else ""
        par = (since_ts,) if since_ts else ()
        rows = _fetchall(db, f"SELECT {','.join(_COLS)} FROM office2_paper_position{w} ORDER BY COALESCE(delivered_ts, generated_ts) DESC LIMIT ?", par + (limit,))
        out["items"] = [_rowdict(r) for r in rows]
        allr = [_rowdict(r) for r in _fetchall(db, f"SELECT {','.join(_COLS)} FROM office2_paper_position{w}", par)]
        cl = [x for x in allr if x["status"] == "CLOSED"]
        st: Dict[str, Any] = {"total": len(allr), "open": sum(1 for x in allr if x["status"] == "OPEN"), "closed": len(cl), "missed": sum(1 for x in allr if x["status"] == "MISSED"),
                              "fees_usd": round(sum(x["cost_usd"] or 0 for x in cl), 2), "note": "n<30 — лише спостереження"}
        for k in ("a", "b", "c"):
            v = [x[f"pnl_{k}"] for x in cl if x[f"pnl_{k}"] is not None]
            st[f"pnl_{k}_usd"] = round(sum(v), 2)
            st[f"wins_{k}"] = sum(1 for x in v if x > 0)
        st["sl"] = sum(1 for x in cl if x["close_reason"] == "SL")
        st["tp"] = sum(1 for x in cl if str(x["close_reason"]).startswith("TP"))
        out["stats"] = st
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return out

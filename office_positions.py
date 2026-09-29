"""Ручний облік угод трейдера: фактичні позиції, часткові виходи, перенесення SL, закриття.

Офіс НІКОЛИ не відкриває, не змінює і не закриває ордери. Тут лише запис того, що власниця
зробила сама на біржі, і розрахунок ризику/результату за її фактичними даними.

Зберігання:
- поточний стан позиції — рядок `trade_journal` (існуюча таблиця; `entry_reason` = POSITION_CONFIRM_REASON,
  тож Risk Officer і шлюз Telegram бачать це як підтверджену позицію; `position_qty` = залишок,
  `stop_loss` = поточний SL);
- історія дій — append-only `office_position_events` (нова адитивна таблиця, `migrate_positions`).
Схема створюється лише явною міграцією; без неї запис відхиляється (`schema_missing`).

Результат = сума за фактичними цінами виходів мінус комісії. Комісія, яку власниця не ввела,
оцінюється за OFFICE_DEFAULT_FEE_PCT і позначається `fee_estimated`. Сценарії, симуляції та реальні
угоди не змішуються: статистика рахується лише за закритими рядками цього модуля.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from office_bridge import (
    POSITION_CONFIRM_REASON,
    _fetchall,
    _fetchone,
    _is_pg,
    _now_iso,
    _sqlite_path_from_url,
)

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

SETUP_NAME = "MANUAL_POSITION"
KIND_OPEN, KIND_PARTIAL, KIND_MOVE_SL, KIND_MOVE_TP, KIND_CLOSE, KIND_VOID, KIND_NOTE = (
    "OPEN", "PARTIAL_EXIT", "MOVE_SL", "MOVE_TP", "CLOSE", "VOID", "NOTE",
)
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}(USDT|USDC)$")
QTY_EPS = 1e-12
_LOCK = threading.Lock()


class PositionError(ValueError):
    """Помилка валідації/стану з кодом і людським повідомленням (українською)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def default_fee_pct() -> float:
    try:
        v = float(os.getenv("OFFICE_DEFAULT_FEE_PCT", "0.04"))
    except ValueError:
        v = 0.04
    return v if 0 <= v < 1 else 0.04


# ---------------------------------------------------------------- schema

def _ddl(db_path: str) -> List[str]:
    pk = "BIGSERIAL PRIMARY KEY" if _is_pg(db_path) else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return [
        f"""CREATE TABLE IF NOT EXISTS office_position_events (
            id {pk},
            trade_id TEXT NOT NULL,
            ts_utc TEXT NOT NULL,
            kind TEXT NOT NULL,
            price DOUBLE PRECISION,
            qty DOUBLE PRECISION,
            fee_usdt DOUBLE PRECISION,
            fee_estimated INTEGER,
            sl DOUBLE PRECISION,
            tp1 DOUBLE PRECISION,
            tp2 DOUBLE PRECISION,
            pnl_usdt DOUBLE PRECISION,
            note TEXT,
            idem_key TEXT,
            payload_json TEXT NOT NULL
        )""",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_position_events_idem ON office_position_events(idem_key)",
        "CREATE INDEX IF NOT EXISTS ix_position_events_trade ON office_position_events(trade_id, id)",
    ]


def _connect(db_path: str):
    if _is_pg(db_path):
        if psycopg is None:
            raise RuntimeError("psycopg required for PostgreSQL mode")
        return psycopg.connect(db_path)
    return sqlite3.connect(_sqlite_path_from_url(db_path), timeout=15)


def migrate_positions(db_path: str) -> None:
    """Адитивно й ідемпотентно. Викликається лише явним кроком міграції, не запитом."""
    with _connect(db_path) as conn:
        for stmt in _ddl(db_path):
            conn.execute(stmt)


def schema_present(db_path: str) -> bool:
    try:
        _fetchone(db_path, "SELECT 1 FROM office_position_events LIMIT 1", ())
        return True
    except Exception:
        return False


def _tx(db_path: str, stmts: List[Tuple[str, tuple]]) -> None:
    """Усі оператори — в одній транзакції (commit при виході, rollback при помилці)."""
    with _connect(db_path) as conn:
        for sql, params in stmts:
            conn.execute(sql.replace("?", "%s") if _is_pg(db_path) else sql, params)


# ---------------------------------------------------------------- helpers

def _num(v: Any, name: str, *, required: bool = True, positive: bool = True) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        if required:
            raise PositionError("missing_" + name, f"Поле «{name}» обов’язкове.")
        return None
    try:
        x = float(str(v).strip().replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        raise PositionError("bad_" + name, f"Поле «{name}» має бути числом.")
    if x != x or x in (float("inf"), float("-inf")):
        raise PositionError("bad_" + name, f"Поле «{name}» має бути скінченним числом.")
    if positive and x <= 0:
        raise PositionError("bad_" + name, f"Поле «{name}» має бути більшим за нуль.")
    if not positive and x < 0:
        raise PositionError("bad_" + name, f"Поле «{name}» не може бути від’ємним.")
    return x


def _side(v: Any) -> str:
    s = str(v or "").strip().upper()
    if s not in ("LONG", "SHORT"):
        raise PositionError("bad_direction", "Напрям має бути LONG або SHORT.")
    return s


def _sign(side: str) -> int:
    return 1 if side == "LONG" else -1


def _check_geometry(side: str, entry: float, sl: float, tp1: Optional[float], tp2: Optional[float]) -> None:
    if side == "LONG" and not sl < entry:
        raise PositionError("geometry", "Для LONG стоп має бути нижче ціни входу.")
    if side == "SHORT" and not sl > entry:
        raise PositionError("geometry", "Для SHORT стоп має бути вище ціни входу.")
    _check_targets(side, entry, tp1, tp2)


def _check_targets(side: str, entry: float, tp1: Optional[float], tp2: Optional[float]) -> None:
    for name, tp in (("TP1", tp1), ("TP2", tp2)):
        if tp is None:
            continue
        if side == "LONG" and not tp > entry:
            raise PositionError("geometry", f"Для LONG {name} має бути вище ціни входу.")
        if side == "SHORT" and not tp < entry:
            raise PositionError("geometry", f"Для SHORT {name} має бути нижче ціни входу.")
    if tp1 is not None and tp2 is not None and ((side == "LONG" and tp2 <= tp1) or (side == "SHORT" and tp2 >= tp1)):
        raise PositionError("geometry", "TP2 має бути далі від входу, ніж TP1.")


def _r8(x: float) -> float:
    return round(float(x), 8)


def _fee(fee_usdt: Any, notional: float) -> Tuple[float, bool]:
    given = _num(fee_usdt, "комісія", required=False, positive=False)
    if given is not None:
        return _r8(given), False
    return _r8(notional * default_fee_pct() / 100.0), True


def _new_trade_id(symbol: str) -> str:
    return f"man-{symbol}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(2)}"


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        raise PositionError("bad_opened_at", "Час відкриття має бути у форматі ISO (наприклад 2026-09-29T10:15).")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt > datetime.now(timezone.utc):
        raise PositionError("bad_opened_at", "Час відкриття не може бути в майбутньому.")
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- reading

_COLS = ("trade_id, ts_open_utc, ts_close_utc, symbol, direction, status, entry_price, stop_loss, take_profit, "
         "position_qty, exit_price, outcome, pnl_pct, fees_pct, r_multiple, setup_name, entry_reason, exit_reason, "
         "review_note, context_json")


def _row_to_dict(r: tuple) -> Dict[str, Any]:
    keys = [c.strip() for c in _COLS.split(",")]
    d = dict(zip(keys, r))
    try:
        d["context"] = json.loads(d.pop("context_json") or "{}")
    except Exception:
        d["context"] = {}
    return d


def _load_row(db_path: str, trade_id: str) -> Dict[str, Any]:
    r = _fetchone(db_path, f"SELECT {_COLS} FROM trade_journal WHERE trade_id = ?", (str(trade_id),))
    if not r:
        raise PositionError("not_found", "Угоду не знайдено.")
    d = _row_to_dict(r)
    if d.get("setup_name") != SETUP_NAME:
        raise PositionError("not_manual", "Це не ручна угода — змінювати її тут не можна.")
    return d


def summarize(row: Dict[str, Any]) -> Dict[str, Any]:
    """Похідні показники з фактичних даних. Невідоме лишається None."""
    ctx = row.get("context") or {}
    side = str(row.get("direction") or "").upper()
    entry = float(row.get("entry_price") or 0)
    remaining = float(row.get("position_qty") or 0)
    sl = row.get("stop_loss")
    sl = float(sl) if sl is not None else None
    initial_qty = float(ctx.get("initial_qty") or remaining or 0)
    initial_risk = ctx.get("initial_risk_usdt")
    realized_gross = float(ctx.get("realized_gross_usdt") or 0.0)
    fees = float(ctx.get("fees_usdt") or 0.0)
    net = realized_gross - fees
    status = str(row.get("status") or "").upper()
    open_ = status == "OPEN"
    risk_now = None
    locked = None
    if open_ and sl is not None and entry > 0:
        per_unit = (entry - sl) * _sign(side)  # >0: ще ризикуємо, <0: стоп за беззбитком
        risk_now = _r8(max(0.0, per_unit) * remaining)
        locked = _r8(max(0.0, -per_unit) * remaining)
    return {
        "trade_id": row["trade_id"], "symbol": row["symbol"], "direction": side, "status": status,
        "entry": entry, "sl": sl, "tp1": row.get("take_profit"), "tp2": ctx.get("tp2"),
        "initial_qty": _r8(initial_qty), "remaining_qty": _r8(remaining),
        "notional_usdt": _r8(entry * remaining) if open_ else None,
        "initial_risk_usdt": initial_risk, "risk_now_usdt": risk_now, "locked_profit_usdt": locked,
        "realized_gross_usdt": _r8(realized_gross), "fees_usdt": _r8(fees), "realized_net_usdt": _r8(net),
        "fees_estimated": bool(ctx.get("fees_estimated")),
        "r_realized": _r8(net / initial_risk) if initial_risk else None,
        "opened_at": row.get("ts_open_utc"), "closed_at": row.get("ts_close_utc"),
        "outcome": row.get("outcome"), "exit_price": row.get("exit_price"),
        "scenario_id": ctx.get("scenario_id") or None, "source": ctx.get("source") or "manual",
        "note": row.get("review_note") or "",
        "is_real_position": True,  # факт, внесений власницею; не сигнал і не симуляція
    }


def events_for(db_path: str, trade_id: str) -> List[Dict[str, Any]]:
    rows = _fetchall(
        db_path,
        "SELECT id, ts_utc, kind, price, qty, fee_usdt, fee_estimated, sl, tp1, tp2, pnl_usdt, note "
        "FROM office_position_events WHERE trade_id = ? ORDER BY id",
        (str(trade_id),),
    )
    keys = ("id", "ts", "kind", "price", "qty", "fee_usdt", "fee_estimated", "sl", "tp1", "tp2", "pnl_usdt", "note")
    return [dict(zip(keys, r)) for r in rows]


def get_position(db_path: str, trade_id: str) -> Dict[str, Any]:
    s = summarize(_load_row(db_path, trade_id))
    s["events"] = events_for(db_path, trade_id)
    return s


def list_positions(db_path: str, state: str = "open", limit: int = 100) -> List[Dict[str, Any]]:
    cond = {"open": "status = 'OPEN'", "closed": "status = 'CLOSED'"}.get(state, "status IN ('OPEN','CLOSED')")
    rows = _fetchall(
        db_path,
        f"SELECT {_COLS} FROM trade_journal WHERE setup_name = ? AND {cond} ORDER BY ts_open_utc DESC LIMIT ?",
        (SETUP_NAME, int(limit)),
    )
    return [summarize(_row_to_dict(r)) for r in rows]


def stats(db_path: str, *, min_sample: int = 20) -> Dict[str, Any]:
    """Лише закриті ручні угоди. Немає закритих → «немає даних», не нулі."""
    closed = list_positions(db_path, "closed", 1000)
    n = len(closed)
    if not n:
        return {"n": 0, "data_status": "EMPTY", "note": "Закритих ручних угод ще немає."}
    wins = sum(1 for p in closed if (p["realized_net_usdt"] or 0) > 0)
    net = sum(p["realized_net_usdt"] for p in closed)
    fees = sum(p["fees_usdt"] for p in closed)
    rs = [p["r_realized"] for p in closed if p["r_realized"] is not None]
    out = {
        "n": n, "wins": wins, "losses": sum(1 for p in closed if (p["realized_net_usdt"] or 0) < 0),
        "net_usdt": _r8(net), "fees_usdt": _r8(fees), "sum_r": _r8(sum(rs)) if rs else None,
        "avg_r": _r8(sum(rs) / len(rs)) if rs else None,
        "any_fee_estimated": any(p["fees_estimated"] for p in closed),
        "data_status": "DATA_OK",
    }
    if n < min_sample:
        out["wr_pct"] = None
        out["note"] = f"n={n} < {min_sample}: відсоток виграшів не показуємо."
    else:
        out["wr_pct"] = round(wins / n * 100, 1)
    return out


def exposure(db_path: str) -> Dict[str, Any]:
    """Поточний ризик відкритих ручних позицій. Порожньо ≠ «експозиції немає» — це «нічого не внесено»."""
    open_ = list_positions(db_path, "open", 500)
    if not open_:
        return {"n_open": 0, "risk_now_usdt": None, "status": "NONE_RECORDED",
                "text": "Відкритих позицій не внесено. Якщо на біржі вони є — внесіть їх, інакше ризик показано неповним."}
    risk = sum((p["risk_now_usdt"] or 0.0) for p in open_)
    return {"n_open": len(open_), "risk_now_usdt": _r8(risk),
            "notional_usdt": _r8(sum(p["notional_usdt"] or 0.0 for p in open_)),
            "locked_profit_usdt": _r8(sum(p["locked_profit_usdt"] or 0.0 for p in open_)),
            "status": "OK", "text": f"Внесено відкритих позицій: {len(open_)}."}


# ---------------------------------------------------------------- writing

def _event_stmt(trade_id: str, kind: str, *, price=None, qty=None, fee=None, fee_est=None, sl=None, tp1=None,
                tp2=None, pnl=None, note="", idem_key="", payload=None, ts: Optional[str] = None) -> Tuple[str, tuple]:
    return (
        "INSERT INTO office_position_events (trade_id, ts_utc, kind, price, qty, fee_usdt, fee_estimated, sl, tp1, tp2, "
        "pnl_usdt, note, idem_key, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (trade_id, ts or _now_iso(), kind, price, qty, fee, None if fee_est is None else int(fee_est), sl, tp1, tp2,
         pnl, (note or "")[:500], idem_key or None, json.dumps(payload or {}, ensure_ascii=False)),
    )


def _ensure_ready(db_path: str) -> None:
    if not schema_present(db_path):
        raise PositionError("schema_missing", "Облік угод ще не активовано: потрібна міграція бази (scripts/migrate_release.py).")


def _idem_seen(db_path: str, idem_key: str) -> bool:
    if not idem_key:
        return False
    return bool(_fetchone(db_path, "SELECT 1 FROM office_position_events WHERE idem_key = ?", (idem_key,)))


def _save_ctx(row: Dict[str, Any], patch: Dict[str, Any]) -> str:
    ctx = dict(row.get("context") or {})
    ctx.update(patch)
    return json.dumps(ctx, ensure_ascii=False)


def open_position(
    db_path: str, *, symbol: Any, direction: Any, entry: Any, qty: Any, sl: Any, tp1: Any = None, tp2: Any = None,
    fee_usdt: Any = None, opened_at: Any = None, scenario_id: str = "", note: str = "", idem_key: str = "",
) -> Dict[str, Any]:
    """Внести позицію, яку власниця відкрила сама (у т.ч. без сценарію Лева)."""
    _ensure_ready(db_path)
    sym = str(symbol or "").strip().upper()
    if not SYMBOL_RE.match(sym):
        raise PositionError("bad_symbol", "Символ має виглядати як BTCUSDT.")
    side = _side(direction)
    e = _num(entry, "ціна входу")
    q = _num(qty, "обсяг")
    s = _num(sl, "стоп")
    t1 = _num(tp1, "TP1", required=False)
    t2 = _num(tp2, "TP2", required=False)
    _check_geometry(side, e, s, t1, t2)
    ts = _parse_ts(opened_at)
    fee, fee_est = _fee(fee_usdt, e * q)
    risk = _r8(abs(e - s) * q)
    tid = _new_trade_id(sym)
    ctx = {"kind": "manual_position", "source": "manual_existing" if not scenario_id else "manual_from_scenario",
           "scenario_id": scenario_id or None, "tp2": t2, "initial_qty": q, "initial_sl": s,
           "initial_risk_usdt": risk, "realized_gross_usdt": 0.0, "fees_usdt": fee, "fees_estimated": fee_est}
    ts_iso = (ts or datetime.now(timezone.utc)).isoformat()
    with _LOCK:
        if _idem_seen(db_path, idem_key):
            raise PositionError("duplicate", "Цю дію вже виконано (повторне натискання).")
        _tx(db_path, [
            ("INSERT INTO trade_journal(trade_id, ts_open_utc, ts_close_utc, symbol, direction, status, entry_price, "
             "stop_loss, take_profit, position_qty, exit_price, outcome, pnl_pct, fees_pct, r_multiple, setup_name, "
             "timeframe, entry_reason, exit_reason, mistake_tags_json, review_note, context_json) "
             "VALUES (?,?,NULL,?,?,'OPEN',?,?,?,?,NULL,NULL,NULL,NULL,NULL,?,?,?,NULL,'[]',?,?)",
             (tid, ts_iso, sym, side, e, s, t1, q, SETUP_NAME, "", POSITION_CONFIRM_REASON, (note or "")[:500],
              json.dumps(ctx, ensure_ascii=False))),
            _event_stmt(tid, KIND_OPEN, price=e, qty=q, fee=fee, fee_est=fee_est, sl=s, tp1=t1, tp2=t2, note=note,
                        idem_key=idem_key, payload={"scenario_id": scenario_id or None}, ts=ts_iso),
        ])
    return get_position(db_path, tid)


def _require_open(row: Dict[str, Any]) -> None:
    if str(row.get("status") or "").upper() != "OPEN":
        raise PositionError("not_open", "Угода вже закрита або скасована.")


def partial_exit(db_path: str, trade_id: str, *, price: Any, qty: Any, fee_usdt: Any = None, note: str = "",
                 idem_key: str = "") -> Dict[str, Any]:
    _ensure_ready(db_path)
    with _LOCK:
        if _idem_seen(db_path, idem_key):
            raise PositionError("duplicate", "Цю дію вже виконано (повторне натискання).")
        row = _load_row(db_path, trade_id)
        _require_open(row)
        p = _num(price, "ціна виходу")
        q = _num(qty, "обсяг виходу")
        remaining = float(row["position_qty"])
        if q >= remaining - QTY_EPS:
            raise PositionError("qty_too_big", "Обсяг не менший за залишок — використайте «Закрити позицію».")
        side, entry = row["direction"], float(row["entry_price"])
        pnl = _r8((p - entry) * q * _sign(side))
        fee, fee_est = _fee(fee_usdt, p * q)
        ctx = row["context"]
        new_ctx = _save_ctx(row, {
            "realized_gross_usdt": _r8(float(ctx.get("realized_gross_usdt") or 0) + pnl),
            "fees_usdt": _r8(float(ctx.get("fees_usdt") or 0) + fee),
            "fees_estimated": bool(ctx.get("fees_estimated")) or fee_est,
        })
        _tx(db_path, [
            ("UPDATE trade_journal SET position_qty = ?, context_json = ? WHERE trade_id = ? AND status = 'OPEN'",
             (_r8(remaining - q), new_ctx, trade_id)),
            _event_stmt(trade_id, KIND_PARTIAL, price=p, qty=q, fee=fee, fee_est=fee_est, pnl=pnl, note=note,
                        idem_key=idem_key),
        ])
    return get_position(db_path, trade_id)


def move_sl(db_path: str, trade_id: str, *, sl: Any, note: str = "", idem_key: str = "") -> Dict[str, Any]:
    _ensure_ready(db_path)
    with _LOCK:
        if _idem_seen(db_path, idem_key):
            raise PositionError("duplicate", "Цю дію вже виконано (повторне натискання).")
        row = _load_row(db_path, trade_id)
        _require_open(row)
        s = _num(sl, "стоп")
        side = row["direction"]
        tp1 = row.get("take_profit")
        if tp1 is not None and ((side == "LONG" and s >= float(tp1)) or (side == "SHORT" and s <= float(tp1))):
            raise PositionError("geometry", "Стоп не може бути за TP1 або на ньому.")
        _tx(db_path, [
            ("UPDATE trade_journal SET stop_loss = ? WHERE trade_id = ? AND status = 'OPEN'", (s, trade_id)),
            _event_stmt(trade_id, KIND_MOVE_SL, sl=s, note=note, idem_key=idem_key,
                        payload={"previous_sl": row.get("stop_loss")}),
        ])
    return get_position(db_path, trade_id)


def move_tp(db_path: str, trade_id: str, *, tp1: Any = None, tp2: Any = None, note: str = "",
            idem_key: str = "") -> Dict[str, Any]:
    _ensure_ready(db_path)
    with _LOCK:
        if _idem_seen(db_path, idem_key):
            raise PositionError("duplicate", "Цю дію вже виконано (повторне натискання).")
        row = _load_row(db_path, trade_id)
        _require_open(row)
        t1 = _num(tp1, "TP1", required=False)
        t2 = _num(tp2, "TP2", required=False)
        if t1 is None and t2 is None:
            raise PositionError("missing_tp", "Вкажіть TP1 та/або TP2.")
        side, entry = row["direction"], float(row["entry_price"])
        new_t1 = t1 if t1 is not None else row.get("take_profit")
        new_t2 = t2 if t2 is not None else (row["context"] or {}).get("tp2")
        _check_targets(side, entry, new_t1, new_t2)
        _tx(db_path, [
            ("UPDATE trade_journal SET take_profit = ?, context_json = ? WHERE trade_id = ? AND status = 'OPEN'",
             (new_t1, _save_ctx(row, {"tp2": new_t2}), trade_id)),
            _event_stmt(trade_id, KIND_MOVE_TP, tp1=t1, tp2=t2, note=note, idem_key=idem_key),
        ])
    return get_position(db_path, trade_id)


def close_position(db_path: str, trade_id: str, *, price: Any, fee_usdt: Any = None, note: str = "",
                   exit_reason: str = "", idem_key: str = "") -> Dict[str, Any]:
    _ensure_ready(db_path)
    with _LOCK:
        if _idem_seen(db_path, idem_key):
            raise PositionError("duplicate", "Цю дію вже виконано (повторне натискання).")
        row = _load_row(db_path, trade_id)
        _require_open(row)
        p = _num(price, "ціна виходу")
        remaining = float(row["position_qty"])
        side, entry = row["direction"], float(row["entry_price"])
        pnl = _r8((p - entry) * remaining * _sign(side))
        fee, fee_est = _fee(fee_usdt, p * remaining)
        ctx = row["context"]
        gross = _r8(float(ctx.get("realized_gross_usdt") or 0) + pnl)
        fees = _r8(float(ctx.get("fees_usdt") or 0) + fee)
        est = bool(ctx.get("fees_estimated")) or fee_est
        net = gross - fees
        risk = ctx.get("initial_risk_usdt") or 0
        eps = 1e-9 * max(1.0, abs(entry * float(ctx.get("initial_qty") or 1)))
        outcome = "BE" if abs(net) <= eps else ("WIN" if net > 0 else "LOSS")
        notional0 = entry * float(ctx.get("initial_qty") or remaining)
        pnl_pct = _r8(net / notional0 * 100.0) if notional0 else None
        fees_pct = _r8(fees / notional0 * 100.0) if notional0 else None
        r_mult = _r8(net / risk) if risk else None
        new_ctx = _save_ctx(row, {"realized_gross_usdt": gross, "fees_usdt": fees, "fees_estimated": est})
        _tx(db_path, [
            ("UPDATE trade_journal SET status = 'CLOSED', ts_close_utc = ?, exit_price = ?, outcome = ?, pnl_pct = ?, "
             "fees_pct = ?, r_multiple = ?, exit_reason = ?, position_qty = 0, review_note = COALESCE(NULLIF(?, ''), "
             "review_note), context_json = ? WHERE trade_id = ? AND status = 'OPEN'",
             (_now_iso(), p, outcome, pnl_pct, fees_pct, r_mult, (exit_reason or "manual close")[:200], (note or "")[:500],
              new_ctx, trade_id)),
            _event_stmt(trade_id, KIND_CLOSE, price=p, qty=remaining, fee=fee, fee_est=fee_est, pnl=pnl, note=note,
                        idem_key=idem_key, payload={"outcome": outcome, "net_usdt": _r8(net), "r": r_mult}),
        ])
    return get_position(db_path, trade_id)


def void_position(db_path: str, trade_id: str, *, reason: str, idem_key: str = "") -> Dict[str, Any]:
    """Скасувати помилково внесений запис. Не видаляє: статус VOIDED, з подією; з ризику й статистики зникає."""
    _ensure_ready(db_path)
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise PositionError("missing_reason", "Вкажіть причину скасування запису.")
    with _LOCK:
        if _idem_seen(db_path, idem_key):
            raise PositionError("duplicate", "Цю дію вже виконано (повторне натискання).")
        row = _load_row(db_path, trade_id)
        _require_open(row)
        _tx(db_path, [
            ("UPDATE trade_journal SET status = 'VOIDED', ts_close_utc = ?, exit_reason = ?, position_qty = 0 "
             "WHERE trade_id = ? AND status = 'OPEN'", (_now_iso(), ("VOID: " + reason)[:200], trade_id)),
            _event_stmt(trade_id, KIND_VOID, note=reason, idem_key=idem_key),
        ])
    return get_position(db_path, trade_id)


def add_note(db_path: str, trade_id: str, *, note: str, idem_key: str = "") -> Dict[str, Any]:
    _ensure_ready(db_path)
    note = (note or "").strip()
    if not note:
        raise PositionError("missing_note", "Нотатка порожня.")
    with _LOCK:
        if _idem_seen(db_path, idem_key):
            raise PositionError("duplicate", "Цю дію вже виконано (повторне натискання).")
        row = _load_row(db_path, trade_id)
        _tx(db_path, [
            ("UPDATE trade_journal SET review_note = ? WHERE trade_id = ?", (note[:500], trade_id)),
            _event_stmt(trade_id, KIND_NOTE, note=note, idem_key=idem_key),
        ])
    return get_position(db_path, trade_id)


# ---------------------------------------------------------------- informational tracking (never acts)

def tracking(pos: Dict[str, Any], *, price: Optional[float], price_fresh: bool,
             scenario_status: Optional[str] = None) -> Dict[str, Any]:
    """Інформаційний супровід відкритої позиції за ЖИВОЮ ціною. Не змінює ордерів і записів."""
    out: Dict[str, Any] = {"price": price, "price_fresh": bool(price_fresh and price), "flags": [], "advisory_only": True}
    if pos.get("status") != "OPEN":
        return out
    if not out["price_fresh"]:
        out["flags"].append({"code": "NO_FRESH_PRICE", "text": "Свіжої ціни немає — показники за ціною не розраховано."})
    else:
        side, entry = pos["direction"], pos["entry"]
        rem = pos["remaining_qty"]
        sgn = _sign(side)
        unreal = _r8((price - entry) * rem * sgn)
        out["unrealized_usdt"] = unreal
        risk0 = pos.get("initial_risk_usdt")
        out["unrealized_r"] = _r8(unreal / risk0) if risk0 else None
        sl, t1, t2 = pos.get("sl"), pos.get("tp1"), pos.get("tp2")
        if sl:
            out["to_sl_pct"] = _r8(abs(price - sl) / price * 100.0)
            if (side == "LONG" and price <= sl) or (side == "SHORT" and price >= sl):
                out["flags"].append({"code": "PRICE_BEYOND_SL",
                                     "text": "Ціна досягла або перейшла ваш стоп. Перевірте фактичний стан ордера на біржі."})
        for name, lvl in (("TP1", t1), ("TP2", t2)):
            if lvl:
                out["to_" + name.lower() + "_pct"] = _r8(abs(lvl - price) / price * 100.0)
                if (side == "LONG" and price >= lvl) or (side == "SHORT" and price <= lvl):
                    out["flags"].append({"code": name + "_REACHED_BY_PRICE",
                                         "text": f"Ціна на рівні {name} або за ним. Рішення про фіксацію — за вами."})
    if scenario_status:
        st = str(scenario_status).upper()
        out["scenario_status"] = st
        if st in ("INVALIDATED", "CANCELLED", "EXPIRED", "HIT_SL"):
            out["flags"].append({"code": "SCENARIO_" + st,
                                 "text": "Початковий сценарій Лева втратив чинність. Це інформація, не наказ закривати."})
    return out

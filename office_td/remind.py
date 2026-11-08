"""TD-V1 · нагадування про відкриту угоду в плюсі (лише інформація, відповіддю на картку сигналу). Рішення завжди за власницею; жодних дій, ордерів і порад.
Умова: ENTRY є, SL/TP/інших завершень немає, угода відкрита >= TD_REMIND_H годин, поточний плюс >= TD_REMIND_R (у R від стопа).
Повторюється не частіше ніж раз на TD_REMIND_EVERY_H годин, не більше TD_REMIND_MAX разів на угоду. Вимкнути: TD_REMIND=0."""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

DDL = """CREATE TABLE IF NOT EXISTS td_reminder (
    sig_id TEXT PRIMARY KEY, n INTEGER NOT NULL, last_ts DOUBLE PRECISION NOT NULL)"""
TERMINAL = {"SL", "TP1", "TP2", "TP3", "AMBIGUOUS", "CANCEL"}


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return os.getenv("TD_REMIND", "1").strip().lower() in ("1", "true", "yes", "on")


def due(entry_ts: float, now: float, r_now: float, n_sent: int, last_ts: Optional[float]) -> bool:
    """Чиста логіка: чи пора надсилати нагадування."""
    if r_now < _f("TD_REMIND_R", 1.0): return False
    if now - entry_ts < _f("TD_REMIND_H", 8.0) * 3600: return False
    if n_sent >= int(_f("TD_REMIND_MAX", 4)): return False
    if last_ts is not None and now - last_ts < _f("TD_REMIND_EVERY_H", 12.0) * 3600: return False
    return True


def text(row: Dict[str, Any], hours: float, r_now: float, r_tp: float) -> str:
    from office_br import card
    sym = str(row["symbol"]).replace("USDT", "")
    num = lambda x: f"{x:+.1f}".replace(".", ",")
    return (f"ЗВЕРХУ ВНИЗ ТЕСТ · №{int(row['seq'])} · {sym} {row['direction']}: відкрита {int(hours)} год, зараз {num(r_now)}R (+${10 * r_now:.0f} при ризику $10). "
            f"Ціль {num(r_tp)}R, стоп −1R. Рішення за вами. {card.TD_TAG}")


async def remind_open(db: str, fetch: Callable, send: Callable, now: Optional[float] = None) -> int:
    """Викликається з моніторингу B&R. Повертає кількість надісланих нагадувань."""
    if not enabled(): return 0
    import asyncio, json
    from office_bridge import _execute, _fetchone
    from office_br import card, store
    now = time.time() if now is None else now; sent = 0
    _execute(db, DDL, ())
    for row in store.rows(db, "WHERE status = 'SENT'"):
        if not card.is_td(row) or row.get("msg_id") is None: continue
        sid = row["sig_id"]; evs = store.events(db, sid); lv = {e["level"] for e in evs}
        if "ENTRY" not in lv or lv & TERMINAL: continue
        entry_ts = float(next(e["touched_ts"] for e in evs if e["level"] == "ENTRY"))
        st = _fetchone(db, "SELECT n, last_ts FROM td_reminder WHERE sig_id = ?", (sid,))
        n_sent, last_ts = (int(st[0]), float(st[1])) if st else (0, None)
        if now - entry_ts < _f("TD_REMIND_H", 8.0) * 3600 or n_sent >= int(_f("TD_REMIND_MAX", 4)): continue     # дешева відсічка до запиту цін
        candles = await asyncio.to_thread(fetch, row["symbol"], "1m", 5, closed_only=True)
        if not isinstance(candles, list) or not candles: continue
        try:
            px = float(candles[-1]["close"])
        except Exception:  # noqa: BLE001
            continue
        side = 1 if row["direction"] == "LONG" else -1; entry, sl = float(row["entry"]), float(row["sl"]); risk = abs(entry - sl)
        if risk <= 0: continue
        tp = float(json.loads(row["targets_json"])[0]["p"]); r_now = side * (px - entry) / risk; r_tp = abs(tp - entry) / risk
        if r_now >= r_tp or r_now <= -1: continue          # ціль/стоп уже за ціною: це справа супроводу, не нагадування
        if not due(entry_ts, now, r_now, n_sent, last_ts): continue
        msg = await send(text(row, (now - entry_ts) / 3600, r_now, r_tp), reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
        if not msg: continue
        _execute(db, "INSERT INTO td_reminder(sig_id, n, last_ts) VALUES (?,?,?) ON CONFLICT (sig_id) DO UPDATE SET n = EXCLUDED.n, last_ts = EXCLUDED.last_ts", (sid, n_sent + 1, now))
        sent += 1
        print(f"[td-remind] {sid} {r_now:+.2f}R (нагадування {n_sent + 1})", flush=True)
    return sent

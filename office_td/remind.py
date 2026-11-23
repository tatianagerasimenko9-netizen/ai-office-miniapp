"""TD-V1 · нагадування про відкриту угоду в плюсі (лише інформація, відповіддю на картку сигналу). Рішення завжди за власницею; жодних дій, ордерів і порад.
Нагадування приходить, коли плюс (за останнім закриттям M1) уперше досягає рівня з TD_REMIND_LEVELS (за замовчуванням 1,2,3 R), по одному разу на рівень. ENTRY має бути, SL/TP/інших завершень немає.
Чому без очікування годин: на історії 2024-2026 медіана часу до першого +1R 2,2 год, а після +1R 49% угод закінчуються стопом (docs/handoff/br-profitability/timing_out.txt).
Вимкнути: TD_REMIND=0."""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

DDL = """CREATE TABLE IF NOT EXISTS td_reminder (
    sig_id TEXT PRIMARY KEY, n INTEGER NOT NULL, last_ts DOUBLE PRECISION NOT NULL)"""
DDL_DAY = """CREATE TABLE IF NOT EXISTS td_day_note (
    sig_id TEXT NOT NULL, kind TEXT NOT NULL, ts DOUBLE PRECISION NOT NULL, r DOUBLE PRECISION, sent INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (sig_id, kind))"""
DAY_WINDOWS = (("d1", 24.0, 30.0), ("d3", 72.0, 78.0))     # СВІНГ: перевірка наприкінці 1-ї та 3-ї доби після входу (вікно 6 год, один раз)
GIVEBACK_TEXT = "💡 Гарний плюс. Такі угоди часто трохи відкочуються — це нормально. Тримай до дня закриття."
D1_TEXT = "⚠️ Перша доба в мінусі. Такі угоди найчастіше закінчуються стопом (8 з 10)."
D3_TEXT = "🌟 Третя доба і вже гарний плюс."


def day_note(kind: str, r_now: float) -> Optional[str]:
    """СВІНГ, історія 2022–2026 (журнал, розділ AA): 1-ша доба ≤ −0,5R → стоп у 82%; 3-тя доба ≥ +2R → +3R і більше у 52%, стоп у 6%. Лише інформація."""
    if kind == "d1" and r_now <= -0.5: return D1_TEXT
    if kind == "d3" and r_now >= 2.0: return D3_TEXT
    return None


TERMINAL = {"SL", "TP1", "TP2", "TP3", "AMBIGUOUS", "CANCEL"}


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def enabled() -> bool:
    return os.getenv("TD_REMIND", "1").strip().lower() in ("1", "true", "yes", "on")


def levels() -> List[float]:
    raw = os.getenv("TD_REMIND_LEVELS", "1,2,3")
    try:
        out = sorted({float(x) for x in raw.split(",") if x.strip()})
    except ValueError:
        out = [1.0, 2.0, 3.0]
    return out or [1.0, 2.0, 3.0]


def due(r_now: float, n_sent: int) -> int:
    """Чиста логіка: скільки рівнів уже пройдено (0 = нічого нового). Повертає нове значення n, якщо пора слати нагадування, інакше n_sent."""
    lv = levels(); reached = sum(1 for x in lv if r_now >= x)
    return reached if reached > n_sent else n_sent


def text(row: Dict[str, Any], r_now: float) -> str:
    from office_br import card
    sym = str(row["symbol"]).replace("USDT", "")
    num = lambda x: f"{x:+.1f}".replace(".", ",")
    msg = f"{card.head(row)} · {sym} {row['direction']} · зараз {num(r_now)}R (+${10 * r_now:.0f}) {card.TD_TAG}"
    if card.is_swing(row):                       # СВІНГ: спочатку долари, R у дужках (прохання власниці 23.11)
        msg = f"{card.head(row)} · {sym} {row['direction']} · зараз +${10 * r_now:.0f} (це {num(r_now).lstrip('+')}R) {card.TD_TAG}"
    if card.is_swing(row) and r_now >= 2.0:      # СВІНГ: беззбиток після +2R на історії 2022–2026 не шкодить і не допомагає (журнал, розділ M); лише підказка
        try:
            msg += f"\n🔒 можна перенести стоп у беззбиток: {card._n(float(row['entry']), row['symbol'])}"
        except Exception:  # noqa: BLE001
            pass
        msg += "\n" + GIVEBACK_TEXT
    if card.is_swing(row):
        nxt = _next_level(row, r_now)
        if nxt: msg += f"\n📍 +${10 * nxt[0]} буде на ціні {nxt[1]}"
    return msg


def _price_at(row: Dict[str, Any], k: float) -> str:
    """Ціна, на якій угода має +k·R (k<0 — мінус), у форматі картки."""
    from office_br import card
    e, sl = float(row["entry"]), float(row["sl"]); side = 1 if row["direction"] == "LONG" else -1
    return card._n(e + side * k * abs(e - sl), row["symbol"])


def _next_level(row: Dict[str, Any], r_now: float):
    """Наступний цілий рівень вище поточного (до +5R; ціль 6R — окремий рядок на картці): (k, ціна) або None."""
    try:
        k = int(r_now) + 1
        return (k, _price_at(row, k)) if 1 <= k <= 5 else None
    except Exception:  # noqa: BLE001
        return None


def day_text(row: Dict[str, Any], r_now: float, note: str) -> str:
    from office_br import card
    sym = str(row["symbol"]).replace("USDT", "")
    usd = f"{'+' if r_now >= 0 else '−'}${abs(10 * r_now):.0f}"
    out = f"{card.head(row)} · {sym} {row['direction']} · зараз {usd} {card.TD_TAG}\n{note}"
    try:
        if note == D1_TEXT:
            out += f"\n🔴 Стоп стоїть на {card._n(float(row['sl']), row['symbol'])} (−$10). Робити нічого не треба."
        elif note == D3_TEXT:
            out += (f" Половина таких угод доходить до ціни {_price_at(row, 3)} (+$30) і далі." if r_now < 3 else " Половина таких угод закінчується на +$30 і більше.") + "\nСтоп буває рідко (6 зі 100)."
    except Exception:  # noqa: BLE001
        pass
    return out


async def remind_open(db: str, fetch: Callable, send: Callable, now: Optional[float] = None) -> int:
    """Викликається з моніторингу B&R. Повертає кількість надісланих нагадувань."""
    if not enabled(): return 0
    import asyncio, json
    from office_bridge import _execute, _fetchone
    from office_br import card, store
    now = time.time() if now is None else now; sent = 0
    _execute(db, DDL, ()); _execute(db, DDL_DAY, ())
    for row in store.rows(db, "WHERE status = 'SENT'"):
        if not card.is_td(row) or row.get("msg_id") is None: continue
        sid = row["sig_id"]; evs = store.events(db, sid); lv = {e["level"] for e in evs}
        if "ENTRY" not in lv or lv & TERMINAL: continue
        st = _fetchone(db, "SELECT n, last_ts FROM td_reminder WHERE sig_id = ?", (sid,))
        n_sent = int(st[0]) if st else 0
        kind = None
        if card.is_swing(row):                                # СВІНГ: нотатка наприкінці 1-ї / 3-ї доби після входу (один раз кожна)
            try:
                age_h = (now - float(next(e["touched_ts"] for e in evs if e["level"] == "ENTRY"))) / 3600.0
                for k_, a_, b_ in DAY_WINDOWS:
                    if a_ <= age_h < b_ and not _fetchone(db, "SELECT 1 FROM td_day_note WHERE sig_id = ? AND kind = ?", (sid, k_)): kind = k_
            except Exception:  # noqa: BLE001
                kind = None
        if n_sent >= len(levels()) and kind is None: continue  # усі рівні вже надіслано і нотатка доби не потрібна: ціни не запитуємо
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
        if kind is not None:
            note = day_note(kind, r_now); ok = 0
            if note:
                ok = 1 if await send(day_text(row, r_now, note), reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"]) else 0
                if ok: sent += 1; print(f"[td-remind] {sid} {kind} {r_now:+.2f}R", flush=True)
            if ok or not note: _execute(db, "INSERT INTO td_day_note(sig_id, kind, ts, r, sent) VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING", (sid, kind, now, r_now, ok))
        n_new = due(r_now, n_sent)
        if n_new <= n_sent: continue
        msg = await send(text(row, r_now), reply_to=int(row["msg_id"]), symbol=row["symbol"], direction=row["direction"])
        if not msg: continue
        _execute(db, "INSERT INTO td_reminder(sig_id, n, last_ts) VALUES (?,?,?) ON CONFLICT (sig_id) DO UPDATE SET n = EXCLUDED.n, last_ts = EXCLUDED.last_ts", (sid, n_new, now))
        sent += 1
        print(f"[td-remind] {sid} {r_now:+.2f}R (рівень {n_new})", flush=True)
    return sent

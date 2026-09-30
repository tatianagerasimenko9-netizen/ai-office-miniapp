"""Життєвий цикл сценарію до входу: скасування за ЗАКРИТТЯМ годинної свічки (а не за проколом ціни), мовчазне
скасування того, про що власниці не повідомляли, пауза після скасування, свіжість після перезапуску worker."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

H1_SEC = 3600
ANNOUNCED = ("ACTIVE", "CONFIRMED", "HIT_ENTRY")
COOLDOWN_ENV = "OFFICE_CANCEL_COOLDOWN_SEC"
COOLDOWN_DEFAULT = 2 * 3600


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _ts(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        return None


def closed_h1_beyond(candles_h1: Any, *, side: str, level: Any, since_ts: float, now_ts: float) -> Optional[Dict[str, Any]]:
    """Перша ЗАКРИТА після `since_ts` годинна свічка, що закрилась за рівнем скасування (LONG — нижче, SHORT — вище). Інакше None."""
    lv = _f(level)
    if lv is None or not isinstance(candles_h1, list):
        return None
    long_ = str(side).upper() != "SHORT"
    for c in candles_h1:
        t0 = _ts((c or {}).get("ts"))
        cl = _f((c or {}).get("close"))
        if t0 is None or cl is None:
            continue
        t_close = t0 + H1_SEC
        if t_close > now_ts or t_close <= since_ts:
            continue  # свічка ще не закрита або закрилась до створення сценарію
        if (long_ and cl < lv) or ((not long_) and cl > lv):
            return {"close": cl, "closed_at": t_close}
    return None


def cancel_reason_h1(side: str, level: Any, symbol: str = "") -> str:
    from office_price_format import format_px

    lv = format_px(level, symbol) if symbol else str(level)
    return f"годинна свічка закрилася {'нижче' if str(side).upper() != 'SHORT' else 'вище'} {lv} — сценарій зламано"


def is_announced(status: Any) -> bool:
    return str(status or "").upper() in ANNOUNCED


def db_status(db_path: str, signal_id: str) -> Optional[str]:
    try:
        from office_bridge import _fetchall

        rows = _fetchall(db_path, "SELECT status FROM office_signals WHERE signal_id = ?", (signal_id,))
        return str(rows[0][0]) if rows else None
    except Exception:  # noqa: BLE001
        return None


def cooldown_sec() -> int:
    try:
        return max(0, int(float(os.getenv(COOLDOWN_ENV, str(COOLDOWN_DEFAULT)))))
    except ValueError:
        return COOLDOWN_DEFAULT


def cooldown_active(db_path: str, symbol: str, direction: str, *, now_ts: Optional[float] = None, sec: Optional[int] = None) -> Optional[str]:
    """signal_id скасованого сценарію тієї ж монети й напрямку, якщо він скасований менше `sec` тому (нова картка в ту саму сторону
    відразу після скасування — це шум; відновлюється сама через `sec`). 0 вимикає."""
    win = cooldown_sec() if sec is None else sec
    if win <= 0:
        return None
    now = time.time() if now_ts is None else now_ts
    try:
        from office_bridge import _fetchall

        rows = _fetchall(db_path, "SELECT signal_id, direction, ts_updated FROM office_signals WHERE symbol = ? AND status = 'CANCELLED'",
                         (str(symbol).upper(),))
    except Exception:  # noqa: BLE001
        return None
    for sid, d, upd in rows or []:
        t = _ts(upd)
        if str(sid).startswith("SCN|") and str(d).upper() == str(direction).upper() and t is not None and 0 <= now - t < win:
            return str(sid)
    return None


PLAN_VALID_ENV = "OFFICE_PLAN_VALID_SEC"


def plan_valid_sec(tf: Any = "H1") -> int:
    """Скільки після підтвердження «діє» готовий план, якщо входу не було: D1 — 24 год, H4 — 12 год, H1 — 4 год, M15 і молодші — 1 год.
    Це стосується лише плану без входу: відкриту власницею угоду (кнопка «Я відкрила угоду…») закінчення часу не зачіпає."""
    try:
        v = int(float(os.getenv(PLAN_VALID_ENV, "")))
        if v > 0:
            return v
    except ValueError:
        pass
    t = str(tf or "H1").upper()
    if t in ("D1", "1D"):
        return 24 * 3600
    if t in ("H4", "4H"):
        return 12 * 3600
    if t in ("H1", "1H"):
        return 4 * 3600
    return 3600


def valid_until_ts(confirmed_ts: float, tf: Any = "H1") -> float:
    """TTL 2.0 (office_scenario_ttl): верхня межа життя плану — за сесією/таймфреймом; знімають насамперед причини."""
    from office_scenario_ttl import deadline

    return deadline(float(confirmed_ts), tf)


def kyiv_hhmm(ts: float) -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Kyiv")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M") + " UTC"


def _swing_level(rows: List[Dict[str, Any]], long_: bool, before_ts: float) -> Optional[float]:
    """Останній підтверджений свінг (по 2 свічки з боків) серед закритих свічок ДО before_ts: LONG — мінімум, SHORT — максимум."""
    seq = [(_ts(r.get("ts")), r) for r in rows if _ts(r.get("ts")) is not None and _ts(r.get("ts")) + H1_SEC <= before_ts]
    seq.sort(key=lambda x: x[0])
    rr = [r for _t, r in seq]
    key = "low" if long_ else "high"
    best = None
    for i in range(2, len(rr) - 2):
        v = _f(rr[i].get(key))
        around = [_f(rr[j].get(key)) for j in range(i - 2, i + 3) if j != i]
        if v is None or any(a is None for a in around):
            continue
        if (long_ and all(v < a for a in around)) or ((not long_) and all(v > a for a in around)):
            best = v
    return best


def structure_break_h1(candles_h1: Any, *, side: str, since_ts: float, now_ts: float) -> Optional[Dict[str, Any]]:
    """Злам структури H1 проти сценарію: закрита після створення H1-свічка за останнім свінгом (LONG — під мінімум, SHORT — над максимум)."""
    if not isinstance(candles_h1, list):
        return None
    long_ = str(side).upper() != "SHORT"
    lvl = _swing_level(candles_h1, long_, since_ts)
    if lvl is None:
        return None
    for c in candles_h1:
        t0 = _ts((c or {}).get("ts"))
        cl = _f((c or {}).get("close"))
        if t0 is None or cl is None or t0 + H1_SEC > now_ts or t0 + H1_SEC <= since_ts:
            continue
        if (long_ and cl < lvl) or ((not long_) and cl > lvl):
            return {"level": lvl, "close": cl}
    return None


def target_without_entry(candles_h1: Any, *, side: str, zone_lo: Any, zone_hi: Any, tp1: Any, since_ts: float, now_ts: float) -> bool:
    """Ціль 1 досягнута, а ціна до того ні разу не торкнулась зони входу: рух пішов без нас, план скасовується."""
    lo, hi, t1 = _f(zone_lo), _f(zone_hi), _f(tp1)
    if lo is None or hi is None or t1 is None or not isinstance(candles_h1, list):
        return False
    if lo > hi:
        lo, hi = hi, lo
    long_ = str(side).upper() != "SHORT"
    rows = sorted([(_ts(c.get("ts")), c) for c in candles_h1 if _ts((c or {}).get("ts")) is not None], key=lambda x: x[0])
    for t0, c in rows:
        if t0 + H1_SEC > now_ts or t0 + H1_SEC <= since_ts:
            continue
        h, l = _f(c.get("high")), _f(c.get("low"))
        if h is None or l is None:
            continue
        if l <= hi and h >= lo:
            return False   # зони торкнулись першими — це вже не «без входу»
        if (long_ and h >= t1) or ((not long_) and l <= t1):
            return True
    return False


def confirmed_plan_action(*, ts_updated: Any, tf: Any, sl: Any, direction: str, candles_h1: Any, has_position: bool,
                          now_ts: Optional[float] = None, tp1: Any = None, price: Any = None) -> Optional[Dict[str, str]]:
    """Що зробити з уже підтвердженим планом, за яким власниця НЕ відкривала угоди: знімаємо за часом дії або за закриттям H1 за рівнем.
    Чиста функція: лише рішення для БД. У Telegram таке не йде ніколи (лише ведення позначеної угоди)."""
    if has_position:
        return None   # відкриту вручну угоду веде супровід позиції, а не термін плану
    now = time.time() if now_ts is None else now_ts
    t0 = _ts(ts_updated)
    lv = _f(sl)
    # спершу ПРИЧИНИ: годинник — лише верхня межа
    if lv is not None and closed_h1_beyond(candles_h1, side=direction, level=lv, since_ts=t0 or 0.0, now_ts=now):
        return {"status": "CANCELLED", "outcome": "CANCELLED", "note": f"CANCELLED after confirm: H1 close beyond {lv}", "reason": "SL_CLOSE"}
    if structure_break_h1(candles_h1, side=direction, since_ts=t0 or 0.0, now_ts=now):
        return {"status": "CANCELLED", "outcome": "CANCELLED", "note": "CANCELLED after confirm: H1 structure broken against the plan", "reason": "STRUCTURE"}
    if tp1 is not None and price is not None and lv is not None:
        from office_alert_gate import max_entry_price

        me = max_entry_price(direction, lv, tp1)
        px = _f(price)
        if me is not None and px is not None and ((str(direction).upper() != "SHORT" and px > me) or (str(direction).upper() == "SHORT" and px < me)):
            return {"status": "EXPIRED", "outcome": "EXPIRED", "note": f"EXPIRED after confirm: price beyond max entry {me}", "reason": "BEYOND_MAX_ENTRY"}
    if t0 and now > valid_until_ts(t0, tf):
        return {"status": "EXPIRED", "outcome": "EXPIRED", "note": "EXPIRED after confirm: upper time bound passed without entry", "reason": "TIME"}
    return None

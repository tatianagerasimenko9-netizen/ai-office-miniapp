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
    """Скільки після підтвердження «діє» готовий план, якщо входу не було: H4 і D1 — 12 год, H1 — 4 год, M15 і молодші — 1 год.
    Це стосується лише плану без входу: відкриту власницею угоду (кнопка «Я відкрила угоду…») закінчення часу не зачіпає."""
    try:
        v = int(float(os.getenv(PLAN_VALID_ENV, "")))
        if v > 0:
            return v
    except ValueError:
        pass
    t = str(tf or "H1").upper()
    if t in ("H4", "4H", "D1", "1D"):
        return 12 * 3600
    if t in ("H1", "1H"):
        return 4 * 3600
    return 3600


def valid_until_ts(confirmed_ts: float, tf: Any = "H1") -> float:
    return float(confirmed_ts) + plan_valid_sec(tf)


def kyiv_hhmm(ts: float) -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(ts, tz=ZoneInfo("Europe/Kyiv")).strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%H:%M") + " UTC"

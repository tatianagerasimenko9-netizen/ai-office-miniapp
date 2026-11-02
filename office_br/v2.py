"""B&R v2: інформаційна мітка до картки (НІЧОГО не блокує, не змінює стоп/ціль/ордери).
Умови (ГІПОТЕЗА, виміряні на 842 історичних угодах; доказ прибутку НЕ отримано):
  стоп ≥ 0,8% — комісія з'їдає менше R; перший у русі — на кластері (та сама 15-хв свічка і напрям) лише перший сигнал, решта = та сама ставка; вікно 13–17 UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable

MIN_STOP_PCT = 0.8
SESSION_UTC = (13, 17)


def stop_pct(row: Dict[str, Any]) -> float:
    entry, sl = float(row["entry"]), float(row["sl"])
    return abs(entry - sl) / entry * 100 if entry else 0.0


def in_session(ts: float) -> bool:
    h = datetime.fromtimestamp(float(ts), timezone.utc).hour
    return SESSION_UTC[0] <= h < SESSION_UTC[1]


def earlier_siblings(row: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> list:
    """Сигнали того ж напряму в тій самій 15-хв свічці, створені раніше за цей."""
    bucket = int(float(row["created_ts"]) // 900)
    out = []
    for r in rows:
        if r.get("sig_id") == row.get("sig_id") or r["direction"] != row["direction"]:
            continue
        if int(float(r["created_ts"]) // 900) != bucket:
            continue
        if (float(r["created_ts"]), int(r.get("seq") or 0)) < (float(row["created_ts"]), int(row.get("seq") or 0)):
            out.append(r)
    return out


def line(row: Dict[str, Any], rows: Iterable[Dict[str, Any]]) -> str:
    sp = stop_pct(row)
    ok_stop = sp >= MIN_STOP_PCT
    prev = earlier_siblings(row, rows)
    ok_first = not prev
    ok_hour = in_session(row["created_ts"])
    head = "✅" if (ok_stop and ok_first) else "❌"
    mark = lambda ok: "✔" if ok else "✘"
    first_txt = "перший у русі" if ok_first else "ідея вже в " + prev[0]["symbol"].replace("USDT", "")
    return (f"v2 {head} · стоп ≥0,8% {mark(ok_stop)} ({sp:.2f}%) · {first_txt} {mark(ok_first)} · 13–17 UTC {mark(ok_hour)}"
            " · мітка інформаційна")

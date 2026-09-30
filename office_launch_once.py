"""Одноразова діагностика запуску на production (результат — у БД, подія LAUNCH_DIAG; без змінних середовища).

Виконується ОДИН раз на VERSION: першим записується маркер, далі кожна перевірка пише свою подію. Так результати можна прочитати з БД навіть без доступу до логів,
а повторний старт нічого не повторює. Нова VERSION = новий одноразовий прогін. Лише читання й запис у журнал подій; Telegram і ордерів немає.
Перевірки: (1) чи календар реально завантажується (по кожній адресі); (2) replay угод LONGXIA і ENA з журналу власниці (вхід — у вікні ±2 год від запису);
(3) потік ліквідацій і карта; (4) облік стабільності свічок і стан стакана."""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Optional

VERSION = "final-2026-09-30"


def _log(db: str, task: str, payload: Dict[str, Any]) -> None:
    from office_bridge import log_event

    log_event(db, "LAUNCH_DIAG", {"version": VERSION, "task": task, "at": time.time(), **payload})


def already_done(db: str) -> bool:
    from office_bridge import _fetchall

    try:
        rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT 200", ("LAUNCH_DIAG",))
    except Exception:  # noqa: BLE001
        return False
    for r in rows or []:
        try:
            p = json.loads(r[0]) if isinstance(r[0], str) else dict(r[0])
        except (TypeError, ValueError):
            continue
        if p.get("version") == VERSION and p.get("task") == "marker":
            return True
    return False


def run(db: str, printer: Callable[[str], None] = print, getter: Optional[Callable[[str], bytes]] = None) -> bool:
    """True — виконано зараз; False — уже виконувалось для цієї VERSION."""
    if already_done(db):
        return False
    _log(db, "marker", {})
    P = lambda s: printer(f"[launch-diag] {s}")  # noqa: E731

    try:
        import office_calendar as cal

        d = cal.diagnose()
        _log(db, "calendar", d)
        P("календар: " + json.dumps(d, ensure_ascii=False)[:900])
    except Exception as exc:  # noqa: BLE001
        _log(db, "calendar", {"error": f"{type(exc).__name__}: {exc}"})
        P(f"календар: помилка {type(exc).__name__}: {exc}")

    try:
        import office_liq_map as lm

        st = lm.stream_state()
        b = lm.real_snapshot("BTCUSDT")
        _log(db, "liq_map", {"stream": st, "btc": {"count": b["count"], "long_liq_usd": b["long_liq_usd"], "short_liq_usd": b["short_liq_usd"]}})
        P(f"потік ліквідацій: {json.dumps(st, ensure_ascii=False)} · BTC подій {b['count']}")
    except Exception as exc:  # noqa: BLE001
        _log(db, "liq_map", {"error": f"{type(exc).__name__}: {exc}"})

    try:
        import office_data_stability as ds
        import office_market_data as omd

        _log(db, "stability", {"status": ds.status(db), "depth": omd.depth_stats()})
        P(f"стабільність свічок: {ds.status(db)} · стакан: {omd.depth_stats()}")
    except Exception as exc:  # noqa: BLE001
        _log(db, "stability", {"error": f"{type(exc).__name__}: {exc}"})

    try:
        import office_replay as rp

        res = rp.run_journal(db, getter=getter, printer=lambda s: P(s))
        for r in res:
            _log(db, "replay_journal", {k: r[k] for k in ("case", "trade_id", "symbol", "side", "entry", "sl", "tp1", "recorded_at", "actual", "gate", "lines")}
                 | {"status": (r["result"] or {}).get("status"), "filled_at": (r["result"] or {}).get("filled_at"), "mfe_pct": (r["result"] or {}).get("mfe_pct"),
                    "mae_pct": (r["result"] or {}).get("mae_pct"), "timeline": (r["result"] or {}).get("timeline")})
        _log(db, "replay_journal_summary", {"trades": len(res)})
    except Exception as exc:  # noqa: BLE001
        _log(db, "replay_journal", {"error": f"{type(exc).__name__}: {exc}"})
        P(f"replay журналу: помилка {type(exc).__name__}: {exc}")
    _log(db, "done", {})
    P("готово")
    return True

"""Рішення, що робити з подією рівня (ENTRY/TP/SL/EXPIRED) у Telegram: чиста функція, без I/O (тестується окремо від relay)."""
from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

SEND, DB_ONLY, RETRY = "send", "db_only", "retry"


def decide(scope: str, m: Dict[str, Any], number_of: Callable[[str], Any], legacy_quiet: bool = False) -> Tuple[str, Any, str]:
    """→ (дія, №READY або None, причина).
    send    — нумерований Office2 READY: надсилаємо відповіддю на початкове повідомлення;
    db_only — тиха подія (ENTRY/EXPIRED), старий Лев, без номера (beta/paper до нумерації): лише БД, у Telegram не йде;
    retry   — не вдалося прочитати номер: подію НЕ записуємо, повторимо в наступному циклі (TP/SL не губимо)."""
    if m.get("silent") or legacy_quiet:
        return DB_ONLY, None, "silent"
    try:
        no = number_of(str(m["scenario_id"]))
    except Exception as exc:  # noqa: BLE001
        return RETRY, None, f"number_of: {type(exc).__name__}"
    if scope != "o2":
        return DB_ONLY, no, "legacy-scope"
    if no is None:
        return DB_ONLY, None, "unnumbered"
    return SEND, no, "numbered"


async def dispatch(ms: Any, scope: str, number_of: Callable[[str], Any], send: Callable[[Dict[str, Any], Any], Any], record: Callable[[Dict[str, Any], Any], Any],
                   legacy_quiet: bool = False, log: Callable[[str], None] = print) -> Dict[str, int]:
    """Один прохід по новим подіям рівня. number_of/send/record — async (у relay виконуються у потоці). Повертає лічильники sent/db_only/retry/undelivered.
    Подія записується (record) ЛИШЕ після підтвердженої доставки (message_id) або як db_only; при retry/недоставленні запису немає — буде повтор."""
    out = {"sent": 0, "db_only": 0, "retry": 0, "undelivered": 0}
    for m in ms:
        nres: Any = None
        nerr: Any = None
        if not (m.get("silent") or legacy_quiet):
            try:
                nres = await number_of(str(m["scenario_id"]))
            except Exception as exc:  # noqa: BLE001
                nerr = exc

        def _lookup(_sid: str) -> Any:
            if nerr is not None:
                raise nerr
            return nres

        act, no, why = decide(scope, m, _lookup, legacy_quiet)
        if act == RETRY:
            out["retry"] += 1
            log(f"[milestone][WARN] {m['symbol']} {m['level']}: {why} — повторю в наступному циклі")
            continue
        if act == DB_ONLY:
            await record(m, None)
            out["db_only"] += 1
            log(f"[milestone] {m['symbol']} {m['level']} (лише БД: {why})")
            continue
        mid = await send(m, no)
        if mid:
            await record(m, mid)
            out["sent"] += 1
            log(f"[milestone] sent {m['symbol']} {m['level']} id={mid}")
        else:
            out["undelivered"] += 1
            log(f"[milestone] not delivered {m['symbol']} {m['level']} — повторю")
    return out

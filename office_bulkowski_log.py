"""Булковскі: ядро в лог Worker, не в чат і не як сигнал."""
from __future__ import annotations


def bulk_log_line() -> str:
    try:
        from office_bulkowski_kernel import BULKOWSKI_KERNEL
    except Exception as exc:
        return f"[bulk] DATA_UNAVAILABLE {type(exc).__name__}"
    text = str(BULKOWSKI_KERNEL or "")
    if "ЯДРО БУЛКОВСКІ" not in text:
        return "[bulk] DATA_UNAVAILABLE"
    return "[bulk] kernel loaded (гіпотеза; фінал Герчик; не в чат)"

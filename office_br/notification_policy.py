"""B&R notification decision policy. Pure, deterministic, manual-only."""
from __future__ import annotations

TERMINAL = {"SL", "TP3", "INVALIDATED", "EXPIRED", "TIMEOUT", "AMBIGUOUS"}

def route_event(event: str, *, status: str, original_message_id: int | None,
                edit_supported: bool = False, changed: bool = True) -> str:
    """Return SILENT, EDIT, ALERT, or JOURNAL.

    Never send a second trade signal for confirmations. Alerts are only for
    actionable events and use the original idea ID.
    """
    if not changed or event in {"NEAR_DUPLICATE", "CONFIRMATION_MINOR"}:
        return "SILENT"
    # The terminal transition itself is actionable, but a delayed event
    # observed after a different terminal outcome must not reopen the idea.
    if status in TERMINAL:
        if event == status and event in {"SL", "TP3", "INVALIDATED", "AMBIGUOUS"}:
            return "ALERT"
        return "JOURNAL"
    if event in {"ENTRY_TOUCHED", "SL", "TP1", "TP2", "TP3", "INVALIDATED",
                 "AMBIGUOUS", "CLOSED"}:
        return "ALERT"
    if event == "DATA_GAP":
        return "JOURNAL"
    if event in {"CONFIRMATION_MATERIAL", "LEVELS_CHANGED", "STATUS_CHANGED"}:
        if original_message_id and edit_supported:
            return "EDIT"
        return "JOURNAL"
    return "JOURNAL"

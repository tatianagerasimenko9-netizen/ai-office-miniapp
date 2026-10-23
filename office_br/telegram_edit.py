"""B&R Telegram edit adapter: edits a known message only, never creates a duplicate."""
from __future__ import annotations

from typing import Any

async def edit_original(session: Any, token: str, chat_id: int, message_id: int, text: str) -> str:
    """Returns EDITED, UNCHANGED, RETRY, or UNSUPPORTED.

    An unknown outcome NEVER triggers sendMessage automatically: an edit must
    not become a duplicate trade idea after timeouts or Telegram errors.
    """
    if not token or not chat_id or not message_id or not text:
        return "UNSUPPORTED"
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "text": text[:3900],
        "disable_web_page_preview": True,
    }
    try:
        async with session.post(url, json=payload) as response:
            body = await response.json()
            if response.status == 200 and body.get("ok") is True:
                return "EDITED"
            description = str(body.get("description", "")).lower()
            if "message is not modified" in description:
                return "UNCHANGED"
            if response.status in (400, 403) and (
                "message can't be edited" in description
                or "message to edit not found" in description
                or "message identifier is not specified" in description
            ):
                return "UNSUPPORTED"
            return "RETRY"
    except Exception:
        return "RETRY"

"""B&R Telegram button contract: two actions, no fake trading execution."""
from __future__ import annotations
from urllib.parse import quote

def markup(seq: int, base_url: str) -> dict:
    if int(seq)<=0 or not base_url.startswith("https://"):
        raise ValueError("invalid B&R button input")
    return {"inline_keyboard":[[
        {"text":"Сценарій","url":f"{base_url.rstrip('/')}/br?signal={int(seq)}","style":"danger"},
        {"text":"Я відкрила угоду","callback_data":f"br_open:{int(seq)}","style":"success"},
    ]]}

def authorized_open(db: str, seq: int, *, owner_id: int|None, actor_id: int,
                    chat_id: int, expected_chat_id: int, message_id: int) -> str:
    """Only the configured owner may report an actual manual fill."""
    from office_bridge import _fetchone
    from office_br import store
    if owner_id is None or actor_id != owner_id or chat_id != expected_chat_id:
        return "DENIED"
    r=_fetchone(db, "SELECT sig_id,msg_id FROM br_test_signal WHERE seq = ?", (seq,))
    if not r or not r[1] or int(r[1]) != int(message_id):
        return "WRONG_CARD"
    if "OPENED" in store.manual_actions(db,r[0]):
        return "ALREADY_RECORDED"
    if not store.record_manual_action(db,r[0],"OPENED"):
        return "ERROR"
    return "RECORDED"

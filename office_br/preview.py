"""One-time historical B&R Telegram image preview, never a trading alert."""
from __future__ import annotations
import asyncio
import os
import time

async def send_preview_once(db, fetch, send):
    from office_bridge import _execute, _fetchone
    from office_br import store,card
    from office_br.live import _epoch
    from office_br.live_image import render
    _execute(db,"CREATE TABLE IF NOT EXISTS br_preview_once (preview_id TEXT PRIMARY KEY, msg_id BIGINT, sent_ts DOUBLE PRECISION)")
    tag="approved-card-v1"
    if _fetchone(db,"SELECT 1 FROM br_preview_once WHERE preview_id = ?", (tag,)):
        return False
    recent=store.rows(db, "WHERE msg_id IS NOT NULL")
    if not recent:
        print("[br-preview] no existing delivered B&R",flush=True)
        return False
    row=max(recent,key=lambda r:int(r["seq"]))
    candles=await asyncio.to_thread(fetch,row["symbol"],"15m",240,closed_only=True)
    if not isinstance(candles,list):
        print("[br-preview] missing futures M15 candles",flush=True)
        return False
    historic=[b for b in candles if _epoch(b)+900<=float(row["confirm_ts"])+1]
    if len(historic)<100:
        print("[br-preview] insufficient aligned historic M15",flush=True)
        return False
    path=await asyncio.to_thread(render,row,historic)
    try:
        caption="🧪 ТЕСТ ДИЗАЙНУ — історичний сигнал, НЕ НОВИЙ ВХІД\n"+card.build_card(row)
        msg_id=await send(path,caption,row)
    finally:
        try:os.unlink(path)
        except OSError:pass
    if msg_id:
        _execute(db,"INSERT INTO br_preview_once(preview_id,msg_id,sent_ts) VALUES (?,?,?) ON CONFLICT DO NOTHING",(tag,int(msg_id),time.time()))
        print(f"[br-preview] SENT historic seq={row['seq']} msg={msg_id}",flush=True)
        return True
    print("[br-preview] Telegram photo delivery not confirmed",flush=True)
    return False

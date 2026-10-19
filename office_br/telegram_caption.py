"""B&R-only concise Ukrainian caption for Telegram sendPhoto.

The chart is a separate photo attachment; this is its Telegram caption.
Never upgrades a conditional setup into a confirmed signal.
"""
from __future__ import annotations
from typing import Any,Mapping

def caption(p:Mapping[str,Any])->str:
    direction=str(p["direction"]).upper()
    if direction not in ("LONG","SHORT"):raise ValueError("direction")
    if p.get("verified") is not True or p.get("risk_ok") is not True:
        raise ValueError("only independently verified, risk-approved READY signals")
    if not p.get("chart_ready"):raise ValueError("chart image required")
    for field in ("symbol","entry","sl","tp1","tp2","tp3","rr_tp1",
                  "expires","invalidation","confirmation"):
        if p.get(field) is None:raise ValueError("missing "+field)
    sym=str(p["symbol"]).upper()
    return "\n".join([
        f"📊 AI Office · B&R LIVE · №{p.get('number','—')}",
        f"{'🟢' if direction=='LONG' else '🔴'} {sym} · {direction} · ГОТОВО",
        "",
        f"✅ Підтвердження: {p['confirmation']}",
        f"🟡 Вхід: {p['entry']}",
        f"🔴 SL: {p['sl']}",
        f"🟢 TP1: {p['tp1']}",
        f"🟢 TP2: {p['tp2']}",
        f"🟢 TP3: {p['tp3']}",
        f"📊 R:R до TP1: {p['rr_tp1']}",
        f"⏳ Діє до: {p['expires']}",
        f"❌ Скасування: {p['invalidation']}",
        "",
        "Рішення: МОЖНА РОЗГЛЯНУТИ ВХІД.",
        "Угоду відкриваєте лише ви. Office не торгує автоматично.",
    ])

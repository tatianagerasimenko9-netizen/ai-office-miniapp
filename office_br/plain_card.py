"""B&R-only plain Ukrainian conditional plan presentation.

Pure formatting: never creates trade levels, upgrades unverified triggers,
or changes Office2/production trading decisions.
"""
from __future__ import annotations
from typing import Any,Mapping

def format_plan(plan:Mapping[str,Any])->str:
    symbol=str(plan["symbol"]).upper()
    direction=str(plan["direction"]).upper()
    if direction not in ("LONG","SHORT"):raise ValueError("direction")
    state=str(plan.get("decision","WAIT")).upper()
    allowed={"WAIT":"ЧЕКАТИ","PREPARE":"ГОТУВАТИСЯ",
             "CONSIDER":"МОЖНА РОЗГЛЯНУТИ ВХІД","SKIP":"НЕ ВХОДИТИ"}
    if state not in allowed:raise ValueError("decision")
    zone=plan.get("zone")
    trigger=plan.get("trigger")
    trigger_verified=plan.get("trigger_verified") is True
    lines=[f"{symbol} {direction}"]
    if zone:
        lines.append(f"• Зона очікування: {zone}.")
    else:
        lines.append("• Зона очікування ще не підтверджена.")
    if trigger is not None:
        tag="перевірений рівень" if trigger_verified else "ПОПЕРЕДНІЙ орієнтир, не перевірений M5"
        verb="вище" if direction=="LONG" else "нижче"
        lines.append(f"• Підтвердження: закриття M5 {verb} {trigger} ({tag}).")
    else:
        lines.append("• Точний тригер M5 визначити після нових закритих свічок.")
    if plan.get("retest"):
        lines.append(f"• Ретест: {plan['retest']}.")
    for key,label in (("sl","SL"),("tp1","TP1"),("tp2","TP2"),("tp3","TP3")):
        if plan.get(key) is not None:lines.append(f"• {label}: {plan[key]}.")
    if plan.get("risk_reward") is not None:
        lines.append(f"• Потенційний R:R: {plan['risk_reward']}.")
    if plan.get("invalidation"):
        lines.append(f"• Скасування: {plan['invalidation']}.")
    if state=="CONSIDER" and not trigger_verified:
        state="WAIT"
        lines.append("• Вхід заборонено: M5-тригер не підтверджений.")
    if state=="CONSIDER" and plan.get("risk_ok") is not True:
        state="SKIP"
        lines.append("• Вхід заборонено: ризик/винагорода не підтверджені.")
    lines.append(f"Рішення зараз: {allowed[state]}.")
    if state=="SKIP":lines.append("Мій вибір зараз — не відкривати угоду.")
    return "\n".join(lines)

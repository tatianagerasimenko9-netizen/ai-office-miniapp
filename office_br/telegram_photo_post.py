"""B&R-only Telegram photo+caption+Mini App button payload contract.

Pure builder: no Telegram network calls, no automatic trading, no Office2 changes.
The existing Mini App URL must be supplied by the caller; never invented.
"""
from __future__ import annotations
from typing import Any,Mapping
from urllib.parse import urlsplit
from ipaddress import ip_address
from office_br.telegram_caption import caption
from office_br.telegram_geometry import validate

def build_photo_post(plan:Mapping[str,Any],*,chart_bytes:bytes,
                     scenario_url:str,round_trip_cost_pct:float,
                     min_net_rr_tp1:float=1.0)->dict[str,Any]:
    if not isinstance(chart_bytes,bytes) or not chart_bytes:
        raise ValueError("missing chart image")
    parsed=urlsplit(scenario_url)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid Mini App HTTPS URL")
    host=parsed.hostname
    if host in ("localhost",) or host.endswith((".local",".internal",".localhost")):
        raise ValueError("Mini App must use a public HTTPS host")
    try:
        if not ip_address(host).is_global:
            raise ValueError("Mini App must use a public HTTPS host")
    except ValueError as exc:
        if "public HTTPS host" in str(exc):
            raise
    if not (0<min_net_rr_tp1<100):
        raise ValueError("invalid minimum R:R")
    if plan.get("verified") is not True or plan.get("risk_ok") is not True:
        raise ValueError("signal not verified")
    computed=validate(plan,round_trip_cost_pct=round_trip_cost_pct)
    if computed["tp1_net_r"]<min_net_rr_tp1:
        raise ValueError("net TP1 R:R below minimum")
    # The numeric cost-adjusted ratio overrides any untrusted caller-supplied text.
    safe=dict(plan,chart_ready=True,
              rr_tp1=f"1:{computed['tp1_net_r']:.2f}".replace(".",","))
    return {"photo":chart_bytes,"caption":caption(safe),
            "reply_markup":{"inline_keyboard":[[
                {"text":"📊 Сценарій","url":scenario_url}
            ]]},
            "parse_mode":None,
            "metrics":{"net_rr_tp1":computed["tp1_net_r"],
                       "round_trip_cost_pct":round_trip_cost_pct},
            "mode":"B&R_SHADOW_ONLY"}

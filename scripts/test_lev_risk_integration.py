#!/usr/bin/env python3
"""Independent risk veto in Lev's existing decision path, no network/orders."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_lev_verdict import finalize_lev

draft = {
    "symbol": "BTCUSDT", "direction": "LONG", "send_card": True,
    "entry": 100.0, "sl": 98.0, "tp1": 104.0, "rr": 2.0,
    "invalidation": 98.0, "confluence": {"tags": ["H1"], "n": 3},
    "atr": {}, "liquidity": {}, "reason": "confirmed HTF structure",
}
base = finalize_lev(draft)
assert base["action"] == "SEND" and base["risk_review"] is None
bad = finalize_lev(draft, risk_context={
    "quantity": 10, "equity_usdt": 1000, "max_risk_pct": 1,
    "data_quality": "UNAVAILABLE", "context_quality": "OK", "execution_quality": "OK",
})
assert bad["action"] == "WAIT" and not bad["send"]
assert "TRADE_RISK_LIMIT" in bad["risk_review"]["reasons"]
assert "DATA_NOT_VERIFIED" in bad["risk_review"]["reasons"]
assert bad["risk_review"]["order_authorized"] is False
good = finalize_lev(draft, risk_context={
    "quantity": 1, "equity_usdt": 1000, "max_risk_pct": 1,
    "data_quality": "OK", "context_quality": "OK", "execution_quality": "OK",
})
assert good["action"] == "SEND" and good["risk_review"]["approved_for_review"]
assert good["risk_review"]["order_authorized"] is False
print("OK Lev independent risk veto: legacy behavior, blocked risk, reviewed plan, no orders")

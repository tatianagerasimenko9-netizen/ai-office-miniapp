#!/usr/bin/env python3
"""UI-only tick formatting: no float tails, exact non-decimal tick multiples."""
from decimal import Decimal
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office_price_format import format_px, format_level_span, quantize_display, format_price_fields

assert format_px(0.07250414754616397, "MANTAUSDT", tick="0.00001") == "0.0725"
assert format_px("84408.10000000001", "BTCUSDT", tick="0.1") == "84 408.1"
assert format_px("100.07", tick="0.05") == "100.05"
assert format_px("100.08", tick="0.05") == "100.1"
assert quantize_display("100.07", tick="0.05") == Decimal("100.05")
assert format_px("100.07", tick="0.05", side="LONG", kind="SL") == "100.05"
assert format_px("100.07", tick="0.05", side="SHORT", kind="SL") == "100.1"
assert format_level_span("2668", "2662", "ETHUSDT", tick="0.01") == "2 662–2 668"
source = {"symbol": "MANTAUSDT", "sl": 0.07250414754616397, "risk": 10.0}
out = format_price_fields(source)
assert out["sl"] == "0.0725" and source["sl"] == 0.07250414754616397
assert out["risk"] == source["risk"]
assert format_px(None) == ""
# float noise must not move a stop a whole tick in the conservative direction
assert format_px(2686.0000000002, "ETHUSDT", tick="0.01", side="SHORT", kind="SL") == "2 686"
assert format_px(0.0700999999999, "MANTAUSDT", tick="0.0001", side="LONG", kind="SL") == "0.0701"
print("OK UI tick formatting: no float tails, true tick multiples, source unchanged")

#!/usr/bin/env python3
"""P0 regression: Binance shared-IP headroom before HTTP 429/418."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_market_data as md

def main():
    assert md._FAPI_GAP >= .06
    assert md._WEIGHT_SOFT < md._WEIGHT_HARD < 2400
    old_soft, old_hard = md._SOFT_UNTIL, md._BACKOFF_UNTIL
    old_weight = dict(md._WEIGHT_LAST)
    try:
        md._SOFT_UNTIL = 0
        md._BACKOFF_UNTIL = 0
        md._note_weight({"X-MBX-USED-WEIGHT-1M": str(md._WEIGHT_SOFT + 1)})
        assert md._SOFT_UNTIL > time.time()
        md._note_weight({"X-MBX-USED-WEIGHT-1M": str(md._WEIGHT_HARD + 1)})
        assert md._BACKOFF_UNTIL > time.time()
    finally:
        md._SOFT_UNTIL = old_soft
        md._BACKOFF_UNTIL = old_hard
        md._WEIGHT_LAST.update(old_weight)
    print("PASS: soft and hard weight backoff preempt shared IP ban")

if __name__ == "__main__":
    main()

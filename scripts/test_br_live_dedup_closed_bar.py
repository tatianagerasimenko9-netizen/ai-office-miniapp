"""B&R LIVE: only one same-direction signal per closed confirmation bar."""
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_br.live import scan_symbol
def test_one_signal_per_direction_per_bar():
    rows=[{"ts":"2026-10-19T00:%02d:00Z"%(15*(i%4)),"open":100,"high":101,"low":99,"close":100} for i in range(120)]
    # The final candle must be recent and each row only needs valid OHLC.
    now=1792376100.0
    from datetime import datetime,timezone
    from datetime import timedelta
    start=datetime.fromtimestamp(now-900,timezone.utc)
    rows[-1]["ts"]=start.isoformat()
    hits=[{"confirm_i":119,"direction":"LONG","level":100},
          {"confirm_i":119,"direction":"LONG","level":101},
          {"confirm_i":119,"direction":"SHORT","level":102}]
    seen=[]
    with patch("office_br.live.detect.scan",return_value=hits),patch(
        "office_br.live.store.record_signal",
        side_effect=lambda db,sym,s,hyp,now: seen.append(s) or "id"):
        n=scan_symbol("db","ETHUSDT",lambda *a,**kw:rows,now=now)
    assert n==2 and [s["direction"] for s in seen]==["LONG","SHORT"]
if __name__=="__main__":
    test_one_signal_per_direction_per_bar()
    print("OK")

#!/usr/bin/env python3
"""Lev thesis from the live cycle: contract check, append-only versions, restart dedup.

Temporary SQLite; no network, Telegram or orders.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

import office_thesis_journal as tj  # noqa: E402
from office_bridge import _fetchall, init_office_db, signal_upsert  # noqa: E402
from office_mini_v2 import scenario_detail  # noqa: E402

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
KEY = "SOLUSDT|LONG|140|142"


def cycle(action="WATCHING", regime=None, alt_eligible=False, lo=140.0):
    ctx = {"data_status": "DATA_OK", **({"regime": regime} if regime else {})}
    return {
        "action": action, "reason": "fixture",
        "draft": {
            "symbol": "SOLUSDT", "direction": "LONG", "timeframe": "H1",
            "zone_lo": lo, "zone_hi": 142.0, "invalidation": 136.0,
            "confluence": {"setup_key": KEY, "tags": ["OB H1", "FVG"]},
            "alternative": {"direction": "SHORT", "eligible": alt_eligible, "reason": "BSL над 150",
                            "zone_lo": 149, "zone_hi": 151},
            "confirmation": ["sfp"], "market_context": ctx,
        },
    }


def main():
    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["OFFICE_DB_PATH"] = db
    try:
        init_office_db(db)
        fresh = {"H1": [{"ts": (NOW - timedelta(minutes=10)).isoformat()}],
                 "M5": [{"ts": (NOW - timedelta(minutes=2)).isoformat()}]}

        # No zone -> no thesis, nothing invented.
        c0 = cycle(); c0["draft"]["zone_lo"] = None
        assert tj.record_thesis(db, c0, candles_by_tf=fresh, now_utc=NOW) is None

        # Unknown regime -> recorded but honestly flagged.
        r1 = tj.record_thesis(db, cycle(), candles_by_tf=fresh, now_utc=NOW)
        assert r1 and r1["regime"] == "UNKNOWN" and r1["opens_position"] is False
        assert "REGIME_NOT_VERIFIED" in r1["check"]["reasons"] and r1["check"]["order_authorized"] is False
        assert "OB H1" in r1["hypothesis"] and r1["invalidation"] == "закриття за 136"
        assert r1["alternative"].startswith("SHORT: підстав немає")

        # Same content later -> no new version; after a restart (memory wiped) either.
        assert tj.record_thesis(db, cycle(), candles_by_tf=fresh, now_utc=NOW + timedelta(minutes=5)) is None
        tj._LAST.clear()
        assert tj.record_thesis(db, cycle(), candles_by_tf=fresh, now_utc=NOW + timedelta(minutes=6)) is None

        # Changed thesis -> new version; old one untouched.
        r2 = tj.record_thesis(db, cycle(action="SEND", regime="range", alt_eligible=True),
                              candles_by_tf=fresh, now_utc=NOW + timedelta(minutes=7))
        assert r2 and r2["state"] == "CONFIRMED" and r2["regime"] == "RANGE"
        assert r2["check"]["valid_for_analyst_review"] is True, r2["check"]
        assert r2["alternative"].startswith("SHORT: BSL над 150")
        rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type='THESIS_VERSION' ORDER BY id", ())
        assert len(rows) == 2 and '"regime": "UNKNOWN"' in rows[0][0]

        # Stale evidence is flagged.
        stale = {"H1": [{"ts": (NOW - timedelta(hours=5)).isoformat()}]}
        r3 = tj.record_thesis(db, cycle(lo=139.0), candles_by_tf=stale, now_utc=NOW)
        assert "EVIDENCE_STALE_OR_FUTURE" in r3["check"]["reasons"]

        # Mini App card shows the latest version for the same scenario id.
        signal_upsert(db, signal_id=KEY, symbol="SOLUSDT", direction="LONG", entry_low=140, entry_high=142,
                      sl=136, tp1=150, tp2=None, rr=None, status="ACTIVE", analysis_note="")
        det = scenario_detail(KEY)
        assert det["ok"] and det["thesis"]["version_hash"] == r3["version_hash"]

        # Regime from real-looking H1 history when the context has none.
        h1 = [{"open": 100 + i * 0.8, "high": 100.5 + i * 0.8, "low": 99.5 + i * 0.8, "close": 100 + i * 0.8,
               "ts": (NOW - timedelta(hours=60 - i)).isoformat()} for i in range(60)]
        rr = tj.build_thesis(cycle(lo=141.0), candles_by_tf={"H1": h1}, now_utc=NOW)
        assert rr["regime"] == "TREND" and rr["regime_info"]["source"] == "regime-v1", rr["regime_info"]
        ctx_r = tj.build_thesis(cycle(regime="range"), candles_by_tf={"H1": h1}, now_utc=NOW)
        assert ctx_r["regime"] == "RANGE" and ctx_r["regime_info"]["source"] == "market_context"

        # Zone drifted slightly: thesis attaches to the existing canonical scenario id.
        signal_upsert(db, signal_id="CANON-1", symbol="ADAUSDT", direction="SHORT", entry_low=0.50,
                      entry_high=0.52, sl=0.54, tp1=0.46, tp2=None, rr=None, status="WATCHING",
                      analysis_note="origin=desk tf=H1 basis=B-ada scenario_id=CANON-1")
        drift = cycle()
        drift["draft"].update({"symbol": "ADAUSDT", "direction": "SHORT", "zone_lo": 0.5001, "zone_hi": 0.52,
                               "invalidation": 0.54})
        drift["draft"]["confluence"] = {"setup_key": "ADAUSDT|SHORT|0.5001|0.52", "market_basis": "B-ada", "tags": ["OB H1"]}
        rd = tj.record_thesis(db, drift, candles_by_tf=fresh, now_utc=NOW)
        assert rd["thesis_id"] == "CANON-1", rd["thesis_id"]
        assert scenario_detail("CANON-1")["thesis"]["version_hash"] == rd["version_hash"]
    finally:
        os.unlink(db)
    print("OK Lev thesis journal: contract check, append-only versions, restart dedup, Mini App card")


if __name__ == "__main__":
    main()

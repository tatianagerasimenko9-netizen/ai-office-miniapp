#!/usr/bin/env python3
"""Mini App 2.0 cards: tick display, status text+icon, Lev's wait/cancel lines, honest Risk tab.

Temporary SQLite only. No network, no Telegram, no orders.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

from office_bridge import init_office_db, log_event, signal_upsert  # noqa: E402
from office_mini_v2 import note_lines, risk_payload, scenario_detail, status_view  # noqa: E402
from office_price_format import has_float_tail  # noqa: E402

NOTE = """🔴 SHORT · ETHUSDT · сценарій H1
WATCHING · ВХОДУ НЕМАЄ
Чекаю повернення в зону і закриття H1 нижче 2662.
Чому сценарій: D1 висхідна, але H4/H1 під тиском продавців.
Що скасує: закриття H1 вище 2686"""


def main() -> int:
    assert note_lines(NOTE) == {
        "wait": "Чекаю повернення в зону і закриття H1 нижче 2662.",
        "cancel": "закриття H1 вище 2686",
        "why": "D1 висхідна, але H4/H1 під тиском продавців.",
    }, note_lines(NOTE)
    assert note_lines("grade=A ckey=x") == {"wait": None, "cancel": None, "why": None}
    for code in ("WATCHING", "ACTIVE", "HIT_SL", "CANCELLED", "???"):
        v = status_view(code)
        assert v["icon"] and v["short"] and v["text"], v
    assert status_view("WATCHING")["group"] == "watch"
    assert "не збиток угоди" in status_view("HIT_SL")["text"]

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["OFFICE_DB_PATH"] = db
    try:
        init_office_db(db)
        signal_upsert(
            db, signal_id="lev-ETH-S1", symbol="ETHUSDT", direction="SHORT",
            entry_low=2662.004999999, entry_high=2668.0000000001, sl=2686.0000000002,
            tp1=2628.0, tp2=2616.0, rr=None, status="WATCHING", analysis_note=NOTE,
        )
        signal_upsert(
            db, signal_id="lev-MANTA-L1", symbol="MANTAUSDT", direction="LONG",
            entry_low=0.07250414754616397, entry_high=0.0731, sl=0.0701, tp1=0.0790,
            tp2=None, rr=None, status="ACTIVE", analysis_note="grade=A",
        )
        log_event(db, "WATCHING_CREATED", {"symbol": "ETHUSDT"}, "lev-ETH-S1")

        eth = scenario_detail("lev-ETH-S1")
        assert eth["ok"] and eth["hypothetical"] is True
        c = eth["scenario"]
        d = c["display"]
        assert d["zone"] == "2 662–2 668", d
        assert d["sl"] == "2 686" and d["tp1"] == "2 628" and d["tp2"] == "2 616", d
        assert d["rr"] and d["rr"].startswith("1:") and d["rr_basis"], d
        assert c["wait"].startswith("Чекаю") and c["cancel"] == "закриття H1 вище 2686"
        assert c["status"]["short"] == "WATCHING" and c["opens_position"] is False
        assert [e["type"] for e in eth["events"]] == ["WATCHING_CREATED"]

        manta = scenario_detail("lev-MANTA-L1")["scenario"]
        for k, v in manta["display"].items():
            assert not has_float_tail(str(v or "")), (k, v)
        assert manta["wait"] is None and manta["cancel"] is None, "no invented conditions"

        r = risk_payload()
        assert r["order_authorized"] is False and r["orders"] is False
        assert r["equity"]["value"] is None and "недоступні" in r["equity"]["text"]
        assert r["exposure"]["value"] is None and "не підтверджені" in r["exposure"]["text"]
        assert r["budget"]["value"] is None
        ids = [p["scenario_id"] for p in r["plans"]]
        assert ids == ["lev-MANTA-L1"], ids  # WATCHING is not a plan for risk review
        assert all(p["risk_usdt"] is None for p in r["plans"])
        assert r["vetoes"] == [] and r["vetoes_note"]
        log_event(db, "RISK_SHADOW_REVIEW", {"symbol": "MANTAUSDT", "would_veto": True,
                                             "reasons": ["EXECUTION_NOT_VERIFIED"]}, "lev-MANTA-L1")
        r2 = risk_payload()
        assert r2["vetoes"] == [] and r2["shadow"][0]["would_veto"] is True, "shadow review is not a veto"
        assert r2["risk_mode"] == "shadow"
        log_event(db, "RISK_VETO", {"reason": "fixture"}, "lev-MANTA-L1")
        assert risk_payload()["vetoes"][0]["type"] == "RISK_VETO"
    finally:
        os.unlink(db)
    print("OK Mini App cards: tick display, status text, Lev lines, honest risk (no orders)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

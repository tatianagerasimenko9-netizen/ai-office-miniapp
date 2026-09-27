#!/usr/bin/env python3
"""Mini App 2.0: сценарій, empty states, без ордерів, канал не сигнал."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_bridge import init_office_db, journal_open_trade, log_event, signal_upsert  # noqa: E402
from office_confluence import now_status_line, scenario_story  # noqa: E402
from office_mini_v2 import (  # noqa: E402
    candles_payload,
    html_v2,
    positions_v2,
    scenario_detail,
    settings_payload,
)
from office_regression_channel import get_channel, regression_channel  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85 or float(MIN_RR) != 1.5:
        return _fail("gates frozen")
    html = html_v2().lower()
    for ban in ("ggshot", "купити premium", "enter long", "enter short", "auto trading", "підключити біржу"):
        if ban in html:
            return _fail(f"brand/order leaked {ban}")
    if "голівна" in html or True:
        if "сигнали" not in html or "сканер" not in html:
            return _fail("nav")
    if "position:fixed" not in html_v2() and "nav{" not in html_v2().replace(" ", ""):
        pass
    if "lightweight-charts" not in html:
        return _fail("need lightweight charts")
    print("OK html v2")

    miss = scenario_story(timeframe="H1", zone_lo=None, zone_hi=None)
    if miss.get("ok") or "чекаємо відкат" in str(miss.get("text") or "").lower():
        return _fail(f"no-bounds story {miss}")
    ok = scenario_story(timeframe="H1", zone_lo=100, zone_hi=102, labels=["OB H1", "Фібо"], confirms=["sfp"], direction="LONG")
    if not ok.get("ok") or "100" not in ok["text"] or "OB" not in ok["text"]:
        return _fail(ok)
    if "сильна свічка" in now_status_line(price=1, zone_lo=None, zone_hi=None, direction="LONG"):
        return _fail("status without bounds")
    if "Немає підтверджених меж" not in now_status_line(price=1, zone_lo=None, zone_hi=None, direction="LONG"):
        return _fail(now_status_line(price=1, zone_lo=None, zone_hi=None, direction="LONG"))
    print("OK story")

    src = [float(i) for i in range(120)]
    ch = get_channel(src, 100)
    if not ch:
        return _fail("channel")
    _y1, _y2, _dev, slope = ch
    if abs(slope - 1.0) > 0.05:
        return _fail(f"slope {slope}")
    pack = regression_channel([{"close": x, "ts": str(i)} for i, x in enumerate(src)], length=100)
    if pack.get("signal") or pack.get("confluence_tag"):
        return _fail("channel must not signal")
    if pack.get("license") != "MPL-2.0":
        return _fail("license")
    print("OK channel")

    os.environ["OFFICE_MINI_FIXTURE"] = "1"
    c = candles_payload("SOLUSDT", "M15", 80)
    if c.get("live") is True:
        return _fail("fixture is not live stream")
    if c.get("source") != "fixture" or not c.get("candles"):
        return _fail(c)
    if not any(x.get("forming") for x in c["candles"]):
        return _fail("forming last bar")
    print("OK fixture candles")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    old = os.environ.get("OFFICE_DB_PATH")
    os.environ["OFFICE_DB_PATH"] = db
    try:
        init_office_db(db)
        empty = positions_v2()
        if empty.get("data_status") != "EMPTY":
            return _fail(f"empty pos {empty}")
        if "підтверджених позицій" not in str(empty.get("empty_reason") or "").lower():
            return _fail(empty)
        signal_upsert(
            db,
            signal_id="desk-conf-SOLUSDT-demo",
            symbol="SOLUSDT",
            direction="LONG",
            entry_low=140,
            entry_high=142,
            sl=136,
            tp1=150,
            tp2=None,
            rr=2.0,
            status="ACTIVE",
            analysis_note="grade=A ckey=SOLUSDT|LONG|140|142",
        )
        log_event(db, "ZONE_REACHED", {"symbol": "SOLUSDT"}, "desk-conf-SOLUSDT-demo")
        det = scenario_detail("desk-conf-SOLUSDT-demo")
        if not det.get("ok") or not det.get("hypothetical"):
            return _fail(det)
        if det["scenario"]["lifecycle"]["key"] == "entered":
            return _fail("entered without /position")
        if not det.get("events"):
            return _fail("events")
        journal_open_trade(
            db,
            trade_id="pos-ETHUSDT-x",
            symbol="ETHUSDT",
            direction="LONG",
            entry_price=3000,
            stop_loss=2900,
            setup_name="T1_MY_POSITION",
            entry_reason="explicit /position by owner",
        )
        p = positions_v2()
        if len(p.get("positions") or []) != 1:
            return _fail(p)
        st = settings_payload()
        if st.get("auto_trading") or st.get("orders") or st.get("risk_presets", {}).get("available"):
            return _fail(st)
        print("OK scenario/events/position")
        return 0
    finally:
        if old is None:
            os.environ.pop("OFFICE_DB_PATH", None)
        else:
            os.environ["OFFICE_DB_PATH"] = old
        os.environ.pop("OFFICE_MINI_FIXTURE", None)
        try:
            os.unlink(db)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())

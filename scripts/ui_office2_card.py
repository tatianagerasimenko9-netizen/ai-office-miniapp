#!/usr/bin/env python3
"""UI-перевірка Mini App /office2 у справжньому браузері (390 px): READY brain v2 показує цілісну тезу, карту ринку зверху вниз, послідовність; без помилок JS і горизонтального скролу."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_office2_brain2 as T  # noqa: E402
import office_bridge as OB  # noqa: E402
from office2 import brain as B  # noqa: E402
from office2 import engine as EN  # noqa: E402
from office2 import webview as WV  # noqa: E402


def build_db(td):
    c, seq = T.closes_long()
    db = os.path.join(td, "o2.db")
    OB.init_office_db(db)
    EN.init_db(db)
    orig = B.all_levels
    B.all_levels = lambda ctx, now: T.LEVELS
    try:
        for upto in (seq["sweep"], seq["top"], seq["bear_in_zone"], seq["trigger"]):
            b, ctx = T.mk(c, upto)
            st = {"price": float(b["c"][-1]), "ret_1h": 0.3, "ret_4h": 1.0, "ret_24h": 2.0, "atr15_pct": 0.3, "vol_regime_7d": 0.5, "pos_24h_range": 0.6}
            EN.step_symbol(db, "XUSDT", ctx, st, {"btc_ret_1h": 0.1, "eth_ret_1h": 0.1, "breadth_up_1h": 0.5, "n_alts": 20}, {"coin_ret_1h": 0.3, "rs_vs_btc_1h": 0.2, "rs_vs_btc_4h": 0.1}, float(b["t"][-1] + 900), None)
    finally:
        B.all_levels = orig
    return db


def main():
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as td:
        db = build_db(td)
        pl = WV.payload(db)
        sid = pl["signals"][0]["id"]
        errors = []
        with sync_playwright() as p:
            kw = {}
            if os.environ.get("PW_CHROMIUM"):
                kw["executable_path"] = os.environ["PW_CHROMIUM"]
            br = p.chromium.launch(**kw)
            page = br.new_page(viewport={"width": 390, "height": 844})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

            def route(r):
                u = r.request.url
                if "/api/v2/office2" in u:
                    r.fulfill(status=200, content_type="application/json", body=json.dumps(WV.payload(db, focus=sid)))
                elif u.endswith("/office2") or "/office2?" in u:
                    r.fulfill(status=200, content_type="text/html; charset=utf-8", body=WV.html())
                else:
                    r.fulfill(status=204, body="")
            page.route("**/*", route)
            page.goto("http://o2.test/office2?id=" + sid)
            page.wait_for_selector("text=Послідовність до READY", timeout=8000)
            txt = page.inner_text("body")
            for must in ("Цілісна теза", "Карта ринку зверху вниз", "Послідовність до READY", "Що перевірено"):
                assert must.lower() in txt.lower(), (must, txt[:300])
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), "горизонтальний скрол"
            br.close()
        assert not errors, errors
    print("OK ui office2 card")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

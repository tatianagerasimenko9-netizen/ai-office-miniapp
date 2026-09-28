#!/usr/bin/env python3
"""Browser smoke for Mini App 2.0 (manual/CI-optional: needs Playwright + Chromium).

Starts office_mini_app on a temporary SQLite with hostile/edge data and
fixture candles, then checks in Chromium at phone and desktop widths:
five tabs render without JS errors, no horizontal scroll, XSS payloads in
DB fields are not executed, API failure shows an error state, slow API
shows a loading state. No network, Telegram or orders.

Usage: python3 scripts/ui_smoke_mini_v2.py [--chromium /path/to/chrome] [--shots DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

XSS = '<img src=x onerror="window.__xss=1">'


def _seed(db: str) -> None:
    from office_bridge import init_office_db, log_event, signal_upsert

    init_office_db(db)
    signal_upsert(db, signal_id="xss-1", symbol="XSSUSDT" + XSS, direction="LONG", entry_low=1.0, entry_high=1.1,
                  sl=0.9, tp1=1.4, tp2=None, rr=None, status="ACTIVE",
                  analysis_note=f"Чекаю {XSS}\nЩо скасує: {XSS}\nЧому сценарій: {XSS}")
    signal_upsert(db, signal_id="big-1", symbol="VERYLONGNAMEDCOINTOKENUSDT", direction="SHORT",
                  entry_low=123456789.12, entry_high=123456799.5, sl=123460000.0, tp1=123000000.0, tp2=None,
                  rr=None, status="WATCHING", analysis_note="")
    signal_upsert(db, signal_id="tiny-1", symbol="PEPEUSDT", direction="LONG", entry_low=0.0000123,
                  entry_high=0.0000125, sl=0.0000118, tp1=0.0000140, tp2=None, rr=None, status="PIERCE_WATCHING",
                  analysis_note="")
    log_event(db, "RISK_SHADOW_REVIEW" + XSS, {"symbol": XSS, "reasons": [XSS], "would_veto": True}, "xss-1")
    log_event(db, "RISK_SHADOW_REVIEW", {"symbol": XSS, "reasons": [XSS], "would_veto": True}, "xss-1")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _run(base: str, chromium: str | None, shots: Path | None) -> list:
    from playwright.async_api import async_playwright

    problems = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(**({"executable_path": chromium} if chromium else {}))
        for name, vp in (("phone", {"width": 360, "height": 780}), ("desktop", {"width": 1280, "height": 900})):
            page = await browser.new_page(viewport=vp)
            errs: list = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(base + "/v2")
            await page.wait_for_timeout(1500)
            for tab in ("office", "radar", "scenarios", "journal", "risk"):
                await page.click(f"nav button[data-r={tab}]")
                await page.wait_for_timeout(700)
                sw = await page.evaluate("document.documentElement.scrollWidth")
                if sw > vp["width"] + 1:
                    problems.append(f"{name}/{tab}: horizontal scroll {sw}>{vp['width']}")
                if shots:
                    await page.screenshot(path=str(shots / f"{name}_{tab}.png"), full_page=True)
            await page.click("nav button[data-r=journal]")
            await page.wait_for_timeout(400)
            await page.click("button[data-k=audit]")
            await page.wait_for_timeout(500)
            for sid in ("xss-1", "big-1", "tiny-1"):
                await page.goto(base + "/v2?scenario=" + sid)
                await page.wait_for_timeout(1200)
                sw = await page.evaluate("document.documentElement.scrollWidth")
                if sw > vp["width"] + 1:
                    problems.append(f"{name}/card {sid}: horizontal scroll {sw}")
                if shots:
                    await page.screenshot(path=str(shots / f"{name}_card_{sid}.png"), full_page=True)
            if await page.evaluate("window.__xss === 1"):
                problems.append(f"{name}: XSS payload executed")
            if await page.locator("img[src=x]").count():
                problems.append(f"{name}: injected <img> present in DOM")
            if errs:
                problems.append(f"{name}: JS errors {errs[:3]}")
            await page.close()

        # API failure -> explicit error state, no stale numbers.
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await page.route("**/api/v2/**", lambda r: r.fulfill(status=500, body="boom"))
        await page.goto(base + "/v2")
        await page.wait_for_timeout(1200)
        if "Не вдалося завантажити" not in await page.content():
            problems.append("API 500: no error state")
        await page.close()

        # Slow API -> loading skeleton visible first.
        page = await browser.new_page(viewport={"width": 390, "height": 844})

        async def slow(route):
            await asyncio.sleep(2.0)
            await route.continue_()

        await page.route("**/api/v2/home", slow)
        await page.goto(base + "/v2")
        await page.wait_for_timeout(500)
        if await page.locator(".sk").count() == 0:
            problems.append("slow API: no loading state")
        await page.close()
        await browser.close()
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chromium", default=os.getenv("PW_CHROMIUM") or None)
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp()
    db = str(Path(tmp) / "ui.db")
    _seed(db)
    port = _free_port()
    env = {**os.environ, "OFFICE_DB_PATH": db, "OFFICE_MINI_FIXTURE": "1", "OFFICE_EXINFO_SEED": "1",
           "OFFICE_MINI_PORT": str(port), "OFFICE_MINI_HOST": "127.0.0.1", "DATABASE_URL": ""}
    proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "office_mini_app.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.2)
        shots = Path(a.shots) if a.shots else None
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
        problems = asyncio.run(_run(f"http://127.0.0.1:{port}", a.chromium, shots))
    finally:
        proc.terminate()
    if problems:
        print("FAIL UI smoke:\n  " + "\n  ".join(problems))
        return 1
    print("OK UI smoke: 5 tabs x phone/desktop, no h-scroll, XSS inert, API error and loading states")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

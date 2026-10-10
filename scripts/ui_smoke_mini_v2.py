#!/usr/bin/env python3
"""Browser smoke for Mini App 2.0 (manual/CI-optional: needs Playwright + Chromium).

Starts office_mini_app on a temporary SQLite with hostile/edge data and
fixture candles, then checks in Chromium at phone and desktop widths:
five tabs render without JS errors, no horizontal scroll, XSS payloads in
DB fields are not executed, API failure shows an error state, slow API
shows a loading state. No network, Telegram or orders.

--lwc FILE serves a local copy of lightweight-charts for the CDN URL (integrity hash is
still verified by the browser) so the interactive chart, not the canvas fallback, is
exercised even without internet. --posix-locale simulates a runner whose browser
language is "en-US@posix" (a real CI failure mode).

Usage: python3 scripts/ui_smoke_mini_v2.py [--chromium /path/to/chrome] [--shots DIR] [--lwc FILE] [--posix-locale]
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
    import office_positions as P

    P.migrate_positions(db)
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


async def _prep(page, lwc: str, posix: bool) -> None:
    if posix:
        await page.add_init_script(
            "Object.defineProperty(navigator,'language',{get:()=>'en-US@posix'});"
            "Object.defineProperty(navigator,'languages',{get:()=>['en-US@posix']});"
        )
    if lwc:
        body = Path(lwc).read_bytes()
        await page.route(
            "https://cdn.jsdelivr.net/npm/lightweight-charts@*/**",
            lambda r: r.fulfill(status=200, body=body, content_type="application/javascript"),
        )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


KEY = "smoke-write-key-0123456789"


async def _trades_flow(browser, base: str, name: str, vp: dict, lwc: str, posix: bool) -> list:
    """Ручний облік у браузері: внесення, частковий вихід, перенесення стопа, закриття; без ключа — явна відмова."""
    problems: list = []
    page = await browser.new_page(viewport=vp)
    await _prep(page, lwc, posix)
    errs: list = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    await page.goto(base + "/v2")
    await page.click("nav button[data-r=journal]")
    await page.wait_for_selector("#addpos")
    if "Мої угоди" not in await page.content():
        problems.append(f"{name}: journal does not default to «Мої угоди»")
    await page.click("#addpos")
    sym = "ETHUSDT" if name == "phone" else "SOLUSDT"
    await page.fill("#f_symbol", sym)
    await page.fill("#f_entry", "2000,5")
    await page.fill("#f_qty", "0.5")
    await page.fill("#f_sl", "1950")
    await page.fill("#f_tp1", "2100")
    await page.click("#fsend")
    await page.wait_for_timeout(700)
    if "Немає доступу" not in await page.inner_text("#fmsg"):
        problems.append(f"{name}: write without key must be refused with a clear message")
    await page.evaluate(f"localStorage.setItem('ao_wkey','{KEY}')")
    await page.click("#fsend")
    await page.wait_for_function("document.body.innerText.includes('Ризик зараз')")
    txt = await page.inner_text("main")
    if sym not in txt or "Ризик зараз" not in txt:
        problems.append(f"{name}: opened position not shown with risk")
    sw = await page.evaluate("document.documentElement.scrollWidth")
    if sw > vp["width"] + 1:
        problems.append(f"{name}/trades: horizontal scroll {sw}")
    await page.click("[data-a=partial]")
    await page.fill("#f_price", "2050")
    await page.fill("#f_qty", "0.2")
    await page.click("#fsend")
    await page.wait_for_timeout(700)
    await page.click("[data-a=move_sl]")
    await page.fill("#f_sl", "2000.5")
    await page.click("#fsend")
    await page.wait_for_timeout(700)
    await page.click("[data-a=close]")
    await page.fill("#f_price", "2080")
    await page.click("#fsend")
    await page.wait_for_function("document.body.innerText.includes('Немає внесених відкритих')")
    txt = await page.inner_text("main")
    if "Немає внесених відкритих" not in txt or "Результат" not in txt:
        problems.append(f"{name}: closed trade/result not shown")
    if errs:
        problems.append(f"{name}/trades: JS errors {errs[:3]}")
    await page.close()
    return problems


async def _run(base: str, chromium: str | None, shots: Path | None, lwc: str = "", posix: bool = False) -> list:
    from playwright.async_api import async_playwright

    problems = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(**({"executable_path": chromium} if chromium else {}))
        for name, vp in (("phone", {"width": 360, "height": 780}), ("desktop", {"width": 1280, "height": 900})):
            page = await browser.new_page(viewport=vp)
            await _prep(page, lwc, posix)
            errs: list = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(base + "/v2")
            await page.wait_for_timeout(1500)
            if lwc and not await page.evaluate("!!window.LightweightCharts"):
                problems.append(f"{name}: lightweight-charts did not load (integrity/route)")
            await page.click("nav button[data-r=office]")
            await page.wait_for_selector("#levq [data-q]")
            await page.click("#levq [data-q]")
            await page.wait_for_function("document.getElementById('levout').textContent.length > 20 && !document.getElementById('levout').textContent.includes('рахує')")
            if "FIXTURE" not in await page.inner_text("#levout"):
                problems.append(f"{name}: «Запитати Лева» did not render an answer: {await page.inner_text('#levout')!r}")
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
            # Accessibility basics: every control has a name, cards are keyboard-reachable.
            unnamed = await page.evaluate(
                "[...document.querySelectorAll('button')].filter(b=>!(b.innerText||b.getAttribute('aria-label')||'').trim()).length")
            if unnamed:
                problems.append(f"{name}: {unnamed} button(s) without an accessible name")
            await page.goto(base + "/v2")
            await page.wait_for_timeout(1000)
            await page.click("nav button[data-r=scenarios]")
            await page.wait_for_timeout(600)
            bad_cards = await page.evaluate(
                "[...document.querySelectorAll('[data-id]')].filter(e=>e.getAttribute('role')!=='button'||e.tabIndex!==0).length")
            if bad_cards:
                problems.append(f"{name}: {bad_cards} scenario card(s) not keyboard-accessible")
            await page.focus("[data-id]")
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(800)
            if "Для перевірки" not in await page.content():
                problems.append(f"{name}: Enter on a card did not open it")
            if await page.evaluate("document.querySelector('nav button.on')?.getAttribute('aria-current')") is None:
                problems.append(f"{name}: active tab lacks aria-current")
            try:
                await page.wait_for_function("Array.isArray(window.__chartLayers)", timeout=6000)
                layers = await page.evaluate("window.__chartLayers")
            except Exception:  # noqa: BLE001
                layers = None
            if not layers or not {"зона", "SL", "TP"}.issubset(set(layers)):
                problems.append(f"{name}: основні торгові рівні відсутні (шари: {layers})")
            if layers and any(x in ("канал", "SMC", "FVG", "сильна свічка") for x in layers):
                problems.append(f"{name}: дослідницькі шари мають бути вимкнені за замовчуванням (шари: {layers})")
            if layers and any(x in ("OB", "дзеркальний") or str(x).startswith("рівень") for x in layers):
                problems.append(f"{name}: на графіку є внутрішні рівні Лева: {layers}")
            if lwc and await page.locator("#chart canvas").count() == 0:
                problems.append(f"{name}: interactive chart canvas missing on scenario card")
            if await page.evaluate("window.__xss === 1"):
                problems.append(f"{name}: XSS payload executed")
            if await page.locator("img[src=x]").count():
                problems.append(f"{name}: injected <img> present in DOM")
            if errs:
                problems.append(f"{name}: JS errors {errs[:3]}")
            await page.close()
            problems += await _trades_flow(browser, base, name, vp, lwc, posix)

        # API failure -> explicit error state, no stale numbers.
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await _prep(page, lwc, posix)
        await page.route("**/api/v2/**", lambda r: r.fulfill(status=500, body="boom"))
        await page.goto(base + "/v2")
        await page.wait_for_timeout(1200)
        if "Не вдалося завантажити" not in await page.content():
            problems.append("API 500: no error state")
        await page.close()

        # Slow API -> loading skeleton visible first.
        page = await browser.new_page(viewport={"width": 390, "height": 844})
        await _prep(page, lwc, posix)

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
    ap.add_argument("--lwc", default="", help="local lightweight-charts standalone JS")
    ap.add_argument("--posix-locale", action="store_true")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp()
    db = str(Path(tmp) / "ui.db")
    _seed(db)
    port = _free_port()
    env = {**os.environ, "OFFICE_DB_PATH": db, "OFFICE_MINI_FIXTURE": "1", "OFFICE_EXINFO_SEED": "1",
           "OFFICE_MINI_PORT": str(port), "OFFICE_MINI_HOST": "127.0.0.1", "DATABASE_URL": "",
           "OFFICE_WRITE_KEY": KEY}
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
        problems = asyncio.run(_run(f"http://127.0.0.1:{port}", a.chromium, shots, a.lwc, a.posix_locale))
    finally:
        proc.terminate()
    if problems:
        print("FAIL UI smoke:\n  " + "\n  ".join(problems))
        return 1
    print("OK UI smoke: 5 tabs x phone/desktop, manual trade flow, no h-scroll, XSS inert, API error and loading states")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

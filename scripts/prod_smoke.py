#!/usr/bin/env python3
"""Продакшн-перевірка Mini App ЗЗОВНІ (з GitHub Actions-раннера, без секретів, лише GET): API свічок Binance Futures (усі ТФ, свіжість, історія), локальна бібліотека графіка,
і браузерна перевірка в емуляції iPhone (touch + pinch через CDP): інтерактивний графік, ТФ, історія при прокрутці, масштаб двома пальцями, шари, помилка+«Повторити».
Ніяких ордерів/Telegram/записів. Обмеження: це емуляція iPhone у Chromium, не фізичний пристрій і не Telegram WebView.
Usage: BASE=https://ai-office-miniapp.onrender.com python3 scripts/prod_smoke.py [--allow-fixture] [--shots DIR]"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.environ.get("BASE", "https://ai-office-miniapp.onrender.com").rstrip("/")
TF_SEC = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
P: list = []
NOTES: list = []


def get(path: str, timeout: int = 40):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "ai-office-prod-smoke/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def jget(path: str):
    st, b = get(path)
    return json.loads(b.decode("utf-8"))


def fail(msg: str) -> None:
    P.append(msg)
    print("FAIL", msg, flush=True)


def ok(msg: str) -> None:
    print("OK  ", msg, flush=True)


def api_checks(allow_fixture: bool) -> str:
    # --- сервіс і бібліотека графіка
    for attempt in range(6):          # Render може прокидатись після деплою
        try:
            st, _ = get("/api/summary")
            if st == 200:
                break
        except Exception as exc:  # noqa: BLE001
            print("  summary:", type(exc).__name__, flush=True)
        time.sleep(15)
    else:
        fail("/api/summary недоступний")
    st, js = get("/static/lightweight-charts-4.2.3.js")
    if st == 200 and len(js) > 100000:
        import base64
        import hashlib
        h = base64.b64encode(hashlib.sha384(js).digest()).decode()
        (ok if h == "stKllnUqA9AD0gsKCuUtf5XlqAW7PwIgDagoNsTWkjkBmJ/GZ/uHTgEBxdLV2VSK" else fail)(f"бібліотека графіка з нашого сервера, sha384 збігається: {h[:12]}…")
    else:
        fail(f"бібліотека графіка не віддається: {st} {len(js)}")
    # --- ключові API Mini App (регресії функціоналу): 200 і ok
    for path in ("/api/v2/home", "/api/v2/market", "/api/v2/scenarios", "/api/v2/radar", "/api/v2/live_radar", "/api/v2/office2", "/api/v2/paper", "/api/v2/journal", "/api/v2/risk", "/api/v2/overview"):
        try:
            st, b = get(path)
            d = json.loads(b.decode("utf-8"))
            bad = st != 200 or d.get("ok") is False
            (fail if bad else ok)(f"{path}: HTTP {st}, ok={d.get('ok')}, data_status={d.get('data_status')}")
        except Exception as exc:  # noqa: BLE001
            fail(f"{path}: {type(exc).__name__}")
    # --- свічки: TIA і BTC, усі ТФ
    now = time.time()
    for sym in ("TIAUSDT", "BTCUSDT"):
        for tf, sec in TF_SEC.items():
            try:
                d = jget(f"/api/v2/candles?symbol={sym}&tf={tf}&limit=500")
            except Exception as exc:  # noqa: BLE001
                fail(f"{sym} {tf}: помилка запиту {type(exc).__name__}")
                continue
            c = d.get("candles") or []
            src = d.get("source")
            problems = []
            if not d.get("ok") or len(c) < 300:
                problems.append(f"свічок {len(c)}")
            if not allow_fixture and (src != "binance_futures" or d.get("fixture")):
                problems.append(f"джерело {src}")
            if c:
                age = now - c[-1]["time"]
                if age > 2 * sec + 180 and not d.get("fixture"):
                    problems.append(f"остання свічка стара: {int(age)} с")
                ts = [x["time"] for x in c]
                if ts != sorted(ts) or len(set(ts)) != len(ts):
                    problems.append("порядок/дублі")
            (fail if problems else ok)(f"{sym} {tf}: {len(c)} св., джерело {src}, статус {d.get('data_status')}" + (f" — {'; '.join(problems)}" if problems else ""))
        # історія назад
        try:
            d1 = jget(f"/api/v2/candles?symbol={sym}&tf=H1&limit=500")
            first = d1["candles"][0]["time"]
            d2 = jget(f"/api/v2/candles?symbol={sym}&tf=H1&limit=500&end={first}")
            c2 = d2.get("candles") or []
            good = bool(c2) and c2[-1]["time"] < first and (allow_fixture or d2.get("source") == "binance_futures")
            (ok if good else fail)(f"{sym}: історія назад {len(c2)} св. до {datetime.fromtimestamp(first, timezone.utc):%m-%d %H:%M} (джерело {d2.get('source')})")
        except Exception as exc:  # noqa: BLE001
            fail(f"{sym}: історія назад: {type(exc).__name__}")
    # --- сценарій для браузерної перевірки
    sid = ""
    try:
        sc = jget("/api/v2/scenarios").get("scenarios") or []
        for pref in ("O2|",):
            sid = next((x.get("sid") or x.get("id") or x.get("scenario_id") or "" for x in sc if str(x.get("sid") or x.get("id") or x.get("scenario_id") or "").startswith(pref)), "")
        sid = sid or str((sc[0].get("sid") or sc[0].get("id") or sc[0].get("scenario_id")) if sc else "")
    except Exception as exc:  # noqa: BLE001
        NOTES.append(f"список сценаріїв: {type(exc).__name__}")
    return sid


async def pinch(cdp, x: float, y: float, d0: float, d1: float, steps: int = 20) -> None:
    def pts(d):
        return [{"x": x - d / 2, "y": y, "id": 1}, {"x": x + d / 2, "y": y, "id": 2}]
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": pts(d0)})
    for i in range(1, steps + 1):
        await cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": pts(d0 + (d1 - d0) * i / steps)})
        await asyncio.sleep(0.04)
    await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


async def browser_checks(sid: str, shots: str, allow_fixture: bool) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        kw = {"executable_path": os.environ["PW_CHROMIUM"]} if os.environ.get("PW_CHROMIUM") else {}
        br = await pw.chromium.launch(**kw)
        dev = pw.devices.get("iPhone 13") or {"viewport": {"width": 390, "height": 844}, "has_touch": True, "is_mobile": True, "device_scale_factor": 3}
        dev = {k: v for k, v in dev.items() if k != "default_browser_type"}
        ctx = await br.new_context(**dev)
        pg = await ctx.new_page()
        errs: list = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        urls = {"requests": []}
        pg.on("request", lambda r: urls["requests"].append(r.url))
        target = f"{BASE}/v2?scenario={urllib.parse.quote(sid)}" if sid else f"{BASE}/v2"
        await pg.goto(target, wait_until="domcontentloaded", timeout=60000)
        try:
            await pg.wait_for_function("window.LightweightCharts && typeof S!=='undefined' && S.bars && S.bars.length>0", timeout=60000)
            ok(f"інтерактивний графік завантажився (сценарій {sid or 'без id'})")
        except Exception:  # noqa: BLE001
            txt = ""
            try:
                txt = (await pg.inner_text("#chart"))[:200]
            except Exception:  # noqa: BLE001
                pass
            fail(f"графік не завантажився; #chart: {txt!r}")
            await br.close()
            return
        if any("jsdelivr" in u for u in urls["requests"]):
            fail("графік звертався до CDN — локальна бібліотека не використана")
        if not await pg.evaluate("usingLW"):
            fail("canvas-заглушка замість інтерактивного графіка")
        n0 = await pg.evaluate("S.bars.length")
        n_can = await pg.evaluate("document.querySelectorAll('#chart canvas').length")
        (ok if n0 >= 300 and n_can else fail)(f"стартово {n0} свічок, canvas {n_can}")
        sym = await pg.evaluate("(document.querySelector('#chart')&&S.histKey)||''")
        ok(f"монета/ТФ графіка: {sym}")
        # --- ТФ
        for tf in ("M1", "M5", "M15", "H1", "H4", "D1"):
            await pg.click(f"[data-tf={tf}]")
            try:
                await pg.wait_for_function(f"S.tf==='{tf}' && S.bars.length>0 && S.histKey.endsWith('|{tf.lower() if False else tf}') || S.tf==='{tf}' && S.bars.length>0", timeout=20000)
                ok(f"перемикач {tf}: {await pg.evaluate('S.bars.length')} св.")
            except Exception:  # noqa: BLE001
                fail(f"перемикач {tf}: графік не оновився")
        await pg.click("[data-tf=H1]")
        await pg.wait_for_function("S.tf==='H1' && S.bars.length>0", timeout=20000)
        await pg.wait_for_timeout(1500)
        # --- історія назад (свайп/прогортання)
        n1 = await pg.evaluate("S.bars.length")
        await pg.evaluate("chart.timeScale().setVisibleLogicalRange({from:-5,to:100})")
        try:
            await pg.wait_for_function(f"S.bars.length>{n1}", timeout=25000)
            ok(f"прокрутка назад підвантажила історію: {n1} → {await pg.evaluate('S.bars.length')} св.")
        except Exception:  # noqa: BLE001
            fail("прокрутка назад не підвантажила історію")
        # --- pinch двома пальцями (CDP touch): графік у видимій зоні екрана, обидва напрямки
        await pg.evaluate("document.querySelector('#chart').scrollIntoView({block:'center'})")
        await pg.wait_for_timeout(500)
        box = await (await pg.query_selector("#chart")).bounding_box()
        cdp = await ctx.new_cdp_session(pg)
        await pg.evaluate("chart.timeScale().setVisibleLogicalRange({from:S.bars.length-100,to:S.bars.length+5})")
        await pg.wait_for_timeout(600)
        rng = "(()=>{const r=chart.timeScale().getVisibleLogicalRange();return r.to-r.from})()"
        w0 = await pg.evaluate(rng)
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        await pinch(cdp, cx, cy, 200, 60, steps=20)
        await pg.wait_for_timeout(700)
        w1 = await pg.evaluate(rng)
        (ok if w1 > w0 * 1.15 else fail)(f"pinch-стиснення віддаляє графік (видимих барів {w0:.0f} → {w1:.0f})")
        await pinch(cdp, cx, cy, 60, 200, steps=20)
        await pg.wait_for_timeout(700)
        w2 = await pg.evaluate(rng)
        (ok if w2 < w1 * 0.85 else fail)(f"pinch-розтягування наближає графік ({w1:.0f} → {w2:.0f})")
        # --- збереження позиції при перемалюванні (перемикач шару)
        before = await pg.evaluate("chart.timeScale().getVisibleRange()")
        layers_before = await pg.evaluate("window.__chartLayers")
        btn = await pg.query_selector("[data-l=liq]") or await pg.query_selector("[data-l=ctx]") or await pg.query_selector("[data-l=ch]")
        if btn:
            await btn.click()
            await pg.wait_for_timeout(1800)
            after = await pg.evaluate("chart.timeScale().getVisibleRange()")
            (ok if before and after and abs(after["from"] - before["from"]) < 3 * TF_SEC["H1"] else fail)("перемикання шару не скидає позицію графіка")
            await btn.click()
            await pg.wait_for_timeout(800)
        else:
            NOTES.append("шарів для перемикання на цьому сценарії немає")
        ok(f"шари на графіку: {layers_before}")
        # --- усі вкладки Mini App відкриваються без JS-помилок і без порожніх екранів
        await pg.goto(f"{BASE}/v2", wait_until="domcontentloaded", timeout=60000)
        await pg.wait_for_selector("nav button[data-r]", timeout=40000)
        n_err = len(errs)
        for tab in ("office", "radar", "scenarios", "journal", "risk"):
            await pg.click(f"nav button[data-r={tab}]")
            await pg.wait_for_timeout(2500)
            txt = (await pg.inner_text("main"))[:4000] if await pg.query_selector("main") else (await pg.inner_text("body"))[:4000]
            sw_t = await pg.evaluate("document.documentElement.scrollWidth")
            problems = []
            if len(txt.strip()) < 40:
                problems.append("порожній екран")
            if sw_t > 391:
                problems.append(f"горизонтальний скрол {sw_t}")
            (fail if problems else ok)(f"вкладка {tab}: {len(txt)} симв." + (f" — {'; '.join(problems)}" if problems else ""))
        if len(errs) > n_err:
            fail(f"JS-помилки на вкладках: {errs[n_err:][:3]}")
        # --- радар: картка спостереження з графіком (шлях paintChart для WATCH), якщо є
        await pg.click("nav button[data-r=radar]")
        await pg.wait_for_timeout(2500)
        card = await pg.query_selector("[data-id], .card.tap")
        if card:
            try:
                await card.click()
                await pg.wait_for_function("typeof S!=='undefined' && S.bars && S.bars.length>0 && document.querySelectorAll('#chart canvas, #ch canvas').length>0", timeout=40000)
                ok(f"картка радара відкрила інтерактивний графік ({await pg.evaluate('S.histKey')})")
            except Exception:  # noqa: BLE001
                NOTES.append("картка радара не відкрила графік за 40 с (можливо, немає карток із графіком)")
        else:
            NOTES.append("у радарі зараз немає карток для відкриття")
        # --- помилка + «Повторити», коли бібліотека недоступна
        pg2 = await ctx.new_page()
        block = {"on": True}

        async def route(r):
            if block["on"] and "lightweight-charts" in r.request.url:
                await r.abort()
            else:
                await r.continue_()

        await pg2.route("**/*", route)
        await pg2.goto(target, wait_until="domcontentloaded", timeout=60000)
        try:
            await pg2.wait_for_selector("#chretry", timeout=40000)
            ok("без бібліотеки: явна помилка і кнопка «Повторити» (без підміни картинкою)")
            block["on"] = False
            await pg2.click("#chretry")
            await pg2.wait_for_function("typeof usingLW!=='undefined' && usingLW && S.bars.length>0", timeout=40000)
            ok("«Повторити» відновлює інтерактивний графік")
        except Exception:  # noqa: BLE001
            fail("помилка/«Повторити» при недоступній бібліотеці не спрацювали")
        sw = await pg.evaluate("document.documentElement.scrollWidth")
        (ok if sw <= 391 else fail)(f"горизонтального скролу немає ({sw})")
        if errs:
            fail(f"JS-помилки: {errs[:3]}")
        if shots:
            os.makedirs(shots, exist_ok=True)
            await pg.screenshot(path=os.path.join(shots, "iphone_chart.png"))
        await br.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-fixture", action="store_true")
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    print(f"# Production smoke · {BASE} · {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}", flush=True)
    sid = api_checks(a.allow_fixture)
    asyncio.run(browser_checks(sid, a.shots, a.allow_fixture))
    for n in NOTES:
        print("NOTE", n)
    print("ПРОБЛЕМ:", len(P))
    print("ALL OK" if not P else "FAILED")
    return 1 if P else 0


if __name__ == "__main__":
    raise SystemExit(main())

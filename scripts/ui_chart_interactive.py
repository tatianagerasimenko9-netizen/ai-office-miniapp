#!/usr/bin/env python3
"""Браузерний тест інтерактивного графіка Mini App (Playwright + Chromium; без мережі, фікстурні свічки OFFICE_MINI_FIXTURE=1, жодних ордерів/Telegram).
Перевіряє: бібліотека графіка віддається з нашого сервера (не залежить від CDN); справжній інтерактивний графік (не canvas-заглушка); 500 свічок на старті;
прокрутка ліворуч підвантажує історію (end=…); масштаб колесом; перемикання ТФ; шар «Ліквідність»; перемалювання не скидає позицію; без JS-помилок і без горизонтального скролу.
Usage: PW_CHROMIUM=/path/to/chromium python3 scripts/ui_chart_interactive.py"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    db = os.path.join(tempfile.mkdtemp(), "t.db")
    os.environ["OFFICE_DB_PATH"] = db
    import office_bridge as OB
    from office2 import engine as E

    OB.init_office_db(db)
    for d in E.DDL:
        OB._execute(db, d)
    snap = json.loads((ROOT / "scripts" / "fixtures" / "o2_snapshot_ada_2026-10-12.json").read_text(encoding="utf-8"))
    sid = "O2|1899a369ddff|1791804600"
    OB._execute(db, "INSERT INTO office2_live_signal(scenario_id,symbol,direction,created_ts,valid_until_ts,status,snapshot_json,version,delivered_ts,msg_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, "ADAUSDT", "LONG", 1791804600.0, 1791804600.0 + 6 * 3600, "DELIVERED", json.dumps(snap, ensure_ascii=False), "v", 1791804700.0, 10528))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = dict(os.environ, OFFICE_MINI_HOST="127.0.0.1", OFFICE_MINI_PORT=str(port), OFFICE_DB_PATH=db, OFFICE_MINI_FIXTURE="1")
    proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "office_mini_app.py")], env=env, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    problems: list = []
    try:
        for _ in range(40):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.25)
        asyncio.run(_run(port, sid, problems))
    finally:
        proc.terminate()
    for p in problems:
        print("FAIL", p)
    print("ALL OK" if not problems else "FAILED")
    return 1 if problems else 0


async def _run(port: int, sid: str, problems: list) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        kw = {"executable_path": os.environ["PW_CHROMIUM"]} if os.environ.get("PW_CHROMIUM") else {}
        br = await pw.chromium.launch(**kw)
        ctx = await br.new_context(viewport={"width": 390, "height": 844}, has_touch=True)
        pg = await ctx.new_page()
        errs: list = []
        urls: list = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("request", lambda r: urls.append(r.url))
        await pg.goto(f"http://127.0.0.1:{port}/v2?scenario={sid}")
        await pg.wait_for_function("window.LightweightCharts && typeof S!=='undefined' && S.bars && S.bars.length>0", timeout=15000)
        if not any("/static/lightweight-charts-4.2.3.js" in u for u in urls):
            problems.append("бібліотека графіка не завантажена з нашого сервера")
        if any("jsdelivr" in u for u in urls):
            problems.append("CDN не має бути потрібен, коли локальна бібліотека віддається")
        if not await pg.evaluate("usingLW"):
            problems.append("графік працює на canvas-заглушці, а не на інтерактивній бібліотеці")
        n0 = await pg.evaluate("S.bars.length")
        if n0 < 400:
            problems.append(f"на старті замало історії: {n0} свічок")
        await pg.evaluate("chart.timeScale().setVisibleLogicalRange({from:-5,to:100})")
        await pg.wait_for_function(f"S.bars.length>{n0}", timeout=8000)
        n1 = await pg.evaluate("S.bars.length")
        if not any("end=" in u for u in urls):
            problems.append("прокрутка ліворуч не запитала історію (end=)")
        times = await pg.evaluate("S.bars.map(b=>b.time)")
        if times != sorted(times) or len(set(times)) != len(times):
            problems.append("історія змерджена з порушенням порядку/дублями")
        box = await (await pg.query_selector("#chart")).bounding_box()
        r0 = await pg.evaluate("chart.timeScale().getVisibleLogicalRange()")
        await pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await pg.mouse.wheel(0, -600)
        await pg.wait_for_timeout(500)
        r1 = await pg.evaluate("chart.timeScale().getVisibleLogicalRange()")
        if round(r0["to"] - r0["from"]) == round(r1["to"] - r1["from"]):
            problems.append("колесо не змінює масштаб")
        before = await pg.evaluate("chart.timeScale().getVisibleRange()")
        await pg.click("[data-l=liq]")
        await pg.wait_for_function("window.__chartLayers && window.__chartLayers.includes('ліквідність')", timeout=6000)
        after = await pg.evaluate("chart.timeScale().getVisibleRange()")
        if before and after and abs(after["from"] - before["from"]) > 3 * 3600:
            problems.append("перемалювання (шар) скинуло позицію графіка")
        if not await pg.evaluate("S.bars.length") >= n1:
            problems.append("перемалювання загубило підвантажену історію")
        for tf in ("M1", "M5", "M15", "H4", "D1", "H1"):
            await pg.click(f"[data-tf={tf}]")
            await pg.wait_for_function(f"S.tf==='{tf}' && S.bars.length>0", timeout=6000)
        sw = await pg.evaluate("document.documentElement.scrollWidth")
        if sw > 391:
            problems.append(f"горизонтальний скрол {sw}")
        if errs:
            problems.append(f"JS-помилки: {errs[:3]}")
        # --- бібліотека графіка недоступна: явна помилка + «Повторити», без тихої підміни картинкою
        pg2 = await ctx.new_page()
        blocked = {"on": True}

        async def route(r):
            if blocked["on"] and ("lightweight-charts" in r.request.url):
                await r.abort()
            else:
                await r.continue_()

        await pg2.route("**/*", route)
        await pg2.goto(f"http://127.0.0.1:{port}/v2?scenario={sid}")
        await pg2.wait_for_selector("#chretry", timeout=15000)
        txt = await pg2.inner_text("#chart")
        if "не завантажився" not in txt:
            problems.append(f"немає явної помилки при недоступній бібліотеці: {txt!r}")
        if await pg2.evaluate("document.querySelectorAll('#chart canvas').length"):
            problems.append("при недоступній бібліотеці показано canvas-картинку замість помилки")
        blocked["on"] = False
        await pg2.click("#chretry")
        await pg2.wait_for_function("typeof usingLW!=='undefined' && usingLW && S.bars.length>0 && document.querySelectorAll('#chart canvas').length>0", timeout=10000)
        await br.close()


if __name__ == "__main__":
    raise SystemExit(main())

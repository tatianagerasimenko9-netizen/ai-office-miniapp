#!/usr/bin/env python3
"""Браузерна перевірка нової READY-картки (телефон 360×780 і десктоп): ієрархія що → чому → де → чи можна зараз, графік у першому екрані,
LONG/SHORT, «зараз» чинний/нечинний, TP1/СТОП досягнуто, без збережених підтверджень, 1/2/3 цілі, довга назва сетапу, календар недоступний.
Дані картки будуються справжнім `office_mini_v2.scenario_detail` на тимчасовій БД; свічки — fixture-сервер. Без мережі, Telegram і ордерів.
Використання: python3 scripts/ui_ready_card.py [--shots DIR] [--chromium PATH] [--lwc FILE]"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def build_cases(db: str) -> dict:
    os.environ.update(OFFICE_DB_PATH=db, DATABASE_URL="", OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1", OFFICE_CALENDAR_BLOCK="1")
    os.environ.pop("OFFICE_MINI_FIXTURE", None)
    import office_calendar as cal
    import office_market_data as MD
    import office_mini_v2 as MV
    import office_ready_core as RC
    import office_signal_track as T
    from office_bridge import init_office_db, log_event, signal_upsert

    init_office_db(db)
    MD.fetch_candles = lambda *a, **k: {}
    MV.fetch_candles = MD.fetch_candles
    cal._CACHE.update(at=0.0, events=None, fail_at=time.time(), error="offline")   # календар недоступний (чесно показується)
    price_box = {"p": 1.0}
    now_iso = datetime.now(timezone.utc).isoformat()
    MV._live_price = lambda sym: {"price": price_box["p"], "fresh": True, "as_of": now_iso, "data_status": "DATA_OK"}
    NOW = time.time()
    cases = {}

    def mk(name, sym, side, entry, sl, tps, lo, hi, tags, mode, price, ms=(), no_confirm=False, age=600):
        sid = f"SCN|{sym}|{side}|H1|{name}"
        t1, t2, t3 = (list(tps) + [None, None, None])[:3]
        signal_upsert(db, signal_id=sid, symbol=sym, direction=side, entry_low=lo, entry_high=hi, sl=sl, tp1=t1, tp2=t2, rr=None, status="CONFIRMED",
                      analysis_note=f"ЛЕВ cancel={sl} ckey=x origin=desk tf=H1 scenario_id={sid} confirm_sent=1 confirmed_px={entry}")
        me = __import__("office_alert_gate").max_entry_price(side, sl, t1, t2)
        conf = None if no_confirm else RC.confirm_basis({"confirms": tags, "detail": "x", "price": entry, "need_retest": mode == "retest" and False})
        if conf is not None and mode == "retest":
            conf["mode"] = "retest"
        T.record_plan(db, scenario_id=sid, symbol=sym, direction=side, tf="H1", entry=entry, sl=sl, tp1=t1, tp2=t2, tp3=t3, max_entry=me,
                      confirmed_ts=NOW - age, valid_until_ts=NOW - age + 86400, confirm_msg_id=100,
                      gate=RC.gate_snapshot(direction=side, entry=entry, sl=sl, tp1=t1, tp2=t2, tp3=t3, max_entry=me, confirm=conf))
        for lv in ms:
            log_event(db, "SCENARIO_MILESTONE", {"scenario_id": sid, "level": lv, "symbol": sym}, sid)
        price_box["p"] = price
        d = MV.scenario_detail(sid)
        cases[name] = {"sid": sid, "json": d, "side": side}

    mk("spx", "SPXUSDT", "SHORT", 0.4437, 0.44966, [0.4299, 0.4239, 0.4177], 0.4406, 0.449, ["flag", "fvg_retest"], "inside_zone", 0.4422)
    mk("syrup", "SYRUPUSDT", "SHORT", 0.25779, 0.260378, [0.23599, 0.22235, 0.19808], 0.25535, 0.25913, ["level_hold", "channel_edge"], "inside_zone", 0.25464)
    mk("eigen", "EIGENUSDT", "SHORT", 0.2623, 0.265343, [0.2448, 0.2387, 0.2278], 0.2609, 0.2638, ["flag", "level_retest", "channel_edge", "engulf"], "inside_zone", 0.2625)
    mk("longok", "ABCUSDT", "LONG", 10.0, 9.7, [10.5, 10.9], 9.9, 10.1, [], "retest", 10.02)
    mk("tp1", "TPUSDT", "LONG", 10.0, 9.7, [10.5, 10.9, 11.4], 9.9, 10.1, ["ob_retest"], "inside_zone", 10.6, ms=("TP1",))
    mk("stop", "STPUSDT", "SHORT", 5.0, 5.2, [4.7, 4.5], 4.95, 5.05, ["sfp", "pin_bar"], "inside_zone", 5.25, ms=("SL",))
    mk("noconf", "OLDUSDT", "LONG", 2.0, 1.94, [2.1], 1.98, 2.02, [], "inside_zone", 2.0, no_confirm=True)
    mk("long_name", "LONGNAMEUSDT", "LONG", 1.0, 0.97, [1.05, 1.08, 1.12], 0.99, 1.01, ["level_retest", "channel_edge", "engulf", "flag", "fvg_retest", "pin_bar"], "inside_zone", 1.0)
    return cases


async def _close(x) -> None:
    try:
        await x.close()
    except Exception:  # noqa: BLE001  (відомий збій dispose у Playwright після route-обробників; на результат перевірки не впливає)
        pass


async def run(base: str, cases: dict, chromium, shots, lwc: str) -> list:
    from playwright.async_api import async_playwright

    problems = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(**({"executable_path": chromium} if chromium else {}))
        for vname, vp in (("phone", {"width": 360, "height": 780}), ("desktop", {"width": 1100, "height": 900})):
            for name, case in cases.items():
                ctx = await browser.new_context(viewport=vp)
                page = await ctx.new_page()
                if lwc:
                    body = Path(lwc).read_bytes()
                    await page.route("https://cdn.jsdelivr.net/npm/lightweight-charts@*/**", lambda r: r.fulfill(status=200, body=body, content_type="application/javascript"))
                errs: list = []
                page.on("pageerror", lambda e, n=name: errs.append(str(e)))

                async def scen(route, _req=None, c=None):
                    c = case
                    q = parse_qs(urlparse(route.request.url).query)
                    if (q.get("id") or [""])[0] == c["sid"]:
                        await route.fulfill(status=200, body=json.dumps(c["json"], ensure_ascii=False), content_type="application/json")
                    else:
                        await route.continue_()
                await page.route("**/api/v2/scenario?*", scen)
                await page.goto(base + "/v2?scenario=" + case["sid"].replace("|", "%7C"))
                try:
                    await page.wait_for_selector(".rh", timeout=8000)
                except Exception:  # noqa: BLE001
                    problems.append(f"{vname}/{name}: READY-картка не відрисувалась")
                    await _close(ctx)
                    continue
                await page.wait_for_timeout(700)
                txt = await page.inner_text("main")
                top = await page.evaluate("""()=>{const r=document.querySelector('.rh'), n=document.querySelector('.nowbar'), c=document.getElementById('chart'),
                    w=document.querySelector('.rh .rnm');
                    return {rh:!!r, now:!!n, nowCls:n?n.className:'', chartTop:c?c.getBoundingClientRect().top+window.scrollY:-1, vh:window.innerHeight,
                      hscroll:document.documentElement.scrollWidth>document.documentElement.clientWidth+1, nm:w?w.textContent:'', cells:document.querySelectorAll('.rh .rg div').length,
                      canvas:!!document.querySelector('#chart canvas'), btn:!!document.getElementById('iopen'), btnText:(document.getElementById('iopen')||{}).textContent||'',
                      prog:Array.from(document.querySelectorAll('.prog span')).map(x=>x.textContent), details:!!document.querySelector('details.dbg')}}""")
                if errs:
                    problems.append(f"{vname}/{name}: JS-помилки {errs[:2]}")
                if not (top["rh"] and top["now"]):
                    problems.append(f"{vname}/{name}: немає героя або смуги «Зараз»")
                if top["hscroll"]:
                    problems.append(f"{vname}/{name}: горизонтальний скрол")
                if top["btnText"].strip() != "Я відкрила угоду за цим сценарієм":
                    problems.append(f"{vname}/{name}: кнопка manual-open змінена: {top['btnText']!r}")
                if vname == "phone" and top["chartTop"] > top["vh"] * 0.85:
                    problems.append(f"{vname}/{name}: графік не в першому екрані ({top['chartTop']:.0f}px при висоті екрана {top['vh']})")
                if "Автоматичне повідомлення ще не підтверджено" in txt:
                    problems.append(f"{vname}/{name}: лишився застарілий текст про автоповідомлення")
                if "sc_ote" in txt.split("Технічні деталі")[0]:
                    problems.append(f"{vname}/{name}: технічні теги в основній частині картки")
                want_side = "SHORT" if case["side"] == "SHORT" else "LONG"
                if want_side not in txt.split("Зараз")[0]:
                    problems.append(f"{vname}/{name}: у верху немає {want_side}")
                if name == "tp1" and "✓ TP1" not in " ".join(top["prog"]):
                    problems.append(f"{vname}/{name}: TP1 досягнуто, але не відмічено: {top['prog']}")
                if name == "stop" and "Досягнуто стоп-рівня сценарію" not in " ".join(top["prog"]):
                    problems.append(f"{vname}/{name}: стоп досягнуто, але не відмічено")
                if name == "noconf" and "не збережене" not in top["nm"]:
                    problems.append(f"{vname}/{name}: без збереженого підтвердження назва має чесно це казати: {top['nm']!r}")
                if name in ("spx", "syrup") and ("Новий вхід зараз не розглядати" not in txt and "ще чинні" not in txt):
                    problems.append(f"{vname}/{name}: немає вердикту «зараз»")
                if name == "longok" and top["nowCls"].split()[-1] != "g":
                    problems.append(f"{vname}/{name}: ціна = вхід, очікувався зелений «зараз», а є {top['nowCls']}")
                if name == "syrup" and "рівень утримано біля краю лінії тренду" not in top["nm"]:
                    problems.append(f"{vname}/{name}: назва сетапу: {top['nm']!r}")
                if name == "spx" and top["cells"] != 5:
                    problems.append(f"{vname}/{name}: очікувалось 5 клітинок (вхід, SL, TP1, TP2, TP3), а є {top['cells']}")
                if name == "syrup" and "Новий вхід зараз не розглядати" not in txt:
                    problems.append(f"{vname}/{name}: ціна нижче зони входу — очікувалось «не розглядати»")
                if shots:
                    await page.screenshot(path=str(shots / f"{vname}_{name}.png"), full_page=False)
                await _close(ctx)
        await _close(browser)
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="")
    ap.add_argument("--chromium", default=os.getenv("PW_CHROMIUM") or None)
    ap.add_argument("--lwc", default="")
    a = ap.parse_args()
    tmp = tempfile.mkdtemp()
    cases = build_cases(str(Path(tmp) / "cards.db"))
    bad = [n for n, c in cases.items() if not c["json"].get("ok") or not (c["json"].get("human") or {}).get("ready")]
    if bad:
        print("FAIL: сервер не побудував READY-стан для", bad, {n: (cases[n]["json"].get("human") or {}).get("state") for n in bad})
        return 1
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    pnum = port.getsockname()[1]
    port.close()
    db2 = str(Path(tmp) / "srv.db")
    env = {**os.environ, "OFFICE_DB_PATH": db2, "OFFICE_MINI_FIXTURE": "1", "OFFICE_EXINFO_SEED": "1", "OFFICE_MINI_PORT": str(pnum), "OFFICE_MINI_HOST": "127.0.0.1", "DATABASE_URL": ""}
    proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "office_mini_app.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        up = False
        for _ in range(150):   # до 30 с: на повільному CI сервер стартує довше за 10 с (раніше цикл мовчки йшов далі й браузер бачив ERR_CONNECTION_REFUSED)
            if proc.poll() is not None:
                print(f"FAIL: сервер Mini App завершився зі кодом {proc.returncode} до старту")
                return 1
            try:
                socket.create_connection(("127.0.0.1", pnum), 0.2).close()
                up = True
                break
            except OSError:
                time.sleep(0.2)
        if not up:
            print("FAIL: сервер Mini App не відкрив порт за 30 с")
            return 1
        shots = Path(a.shots) if a.shots else None
        if shots:
            shots.mkdir(parents=True, exist_ok=True)
        problems = asyncio.run(run(f"http://127.0.0.1:{pnum}", cases, a.chromium, shots, a.lwc))
    finally:
        proc.terminate()
    if problems:
        print("FAIL READY-картка:\n  " + "\n  ".join(problems))
        return 1
    print(f"OK READY-картка: {len(cases)} сценаріїв × телефон/десктоп, ієрархія, «зараз», прогрес TP/СТОП, кнопка manual-open без змін, без h-scroll")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

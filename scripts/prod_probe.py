#!/usr/bin/env python3
"""Read-only probe of a running Mini App (production or local). Only HTTP GET; never POST, never Telegram, no orders.

Reports: reachability/latency of every read endpoint, DB backend and git sha, candle freshness per timeframe,
overview feed status, scenario/trade counts, whether manual-ledger writes are configured, and (with --browser)
phone/desktop rendering of the 5 tabs: JS errors, horizontal scroll, chart canvas, screenshots.

Usage: python3 scripts/prod_probe.py --base https://ai-office-miniapp.onrender.com [--browser] [--out DIR] [--symbol BTCUSDT]
Exit 1 if the app is unreachable, returns 5xx, or the browser shows JS errors/overflow.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

TF_SEC = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
ENDPOINTS = ["/api/v2/home", "/api/v2/overview", "/api/v2/scenarios?watching=1", "/api/v2/scanner", "/api/v2/risk",
             "/api/v2/settings", "/api/v2/trades?state=all", "/api/v2/auth", "/api/v2/session", "/api/v2/journal?kind=audit"]


def get(base: str, path: str, timeout: float = 45.0) -> Dict[str, Any]:
    t0 = time.time()
    req = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": "office-prod-probe/1 (read-only)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read() or b"", e.code
    except Exception as e:  # noqa: BLE001
        return {"path": path, "status": None, "error": f"{type(e).__name__}: {e}", "ms": int((time.time() - t0) * 1000)}
    out: Dict[str, Any] = {"path": path, "status": code, "ms": int((time.time() - t0) * 1000), "bytes": len(raw)}
    try:
        out["json"] = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        out["json"] = None
    return out


def _age_min(ts: Any, now: float) -> Any:
    try:
        return round((now - datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()) / 60, 1)
    except Exception:  # noqa: BLE001
        return None


def probe_http(base: str, symbol: str) -> Dict[str, Any]:
    now = time.time()
    rep: Dict[str, Any] = {"at": datetime.now(timezone.utc).isoformat(), "base": base, "endpoints": [], "problems": []}
    page = get(base, "/v2")
    rep["page"] = {k: page.get(k) for k in ("status", "ms", "bytes", "error")}
    if page.get("status") != 200:
        rep["problems"].append(f"/v2 -> {page.get('status') or page.get('error')}")
    data: Dict[str, Any] = {}
    for ep in ENDPOINTS:
        r = get(base, ep)
        rep["endpoints"].append({k: r.get(k) for k in ("path", "status", "ms", "error")})
        data[ep] = r.get("json")
        if r.get("status") is None or (r["status"] or 0) >= 500:
            rep["problems"].append(f"{ep} -> {r.get('status') or r.get('error')}")
    home = data.get("/api/v2/home") or {}
    rep["app"] = {"db_backend": home.get("db_backend"), "git_sha": home.get("git_sha"), "btc": home.get("btc"),
                  "sessions": home.get("sessions"), "market_regime": home.get("market_regime")}
    ov = data.get("/api/v2/overview") or {}
    rep["feeds"] = [{"symbol": m.get("symbol"), "data_status": m.get("data_status"), "age_min": _age_min(m.get("as_of"), now)}
                    for m in (ov.get("marks") or [])]
    sc = (data.get("/api/v2/scenarios?watching=1") or {}).get("scenarios") or []
    groups: Dict[str, int] = {}
    for s in sc:
        g = (s.get("status") or {}).get("group") or "?"
        groups[g] = groups.get(g, 0) + 1
    rep["scenarios"] = {"n": len(sc), "by_group": groups}
    tr = data.get("/api/v2/trades?state=all") or {}
    rep["trades"] = {"schema_missing": tr.get("schema_missing"), "n": len(tr.get("positions") or []),
                     "exposure_status": (tr.get("exposure") or {}).get("status")}
    au = data.get("/api/v2/auth") or {}
    rep["write_enabled"] = au.get("write_enabled")
    rep["candles"] = {}
    for tf in ("M1", "M5", "M15", "H1", "H4", "D1"):
        r = get(base, f"/api/v2/candles?symbol={symbol}&tf={tf}&limit=180")
        j = r.get("json") or {}
        cs = j.get("candles") or []
        age = _age_min(j.get("as_of"), now)
        stale = age is None or age * 60 > TF_SEC[tf] * 2.5
        rep["candles"][tf] = {"status": r.get("status"), "n": len(cs), "as_of": j.get("as_of"), "age_min": age,
                              "source": j.get("source"), "fixture": bool(j.get("fixture")), "stale": stale}
        if r.get("status") is None or (r["status"] or 0) >= 500:
            rep["problems"].append(f"candles {tf} -> {r.get('status') or r.get('error')}")
    rep["verdict"] = {"reachable": page.get("status") == 200, "hard_problems": len(rep["problems"]),
                      "stale_timeframes": [t for t, c in rep["candles"].items() if c["stale"]]}
    return rep


async def probe_browser(base: str, out: Path) -> Dict[str, Any]:
    from playwright.async_api import async_playwright

    res: Dict[str, Any] = {"views": [], "problems": []}
    async with async_playwright() as p:
        import os

        b = await p.chromium.launch(**({"executable_path": os.environ["PW_CHROMIUM"]} if os.environ.get("PW_CHROMIUM") else {}))
        for name, vp in (("phone360", {"width": 360, "height": 780}), ("desktop", {"width": 1280, "height": 900})):
            pg = await b.new_page(viewport=vp)
            errs: List[str] = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
            await pg.goto(base.rstrip("/") + "/v2", wait_until="domcontentloaded", timeout=60000)
            await pg.wait_for_timeout(4000)
            for tab in ("office", "radar", "scenarios", "journal", "risk"):
                await pg.click(f"nav button[data-r={tab}]")
                await pg.wait_for_timeout(2500)
                sw = await pg.evaluate("document.documentElement.scrollWidth")
                text = (await pg.inner_text("main"))[:400]
                await pg.screenshot(path=str(out / f"{name}_{tab}.png"), full_page=True)
                res["views"].append({"viewport": name, "tab": tab, "h_scroll": sw > vp["width"] + 1, "sample": text})
                if sw > vp["width"] + 1:
                    res["problems"].append(f"{name}/{tab}: horizontal scroll {sw}")
            # first scenario card: interactive chart present?
            await pg.click("nav button[data-r=scenarios]")
            await pg.wait_for_timeout(2500)
            if await pg.locator("[data-id]").count():
                await pg.locator("[data-id]").first.click()
                await pg.wait_for_timeout(5000)
                canvas = await pg.locator("#chart canvas").count()
                res["views"].append({"viewport": name, "tab": "scenario_card", "chart_canvas": canvas > 0,
                                     "asof": (await pg.inner_text("#asof")) if await pg.locator("#asof").count() else ""})
                await pg.screenshot(path=str(out / f"{name}_card.png"), full_page=True)
                if not canvas:
                    res["problems"].append(f"{name}: chart canvas missing on scenario card")
            if errs:
                res["problems"].append(f"{name}: JS errors {errs[:3]}")
            await pg.close()
        await b.close()
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--browser", action="store_true")
    ap.add_argument("--out", default="probe_out")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rep = probe_http(a.base, a.symbol)
    if a.browser and rep["verdict"]["reachable"]:
        import asyncio

        rep["browser"] = asyncio.run(probe_browser(a.base, out))
        rep["problems"] += rep["browser"]["problems"]
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("at", "app", "feeds", "scenarios", "trades", "write_enabled", "verdict")},
                     ensure_ascii=False, indent=2))
    print("candles:", {t: (c["age_min"], "STALE" if c["stale"] else "ok") for t, c in rep["candles"].items()})
    if rep["problems"]:
        print("PROBLEMS:\n  " + "\n  ".join(rep["problems"]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

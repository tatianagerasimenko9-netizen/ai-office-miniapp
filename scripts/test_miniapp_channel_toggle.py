#!/usr/bin/env python3
"""Mini App: перемикач «Канал» має показувати живий регресійний канал і для READY, де канал не був причиною (ETC/MARSCOIN/LDO мали objects без 'channel').
Перевіряємо джерело інтерфейсу (фільтр __objs більше не застосовується до каналу) і те, що API віддає канал та його справжню довжину."""
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


html = (ROOT / "office_web" / "mini_v2.html").read_text()
m = re.search(r"if\(cx&&cx\.ok&&S\.layers\.ch&&cx\.channel([^)]*)\)\{", html)
check(m is not None, "умова малювання каналу знайдена")
check(m is not None and "__objs" not in m.group(1), f"канал не залежить від __objs: {m.group(0) if m else None}")
check("лише '+c.length+' св. замість 100" in html, "коротший за 100 канал позначається, а не мовчки видається за 100")
# FVG і сильна свічка лишаються лише для актуальних у сценарії (як у підписі перемикача)
check("cx.fvg&&(!s.__objs||s.__objs.includes('fvg'))" in html, "FVG: фільтр актуальності збережено")

import office_mini_v2 as MV  # noqa: E402
import office_setup_story as su  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def fake(n):
    rows = [{"time": int((T0 + timedelta(minutes=15 * i)).timestamp()), "ts": (T0 + timedelta(minutes=15 * i)).isoformat(), "open": 100 + 0.05 * i, "high": 100.5 + 0.05 * i,
             "low": 99.5 + 0.05 * i, "close": 100.1 + 0.05 * i + math.sin(i / 5)} for i in range(n)]
    return {"candles": rows, "tf": "15m", "data_status": "DATA_OK"}


for n, want in ((300, 100), (60, 59)):
    MV.candles_payload = lambda s, t, l, n=n: fake(n)
    cx = MV.chart_context_payload("ETCUSDT", "15m", "SHORT", 8.89, 9.04, ())
    check(cx["ok"] and cx.get("channel") and cx["channel"]["length"] == want, f"API: {n} свічок → довжина каналу {want}, а не мовчки інша: {cx.get('channel', {}).get('length')}")
for name, tags in (("ETC", ["flag"]), ("MARSCOIN", ["sweep_pool", "fvg_retest", "ote"]), ("LDO", ["double_top", "choch", "upthrust"])):
    check("channel" not in su.build(tags, "inside_zone", "SHORT")["objects"], f"{name}: канал не в objects сценарію (раніше через це ховався)")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)

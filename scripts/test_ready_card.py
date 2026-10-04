#!/usr/bin/env python3
"""Telegram-картка READY: вертикальний текст (без ринкових рядків), «Чому» з цифрами, фаза лише ≥3σ, картинка без обрізання."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
import office_ready_card as rc  # noqa: E402
import office_user_messages as um  # noqa: E402
import office_language as lang  # noqa: E402

FAIL = []


def check(ok, msg):
    if not ok:
        FAIL.append(msg)
        print("FAIL:", msg)


def candles(p0, vol=0.004, n=96):
    out, p = [], p0
    for i in range(n):
        o = p
        c = o * (1 + (0.5 - ((i * 7919) % 100) / 100.0) * vol * 2)
        out.append(dict(open=o, high=max(o, c) * (1 + vol / 3), low=min(o, c) * (1 - vol / 3), close=c))
        p = c
    return out


# --- текст
t = rc.caption(symbol="ONEUSDT", direction="SHORT", entry=0.0245, sl=0.0258, tp1=0.0238, tp2=0.0231, tp3=0.0219, max_entry=0.0248, risk_usd=10,
               valid_until="05.10 12:30", why=rc.short_why(tags=["level_retest", "engulf"], mode=None, direction="SHORT", symbol="ONEUSDT", entry=0.0245), sigma30=3.2)
L = t.split("\n")
check(L[0] == "🔴 SHORT · ONE", "заголовок")
check(L[1].startswith("Чому: Ціна повернулась до 0,0245 і відбилась вниз"), "чому з цифрою")
for k in ("Вхід: 0,0245–0,0248", "Стоп: 0,0258 (−5,31%)", "TP1: ", "TP2: ", "TP3: ", "Ризик: 10 $", "⚠️ Рух уже розтягнутий: 3,2σ за 30 хв.", "⏳ до 05.10 12:30"):
    check(any(x.startswith(k) for x in L), f"рядок {k}")
check(L.index("⚠️ Рух уже розтягнутий: 3,2σ за 30 хв.") < len(L) - 1, "фаза перед строком")
for bad in ("Ринок", "BTC", "Weekly", "Тиждень", "фандинг", "кореляц", "Сетап", "Позиція"):
    check(bad not in t, f"у Telegram не має бути «{bad}»")
check(len(t) < 1000, "підпис ≤1024")
check(not lang.problems(t), f"мова: {lang.problems(t)}")
# немає TP2/TP3 → рядків немає, жодного «немає обґрунтованої»
t2 = rc.caption(symbol="ETHUSDT", direction="LONG", entry=3120.5, sl=3090, tp1=3160, risk_usd=10, valid_until="x", why="w")
check("TP2" not in t2 and "TP3" not in t2 and "обґрунтован" not in t2, "відсутні цілі не показуються")
# нормальна фаза мовчить
t3 = rc.caption(symbol="ETHUSDT", direction="LONG", entry=3120.5, sl=3090, tp1=3160, valid_until="x", why="w", sigma30=2.9)
check("розтягнутий" not in t3, "<3σ мовчить")
# заголовок і напрям
check(rc.caption(symbol="BTCUSDT", direction="LONG", entry=64000, sl=63000, tp1=65000).startswith("🟢 LONG · BTC"), "LONG заголовок")
# «Чому» різних сетапів: конкретика, без самої назви патерну
for tags in (["level_hold"], ["fvg_retest"], ["sweep_pool"], ["upthrust"], ["ote"], ["double_top"], ["ascending_triangle", "bos"], ["ob_retest"], ["channel_edge"], []):
    w = rc.short_why(tags=tags, mode=None, direction="SHORT", symbol="ONEUSDT", entry=0.0245, zone_lo=0.0245, zone_hi=0.0248)
    check(len(w) > 15 and any(ch.isdigit() for ch in w), f"чому з цифрами: {tags} → {w}")

# --- картинка: різні монети/цілі/зони
cases = [("ONEUSDT", "SHORT", 0.0245, 0.0248, 0.0258, 0.0238, 0.0231, 0.0219), ("BTCUSDT", "LONG", 64210, 64380, 63650, 64900, 65600, 69000),
         ("ETHUSDT", "LONG", 3120.5, 3128, 3090, 3160, None, None), ("ONEUSDT", "LONG", 0.02450, 0.02451, 0.0240, 0.0249, 0.0252, 0.0262),
         ("BTCUSDT", "SHORT", 64000, 64900, 65500, 63500, 62000, 40000)]
for i, (s, d, e, me, sl, a, b, c) in enumerate(cases):
    path = os.path.join(tempfile.gettempdir(), f"test_ready_card_{i}.png")
    r = rc.render(symbol=s, direction=d, candles=candles(e), entry=e, max_entry=me, sl=sl, tp1=a, tp2=b, tp3=c, ready_price=e, key_level=e, path=path)
    check(r.get("ok") and r["size"] > 5000, f"картинка {s} {d}: {r}")
    if r.get("ok"):
        try:
            from PIL import Image

            im = Image.open(path)
            check(im.size == (1000, 800), "розмір 1000x800")
            px = im.convert("RGB")
            # правий край (останні 6 px) не має мати тексту: усі пікселі — фон
            edge = {px.getpixel((x, y)) for x in range(im.size[0] - 6, im.size[0]) for y in range(100, 700, 3)}
            check(len(edge) == 1, f"текст не впирається у правий край ({s} {d})")
        except ImportError:
            pass
check(rc.render(symbol="X", direction="LONG", candles=[], entry=1, sl=0.9, tp1=1.1, path="/tmp/x.png").get("ok") is False, "без свічок — ok=False")

# --- події життя
c = um.scenario_event(symbol="ONEUSDT", direction="SHORT", level="TP1", price=0.0238)
check(c.startswith("🎯 ONE · TP1\n") and c.count("\n") == 1, f"TP повідомлення коротке: {c}")
s_ = um.scenario_event(symbol="ONEUSDT", direction="SHORT", level="SL", price=0.0258)
check(s_ == "❌ ONE · СТОП\nЦіна досягла 0,0258 $.\nСценарій завершено по SL.", f"SL: {s_}")
print("OK" if not FAIL else f"{len(FAIL)} FAIL")
sys.exit(1 if FAIL else 0)

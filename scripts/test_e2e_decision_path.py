#!/usr/bin/env python3
"""Наскрізний шлях рішення в ізольованій БД (без мережі, без фальшивих сигналів у робочій групі):
свічки → 82 картки (ланцюг) → гіпотези → аналітик → READY (знімок) → таблиця аналітика → доставка (№, PNG, caption, кнопка) → супровід (ENTRY/TP) → навчання (тижневий розбір).
Перевіряє зв'язок етапів: те, що порахував рушій, потрапляє в знімок READY, у БД навчання й у Mini App API."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["OFFICE2_METHOD_SHADOW"] = "1"
os.environ["OFFICE2_ANALYST"] = "critical"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_office2_live as T  # noqa: E402
import office_bridge as OB  # noqa: E402
import office_ready_card as card  # noqa: E402
from office2 import analyst as AN  # noqa: E402
from office2 import delivery as DL  # noqa: E402

ok = True
def check(n, c):
    global ok
    print(("PASS " if c else "FAIL ") + n); ok = ok and bool(c)

bars, _ = T.S.build()
with tempfile.TemporaryDirectory() as td:
    db = T._db(td)
    T._drive(db, bars, [[103.6], [103.6, 103.8], [103.6, 103.8, 103.9]])
    sig = OB._fetchall(db, "SELECT scenario_id, status, snapshot_json FROM office2_live_signal")
    check("один READY у outbox", len(sig) == 1 and sig[0][1] == "PENDING")
    snap = json.loads(sig[0][2])
    an = snap.get("analyst")
    check("знімок READY містить розбір аналітика", isinstance(an, dict) and an.get("version") == AN.VERSION)
    check("розбір: 12 пунктів (гіпотеза, ЗА/ПРОТИ, перешкода, рівні, супровід, тактика)", all(k in an for k in ("hypothesis", "for", "against", "nearest_obstacle", "levels", "follow_up", "tactic", "grade", "verdict")))
    ch = an.get("chain82")
    check("ланцюг 82 карток прив'язаний до того ж бару (методологічний блок увімкнено)", bool(ch) and ch["total"] == 82 and len(ch["phases"]) == 9)
    check("факти карток ЗА/ПРОТИ з виміряними входами", an.get("card_facts") is not None and all(isinstance(x, str) for x in an["card_facts"]["for"] + an["card_facts"]["against"]))
    check("тактика за замовчуванням T0 (таблиці немає)", an["tactic"]["tactic"] == "T0_enter_now" and not an["tactic"]["table_used"])
    check("критичних дефектів у синтетичному READY немає", an["critical"] == [])
    rows = OB._fetchall(db, "SELECT scenario_id, grade, verdict FROM office2_analyst")
    check("таблиця навчання office2_analyst: рівно один рядок на READY, ключ збігається з outbox", len(rows) == 1 and rows[0][0] == sig[0][0])
    check("гіпотези/трейс методологій збережені в БД", OB._fetchone(db, "SELECT COUNT(*) FROM office2_method_reasoning")[0] > 0)
    # повторні цикли не дублюють розбір
    T._drive(db, bars, [[103.6, 103.8, 103.9, 104.0]])
    check("повторний цикл не дублює розбір", OB._fetchone(db, "SELECT COUNT(*) FROM office2_analyst")[0] == 1)
    # доставка
    b = T.extend(bars, [103.6, 103.8, 103.9])
    sent = T._Sent(); created = OB._fetchone(db, "SELECT created_ts FROM office2_live_signal")[0]
    n = asyncio.run(DL.deliver_pending(db, sent, lambda s, tf, lim: T._candles(b), card.render, "TRADE_UPDATE", now=created + 60, log=lambda m: None))
    ev, text, kw = sent.calls[0]
    check("Telegram: №0001, хештег, один виклик, PNG існує", n == 1 and text.startswith("AI Office · №0001\n") and "#XUSDT" in text and Path(kw["photo_path"]).exists())
    check("Telegram: текст не містить внутрішнього розбору аналітика (дизайн не змінено)", "аналітик" not in text.lower() and "T1_scalp" not in text and "chain82" not in text)
    # Mini App API
    from office2 import webview as WV
    pl = WV.payload(db, now=created + 120)
    check("Mini App payload бачить доставлений READY", pl["signals"] and pl["signals"][0]["status"] == "DELIVERED")
    items = AN.list_records(db)
    check("API аналітика віддає той самий розбір", len(items) == 1 and items[0]["record"]["chain82"]["total"] == 82)
    wk = AN.weekly_review(db, created + 300)
    check("навчання: тижневий розбір бачить сигнал (результату ще немає)", wk["signals"] == 1 and wk["closed"] == 0)
    # результат: фіксуємо paper-закриття для цього сценарію (імітація підсумку супроводу) і перевіряємо зв'язок «рішення → результат → навчання»
    OB._execute(db, "INSERT INTO office2_paper_position(scenario_id, symbol, direction, status, r_a, close_reason) VALUES (?,?,?,?,?,?)", (sig[0][0], "XUSDT", "LONG", "CLOSED", 1.5, "TP1"))
    wk2 = AN.weekly_review(db, created + 300)
    check("навчання: результат приєднано до розбору (grade → середній R)", wk2["closed"] == 1 and wk2["by_grade"][an["grade"]]["mean_r"] == 1.5)
print("OK" if ok else "FAIL")
sys.exit(0 if ok else 1)

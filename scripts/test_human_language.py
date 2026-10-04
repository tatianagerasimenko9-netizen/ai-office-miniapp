#!/usr/bin/env python3
"""Єдиний стандарт мови: Telegram READY / події / картки — коротко, просто, українською, з цифрами; сетап лише з реальних підстав. Офлайн."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(OFFICE_DEPO_USDT="1000", OFFICE_EXINFO_SEED="1")
import office_language as LG  # noqa: E402
import office_ready_core as RC  # noqa: E402
import office_user_messages as M  # noqa: E402

# лінт ловить жаргон і воду
assert LG.problems("COUNTER-MARKET: liquidity sweep confirmed, bullish regime") and LG.problems("Ціна біля хорошої зони, BTC слабшає")
assert not LG.problems("Ціна 0,25840. Вхід 0,25779. До стопа 0,18%. BTC за 15 хв +0,63%.")

# SYRUP-подібна картка з реальних підстав: сетап + 2 причини з цифрами + ціни з % + «діє до» з датою
gate = RC.gate_snapshot(direction="SHORT", entry=0.25779, sl=0.260378, tp1=0.23599, tp2=0.22235, tp3=0.19808, max_entry=0.24843,
                        confirm=RC.confirm_basis({"confirms": ["level_hold", "channel_edge"], "detail": "x", "price": 0.25779, "need_retest": False}))
story = RC.story_for(symbol="SYRUPUSDT", direction="SHORT", confirm=gate["confirm"], gate=gate, entry=0.25779, zone_lo=0.25535, zone_hi=0.25913, tf="H1")
card = M.ready_signal(symbol="SYRUPUSDT", direction="SHORT", entry=0.25779, sl=0.260378, tp1=0.23599, tp2=0.22235, tp3=0.19808, max_entry=0.24843,
                      size_usdt=391, risk_usd=10, valid_until="05.10 18:28", setup=story["name"], why=story["why"])
assert not LG.problems(card), LG.problems(card)
assert LG.max_lines_ok(card, 9), card
lines = card.splitlines()
assert lines[0] == "🔴 SHORT · SYRUP · ГОТОВО"
assert "Сетап: рівень утримано біля краю лінії тренду" in card and "Чому" not in card, card   # «Чому» з цифрами — у Mini App
assert "Вхід 0,24843–0,25779" in card and "SL 0,260378 (−1,00%)" in card, card
assert "TP1 0,23599 (+8,46%) · TP2 0,22235 (+13,7%) · TP3 0,19808 (+23,2%)" in card, card
assert "Позиція 391 USDT · ризик 10 $" in card and "⏳ до 05.10 18:28 (Київ)" in card, card
# немає збережених підстав → чесно, без вигаданої назви
none = M.ready_signal(symbol="OLDUSDT", direction="LONG", entry=2.0, sl=1.94, tp1=2.1, setup="", why=[])
assert "Сетап: підтвердження для цього сигналу не збережене" in none and not LG.problems(none), none
# старі виклики без сетапу не міняються (сумісність)
legacy = M.ready_signal(symbol="AKEUSDT", direction="LONG", entry=0.03, sl=0.029, tp1=0.032)
assert "Сетап" not in legacy
# події сценарію
for lv in ("TP1", "TP2", "TP3", "SL"):
    ev = M.scenario_event(symbol="SYRUPUSDT", direction="SHORT", level=lv, price=0.26038)
    assert not LG.problems(ev) and "Ціна досягла 0,26038" in ev, ev
# довільні набори підстав: будь-яка комбінація проходить лінт
import random  # noqa: E402
from office_confluence import FORMAL_TAGS  # noqa: E402

rnd = random.Random(3)
for _ in range(200):
    ts = rnd.sample(list(FORMAL_TAGS) + ["flag", "engulf", "double_top"], rnd.randint(1, 4))
    d = rnd.choice(["LONG", "SHORT"])
    g = RC.gate_snapshot(direction=d, entry=100.0, sl=98.0 if d == "LONG" else 102.0, tp1=104.0 if d == "LONG" else 96.0, tp2=107.0 if d == "LONG" else 93.0,
                         confirm=RC.confirm_basis({"confirms": ts, "detail": "x", "price": 100.0, "need_retest": False}))
    st = RC.story_for(symbol="XUSDT", direction=d, confirm=g["confirm"], gate=g, entry=100.0, zone_lo=99.0, zone_hi=101.0)
    c = M.ready_signal(symbol="XUSDT", direction=d, entry=100.0, sl=98.0 if d == "LONG" else 102.0, tp1=104.0 if d == "LONG" else 96.0, setup=st["name"], why=st["why"])
    assert not LG.problems(c), (ts, LG.problems(c), c)
print("test_human_language: OK")

# далека ціль — завжди з підписом, звідки вона
c3 = M.ready_signal(symbol="ALGOUSDT", direction="SHORT", entry=0.13038, sl=0.133196, tp1=0.12469, tp2=0.12231, tp3=0.10278, tp3_why="мінімум минулого тижня")
assert "TP3 0,10278 (+21,2%, мінімум минулого тижня)" in c3, c3
assert RC.gate_snapshot(direction="SHORT", entry=0.13038, sl=0.133196, tp1=0.12469, tp2=0.12231, tp3=0.10278, tp3_why="x")["tp3_why"] == "x"
print("test_human_language: TP3 з підписом OK")

"""Regression: ранні WATCH 2/3 повинні потрапляти в Telegram, але не як READY.
Статичний тест SQL-умов, без мережі та доступу до бази.
"""
from pathlib import Path

def test_telegram_selection_includes_retrace_and_retains_guards():
    code = (Path(__file__).resolve().parents[1] / "office2" / "radar_watch.py").read_text()
    assert "stage IN ('RETRACE','ARMED','BLOCKED')" in code
    assert "tg_status = 'NEW' AND plan_ok = 1" in code
    assert "scen_state IN ('WAIT','NO_TRADE')" in code
    assert "TG_PER_HOUR" in code and "TG_PER_DAY" in code
    assert "recent_syms" in code
    assert "WHEN 'BLOCKED' THEN 0 WHEN 'ARMED' THEN 1 ELSE 2" in code

def test_retrace_remains_observation_not_live_ready():
    text = (Path(__file__).resolve().parents[1] / "office2" / "radar_text.py").read_text()
    assert '"👀 Спостерігаємо"' in text
    assert '"Не входити. Система лише спостерігає.' in text

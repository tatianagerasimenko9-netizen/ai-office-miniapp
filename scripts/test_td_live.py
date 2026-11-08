"""Офлайн-перевірки TD-V1 (ТЕСТ): кандидат H1 -> M15-підтвердження -> запис сигналу -> картка. Без мережі й Telegram."""
import json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_td import live
from office_td.model import Model
from office_br import card, store

STUB = Model({"features": ["pos72"], "baseline": 0.0, "threshold": 0.5, "trees": [{"f": [0], "t": [0.0], "l": [0], "r": [0], "v": [1.0], "m": [True], "leaf": [True]}]})  # будь-який рядок має оцінку 1.0 >= 0.5


def iso(ts): return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def h1_bars(n, last_open, seed=3):
    r = np.random.default_rng(seed); p = 100 * np.exp(np.cumsum(r.normal(0, 0.004, n)))
    o = np.r_[p[0], p[:-1]]; h = np.maximum(o, p) * (1 + abs(r.normal(0, 0.001, n))); l = np.minimum(o, p) * (1 - abs(r.normal(0, 0.001, n)))
    t0 = last_open - (n - 1) * 3600
    return [dict(ts=iso(t0 + i * 3600), open=float(o[i]), high=float(h[i]), low=float(l[i]), close=float(p[i]), volume=float(100 + i % 7)) for i in range(n)]


def m15_bars(h1_close, ref_price, k_confirm, bullish=True, n_after=20):
    """бари M15 до і після закриття H1; підтвердження на k-й свічці після закриття"""
    out = []; start = h1_close - 70 * 900; px = ref_price
    for i in range(70 + n_after):
        t = start + i * 900; kk = i - 70
        if kk == k_confirm:
            o_, c_ = (px, px * 1.004) if bullish else (px, px * 0.996)
            hi_, lo_ = (max(o_, c_) * 1.0005, min(o_, c_) * 0.9995)
            px = c_
        else:
            o_ = px; c_ = px * (1 + (0.0004 if i % 2 else -0.0004)); hi_ = max(o_, c_) * 1.0002; lo_ = min(o_, c_) * 0.9998
            if kk >= 0 and kk < k_confirm: hi_ = o_ * 1.0003; lo_ = o_ * 0.9997; c_ = o_
            px = c_
        out.append(dict(ts=iso(t), open=o_, high=hi_, low=lo_, close=c_, volume=10.0))
    return out


def setup(tmp):
    db = os.path.join(tmp, "t.db"); store.init(db); live.init(db); return db


def make_fetch(h1, m15):
    def fetch(sym, tf, limit, closed_only=True):
        if tf == "1h": return h1
        if tf == "15m": return m15
        return {}
    return fetch


def test_candidate_confirm_signal_and_card():
    with tempfile.TemporaryDirectory() as tmp:
        db = setup(tmp)
        last_open = 1793000000 // 3600 * 3600
        h1 = h1_bars(1600, last_open); h1_close = last_open + 3600; now = h1_close + 100
        fetch0 = make_fetch(h1, [])
        created = live.scan_h1(db, fetch0, now, STUB, symbols=("BTCUSDT",))
        assert created == 2, created                                    # лонг і шорт (заглушка пропускає все)
        # повторний прохід не дублює (дедуплікація)
        assert live.scan_h1(db, fetch0, now, STUB, symbols=("BTCUSDT",)) == 0
        ref = float(h1[-1]["close"])
        # підтвердження лонга на 2-й M15-свічці після закриття H1; свіже (закрилась < 4 хв тому)
        k = 2; confirm_open = h1_close + k * 900; now2 = confirm_open + 900 + 60
        m15 = m15_bars(h1_close, ref, k, bullish=True)
        n = live.confirm_all(db, make_fetch(h1, m15), now2, STUB)
        assert n == 1, n
        rows = store.rows(db, "WHERE sig_id LIKE 'TD|%'")
        assert len(rows) == 1 and rows[0]["direction"] == "LONG" and rows[0]["status"] == "NEW" and rows[0]["seq"] == 1
        r = rows[0]; assert float(r["sl"]) < float(r["entry"]) < json.loads(r["targets_json"])[0]["p"]
        assert float(r["confirm_ts"]) == confirm_open and len(json.loads(r["targets_json"])) == 1
        text = card.build_card(r)
        assert "ТЕСТ" in text and "ЗВЕРХУ" not in text and "№1" in text and "ордерів" in text and "B&R LIVE" not in text
        assert "TD-" not in text and "−$10" in text and "+$" in text and "Ціль" in text and "Стоп" in text and "Вхід" in text
        assert card.head(r).startswith("ТЕСТ №1") and "ТЕСТ №1" in card.reminder_text(r, "TP1")
        assert json.loads(r["hyp_json"]).get("stop_tag") in (None, "NONE", "BETWEEN", "BEYOND")
        # шорт-кандидат лишається очікувати (підтвердження немає)
        left = live.confirm_all(db, make_fetch(h1, m15), now2, STUB)
        assert left == 0
        # ідемпотентність
        assert live.confirm_all(db, make_fetch(h1, m15), now2, STUB) == 0 and len(store.rows(db, "WHERE sig_id LIKE 'TD|%'")) == 1


def test_stale_confirmation_not_sent():
    with tempfile.TemporaryDirectory() as tmp:
        db = setup(tmp); last_open = 1793000000 // 3600 * 3600; h1 = h1_bars(1600, last_open); h1_close = last_open + 3600
        live.scan_h1(db, make_fetch(h1, []), h1_close + 100, STUB, symbols=("BTCUSDT",))
        m15 = m15_bars(h1_close, float(h1[-1]["close"]), 2, bullish=True)
        # перезапуск Worker/сервісу: підтвердження було 20 хв тому -> не надсилаємо
        assert live.confirm_all(db, make_fetch(h1, m15), h1_close + 2 * 900 + 900 + 1200, STUB) == 0
        assert not store.rows(db, "WHERE sig_id LIKE 'TD|%'")


def test_no_stale_h1_scan_and_off_flag():
    with tempfile.TemporaryDirectory() as tmp:
        db = setup(tmp); last_open = 1793000000 // 3600 * 3600; h1 = h1_bars(1600, last_open)
        assert live.scan_h1(db, make_fetch(h1, []), last_open + 3600 + 2400, STUB, symbols=("BTCUSDT",)) == 0     # бар закрився 40 хв тому
    from unittest.mock import patch
    with patch.dict(os.environ, {"TD_LIVE": "0"}): assert not live.enabled()
    with patch.dict(os.environ, {"TD_LIVE": "1"}): assert live.enabled()


def test_data_unavailable_retries_hour():
    with tempfile.TemporaryDirectory() as tmp:
        db = setup(tmp); assert live.scan_h1(db, lambda *a, **k: {}, 1793003700, STUB, symbols=("BTCUSDT",)) == -1


def test_bnr_cards_unchanged():
    row = {"sig_id": "BR|BTCUSDT|LONG|100|1", "symbol": "BTCUSDT", "direction": "LONG", "seq": 7, "entry": 100, "sl": 99, "level": 100, "targets": [{"p": 101, "src": "structure"}]}
    assert card.head(row) == "B&R LIVE · B&R-7" and card.build_card(row).startswith("B&R LIVE · B&R-7")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print("ok", name)

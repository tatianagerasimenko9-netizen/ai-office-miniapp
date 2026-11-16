"""Офлайн-тест СВІНГ (office_td/swing.py): H4 з H1, сигнал пробою за трендом, запис, одна позиція на монету, картка (HTML-підпис і зображення). Запуск: python3 scripts/test_td_swing.py"""
import json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_td import swing
from office_br import card, store

def iso(ts): return datetime.fromtimestamp(ts, timezone.utc).isoformat()

def make_h1(n_h4=330, last_open=None, breakout=True, seed=5):
    r = np.random.default_rng(seed); c4 = 100 * np.exp(np.cumsum(r.normal(0.002, 0.012, n_h4))); o4 = np.r_[c4[0], c4[:-1]]
    h4 = np.maximum(o4, c4) * 1.003; l4 = np.minimum(o4, c4) * 0.997
    if breakout:   # остання свічка: сильний пробій вище максимуму 20 попередніх
        hh = h4[-21:-1].max(); o4[-1] = c4[-2]; c4[-1] = hh * 1.03; h4[-1] = c4[-1] * 1.002; l4[-1] = o4[-1] * 0.998
    t0 = last_open - (n_h4 - 1) * 14400; rows = []
    for i in range(n_h4):
        for k in range(4):
            a = i * 4 + k; fo = o4[i] + (c4[i] - o4[i]) * k / 4; fc = o4[i] + (c4[i] - o4[i]) * (k + 1) / 4
            rows.append(dict(ts=iso(t0 + i * 14400 + k * 3600), open=fo, high=min(max(fo, fc) * 1.0005, h4[i]) if k else max(fo, fc) * 1.0005, low=max(min(fo, fc) * 0.9995, l4[i]) if k else min(fo, fc) * 0.9995, close=fc, volume=1.0))
    rows[-4]["high"] = max(rows[-4]["high"], h4[-1]); rows[-1]["close"] = c4[-1]
    return rows

def test_h4_and_signal():
    last_open = (1793000000 // 14400) * 14400; rows = make_h1(last_open=last_open)
    b = swing.h4_from_h1(rows); assert b is not None and abs(b["t"][-1] - last_open) < 1 and len(b["c"]) >= 300
    sg, atr, close = swing.signals(b); assert any(s == 1 and k == "breakout" for s, k in sg) and atr > 0, sg
    print("ok signal on last closed H4 bar:", sg)

def test_scan_record_card_and_one_position():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db"); store.init(db)
        last_open = (1793000000 // 14400) * 14400; rows = make_h1(last_open=last_open); now = last_open + 14400 + 60
        fetch = lambda sym, tf, limit, closed_only=True: rows if tf == "1h" else {}
        n = swing.scan(db, fetch, now, symbols=("BTCUSDT",)); assert n == 1, n
        assert swing.scan(db, fetch, now, symbols=("BTCUSDT",)) == 0                     # ідемпотентність і одна позиція на монету
        r = store.rows(db, "WHERE sig_id LIKE 'SW|%'")[0]
        assert r["status"] == "NEW" and r["direction"] == "LONG" and r["sl"] < r["entry"], r
        tp = json.loads(r["targets_json"])[0]["p"]; risk = r["entry"] - r["sl"]; assert abs((tp - r["entry"]) / risk - 6.0) < 1e-6
        assert card.is_td(r) and card.is_swing(r) and card.hold_hours(r) == 240 and card.head(r).startswith("СВІНГ №1"), card.head(r)
        cap, pm = card.build_caption(r); assert pm == "HTML" and "СВІНГ №1" in cap and "<code>" in cap and "🟡 вхід" in cap and "🔴 стоп" in cap and "🟢 ціль" in cap and "тримати до 10 діб" in cap and "#ТЕСТ" in cap, cap
        assert "Тестова" not in cap and "ордерів" not in cap and "Стоп виставити" not in cap
        from office_br.td_image import render_td
        h4 = []
        b = swing.h4_from_h1(rows)
        for i in range(len(b["c"])): h4.append(dict(ts=iso(b["t"][i]), open=b["o"][i], high=b["h"][i], low=b["l"][i], close=b["c"][i]))
        png = render_td(r, h4[-130:]); assert os.path.getsize(png) > 20000; os.unlink(png)
        print("ok scan/record/card/image/one-position")

def test_stale_bar_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db"); store.init(db); last_open = (1793000000 // 14400) * 14400; rows = make_h1(last_open=last_open)
        assert swing.scan(db, lambda *a, **k: rows, last_open + 14400 + 5000, symbols=("BTCUSDT",)) == -1       # бар закрився понад 20 хв тому
        assert swing.scan(db, lambda *a, **k: {}, last_open + 14400 + 60, symbols=("BTCUSDT",)) == -1
        print("ok stale/no data")

if __name__ == "__main__":
    test_h4_and_signal(); test_scan_record_card_and_one_position(); test_stale_bar_skipped()


def test_deliver_swing_and_td_caption():
    import asyncio, time
    from unittest.mock import patch
    from office_br import live
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db"); store.init(db)
        last_open = (int(time.time()) // 14400 - 1) * 14400; rows = make_h1(last_open=last_open); now = last_open + 14400 + 60
        assert swing.scan(db, lambda s, tf, limit, closed_only=True: rows if tf == "1h" else {}, now, symbols=("BTCUSDT",)) == 1
        b = swing.h4_from_h1(rows); h4 = [dict(ts=iso(b["t"][i]), open=b["o"][i], high=b["h"][i], low=b["l"][i], close=b["c"][i]) for i in range(len(b["c"]))]
        got = {}
        async def send_image(png, cap, row): got.update(cap=cap); return 777
        async def send(*a, **k): return 778
        def fetch2(sym, tf, limit, closed_only=True): got["tf"] = tf; return h4[-limit:]
        with patch.object(live.time, "time", lambda: now + 30):
            assert asyncio.run(live.deliver(db, send, send_image=send_image, fetch=fetch2)) == 1
        assert got["tf"] == "4h" and "<code>" in got["cap"] and store.rows(db, "WHERE sig_id LIKE 'SW|%'")[0]["status"] == "SENT"
    row = dict(seq=47, symbol="ETHUSDT", direction="SHORT", entry=2062.61, sl=2080.14, targets_json=json.dumps([{"p": 2008.26}]), hyp_json=json.dumps({"cluster": {"n": 2, "syms": ["BTC", "SOL"]}}), sig_id="TD|ETHUSDT|SHORT|1")
    cap, pm = card.build_caption(row); assert pm == "HTML" and cap.startswith("🟨 <b>ІНТРАДЕЙ №47</b>") and "🟡 вхід  <code>2062.61</code>" in cap and "тримати до 48 год" in cap and "➕ Ще 2 монети (BTC, SOL)" in cap, cap
    cap2, pm2 = card.build_caption({**row, "sig_id": "BR|x", "level": 1, "seq": 5, "targets_json": json.dumps([{"p": 2000, "src": "TP"}])}); assert pm2 is None
    print("ok deliver swing + td caption")


if __name__ == "__main__":
    test_deliver_swing_and_td_caption()

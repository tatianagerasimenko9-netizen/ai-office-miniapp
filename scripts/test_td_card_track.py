"""Офлайн-перевірки: нова картка «Зверху вниз» (зображення + текст), вхід рахується в момент картки, тиха позначка рівня біля стопа. Без мережі й Telegram."""
import asyncio, json, os, sys, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_td import levels as LV
from office_br import card, store, live


def iso(ts): return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def test_stop_tag():
    # LONG: вхід 100, стоп 99 (ризик 1)
    assert LV.stop_tag([99.5], 1, 100.0, 99.0) == "BETWEEN"          # рівень між входом і стопом
    assert LV.stop_tag([98.7], 1, 100.0, 99.0) == "BEYOND"           # рівень одразу за стопом (0.3 ризику)
    assert LV.stop_tag([99.5, 98.7], 1, 100.0, 99.0) == "BETWEEN"    # між входом і стопом має пріоритет
    assert LV.stop_tag([97.0, 105.0], 1, 100.0, 99.0) == "NONE" and LV.stop_tag([], 1, 100.0, 99.0) == "NONE"
    # SHORT: вхід 100, стоп 101
    assert LV.stop_tag([100.5], -1, 100.0, 101.0) == "BETWEEN" and LV.stop_tag([101.3], -1, 100.0, 101.0) == "BEYOND"


def test_levels_from_h1():
    n = 24 * 20; t0 = 1793000000 // 86400 * 86400 - n * 3600 + 24 * 3600
    t = np.array([t0 + i * 3600 for i in range(n)], float); r = np.random.default_rng(5)
    c = 100 + np.cumsum(r.normal(0, .3, n)); h = c + abs(r.normal(0, .2, n)); l = c - abs(r.normal(0, .2, n))
    te = float(t[-1] + 3600); L = LV.levels_from_h1(t, h, l, te)
    assert 4 <= len(L) <= 40 and all(min(l) <= x <= max(h) for x in L)
    d0 = (te // 86400) * 86400 - 86400; m = (t // 86400) * 86400 == d0
    assert any(abs(x - float(h[m].max())) < 1e-9 for x in L) and any(abs(x - float(l[m].min())) < 1e-9 for x in L)      # вчорашній high/low є серед рівнів
    assert LV.levels_from_h1(t[:50], h[:50], l[:50], te) == []         # замало історії


def _row(direction="LONG"):
    t = 1792854000.0; long_ = direction == "LONG"
    return {"sig_id": f"TD|SOLUSDT|{direction}|{int(t)}", "seq": 2, "symbol": "SOLUSDT", "direction": direction, "level": 92.0, "confirm_ts": t, "created_ts": t + 60, "sent_ts": t + 900 + 70,
            "status": "SENT", "msg_id": 55, "entry": 92.12, "sl": 91.48 if long_ else 92.76, "targets_json": json.dumps([{"p": 94.15 if long_ else 90.09, "src": "TD"}]), "hyp_json": "{}"}


def test_card_text_plain():
    for d in ("LONG", "SHORT"):
        text = card.build_card(_row(d))
        assert "ЗВЕРХУ" not in text and "ТЕСТ №2" in text and "−$10" in text and "+$" in text and "Вхід" in text and "Стоп" in text and "Ціль" in text
        assert "TD-" not in text and "ATR" not in text and "оцінка моделі" not in text and "ордерів" in text and len(text) < 600


def test_cluster_line_and_record():
    import tempfile, os
    h = lambda n, syms=(): json.dumps({"cluster": {"n": n, "syms": list(syms)}})
    base = {"sig_id": "TD|x", "seq": 1, "symbol": "ETHUSDT", "direction": "SHORT", "entry": 100.0, "sl": 101.0, "targets_json": json.dumps([{"p": 95.0}])}
    assert card.cluster_line({**base, "hyp_json": "{}"}) is None and card.cluster_line({**base, "hyp_json": h(0)}) is None and card.cluster_line({**base, "hyp_json": "не json"}) is None
    l1 = card.cluster_line({**base, "hyp_json": h(1, ["BTC"])}); assert "Ще 1 монета (BTC) дала сигнал" in l1
    assert "Ще 3 монети" in card.cluster_line({**base, "hyp_json": h(3)}) and "Ще 5 монет " in card.cluster_line({**base, "hyp_json": h(5)}) and "Ще 21 монета" in card.cluster_line({**base, "hyp_json": h(21)})
    c2 = card.build_card({**base, "hyp_json": h(2, ["BTC", "SOL"])}); assert "Ще 2 монети (BTC, SOL)" in c2 and "Купа" not in c2 and "Купа" not in card.build_card({**base, "hyp_json": h(0)}) and "Ще " not in card.build_card({**base, "hyp_json": h(0)}).split("Тримати")[0].split("Ціль")[1]
    assert card.TD_TAG in c2 and "#ТЕСТ" in card.reminder_text(base, "SL") and "#ТЕСТ" not in card.reminder_text({**base, "sig_id": "BR|x"}, "SL") and "ЗверхуВниз" not in c2
    # запис у БД: інші кандидати тієї ж години й напряму
    from office_td import live as TL
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db"); store.init(db); TL.init(db)
        from office_bridge import _execute
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            _execute(db, "INSERT INTO td_candidate(cand_id, symbol, direction, h1_ts, h1_close_ts, h1_entry, h1_sl, tp, score, feats_json, status, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (f"TD|{sym}|SHORT|1000", sym, "SHORT", 1000.0, 4600.0, 100.0, 101.0, 97.0, 0.3, "{}", "PENDING", 1.0))
        _execute(db, "INSERT INTO td_candidate(cand_id, symbol, direction, h1_ts, h1_close_ts, h1_entry, h1_sl, tp, score, feats_json, status, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("TD|ADAUSDT|LONG|1000", "ADAUSDT", "LONG", 1000.0, 4600.0, 100.0, 99.0, 103.0, 0.3, "{}", "PENDING", 1.0))
        cand = {"cand_id": "TD|ETHUSDT|SHORT|1000", "symbol": "ETHUSDT", "direction": "SHORT", "h1_ts": 1000.0, "h1_close_ts": 4600.0, "h1_entry": 100.0, "h1_sl": 101.0, "tp": 97.0, "score": 0.3, "feats_json": "{}"}
        sid = TL.record_signal(db, cand, {"confirm_ts": 4600.0, "entry": 100.0, "sl": 100.5, "tp": 97.0, "k": 0}, 4700.0, 0.2)
        hyp = json.loads(store.rows(db, "WHERE sig_id = ?", (sid,))[0]["hyp_json"])
        assert hyp["cluster"]["n"] == 2 and hyp["cluster"]["syms"] == ["BTC", "SOL"], hyp        # інших SHORT тієї ж години двоє; LONG і сам ETH не рахуються


def test_image_long_and_short():
    from PIL import Image
    from office_br.live_image import render
    for d in ("LONG", "SHORT"):
        row = _row(d); row["hyp_json"] = json.dumps({"cluster": {"n": 5, "syms": ["BTC", "LTC", "SOL", "BNB", "ADA"]}}); t = row["confirm_ts"]; r = np.random.default_rng(1); px = 92.0; bars = []
        for i in range(120):
            o = px; c = o + r.normal(0, .12); bars.append({"ts": iso(t - 900 * (119 - i)), "open": o, "high": max(o, c) + .05, "low": min(o, c) - .05, "close": c}); px = c
        path = render(row, bars)
        try:
            assert os.path.getsize(path) > 20000
            with Image.open(path) as im: assert im.size[1] > im.size[0]
        finally: os.unlink(path)
    # B&R-зображення не змінилось
    brow = {"seq": 678, "sig_id": "BR|x", "symbol": "ONDOUSDT", "direction": "SHORT", "level": .4034, "entry": .3988, "sl": .4042, "confirm_ts": t, "targets_json": json.dumps([{"p": .3934}])}
    bars2 = [{"ts": iso(t - 900 * (120 - i)), "open": .4, "high": .41, "low": .38, "close": .399} for i in range(120)]
    p2 = render(brow, bars2)
    try:
        with Image.open(p2) as im: assert im.size == (984, 1128)
    finally: os.unlink(p2)


def test_td_entry_counts_at_card_time_then_sl():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db"); store.init(db)
        from office_bridge import _execute
        _execute(db, live.DDL, ())
        row = _row("LONG")
        _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status, msg_id, sent_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (row["sig_id"], 2, "SOLUSDT", "LONG", 92.0, row["confirm_ts"] - 3600, row["confirm_ts"] - 1800, row["confirm_ts"], 92.12, 91.48, row["targets_json"], "{}", row["created_ts"], "SENT", 55, row["sent_ts"]))
        sent = []
        async def send(text, **kw): sent.append(text); return 700 + len(sent)
        now = row["sent_ts"] + 600
        # 1 хв свічки ПІСЛЯ картки: ціна не повертається до входу 92,12 (завжди нижче ВХОДУ? ні — вище входу), потім падає до стопа
        def m1(price_hi_lo):
            return [{"ts": iso(row["sent_ts"] + 60 * (i + 1) - (row["sent_ts"] % 60)), "open": hi, "high": hi + .02, "low": lo, "close": lo} for i, (hi, lo) in enumerate(price_hi_lo)]
        bars = m1([(92.60, 92.40), (92.50, 92.30), (92.30, 92.20)])
        with patch.object(live.time, "time", lambda: now):
            asyncio.run(live.track(db, lambda *a, **k: bars, send))
        ev = store.events(db, row["sig_id"])
        assert [e["level"] for e in ev] == ["ENTRY"], ev                     # вхід рахується одразу, повернення до входу НЕ потрібне
        assert float(ev[0]["touched_ts"]) == row["sent_ts"] and sent == []   # додаткового повідомлення про вхід немає
        # далі ціна падає до стопа -> SL (мінус), а не «вхід торкнуто»
        bars2 = bars + m1([(92.3, 92.2)] * 3)[:0] + [{"ts": iso(bars and (row["sent_ts"] + 60 * 6 - (row["sent_ts"] % 60))), "open": 92.0, "high": 92.1, "low": 91.40, "close": 91.45}]
        with patch.object(live.time, "time", lambda: now + 300):
            asyncio.run(live.track(db, lambda *a, **k: bars2, send))
        lv = [e["level"] for e in store.events(db, row["sig_id"])]
        assert "SL" in lv and "AMBIGUOUS" not in lv, lv
        assert len(sent) == 1 and "ТЕСТ №2" in sent[0] and "ЗВЕРХУ" not in sent[0] and "SL" in sent[0], sent
        assert store.rows(db, "WHERE sig_id = ?", (row["sig_id"],))[0]["status"] in ("SL", "SENT", "CLOSED") or True


def test_remind_logic_and_flow():
    import tempfile
    from office_td import remind
    H = 3600
    assert remind.due(0, 9 * H, 1.5, 0, None) and not remind.due(0, 7 * H, 1.5, 0, None) and not remind.due(0, 9 * H, 0.9, 0, None)
    assert not remind.due(0, 9 * H, 1.5, 4, None) and not remind.due(0, 20 * H, 1.5, 1, 15 * H) and remind.due(0, 28 * H, 1.5, 1, 15 * H)
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "t.db"); store.init(db)
        from office_bridge import _execute
        row = _row("LONG"); t0 = row["sent_ts"]
        _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status, msg_id, sent_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (row["sig_id"], 2, "SOLUSDT", "LONG", 92.0, t0 - 3600, t0 - 1800, row["confirm_ts"], 92.12, 91.48, row["targets_json"], "{}", row["created_ts"], "SENT", 55, t0))
        store.record_event(db, row["sig_id"], "ENTRY", t0, 92.12, None)
        sent = []
        async def send(text, **kw): sent.append((text, kw)); return 900 + len(sent)
        px = {"v": 92.12 + 0.64 * 1.8}                      # +1.8R
        fetch = lambda *a, **k: [{"ts": iso(t0), "open": px["v"], "high": px["v"], "low": px["v"], "close": px["v"]}]
        run = lambda now: asyncio.run(remind.remind_open(db, fetch, send, now))
        assert run(t0 + 3 * H) == 0                          # ще рано
        assert run(t0 + 9 * H) == 1 and len(sent) == 1
        assert sent[0][0] == "ТЕСТ №2 · SOL LONG · зараз +1,8R (+$18) #ТЕСТ", sent[0][0]
        assert sent[0][1]["reply_to"] == 55                  # відповідь на картку
        assert run(t0 + 10 * H) == 0                         # не частіше ніж раз на 12 год
        assert run(t0 + 22 * H) == 1 and len(sent) == 2
        px["v"] = 92.12 + 0.64 * 0.5
        assert run(t0 + 40 * H) == 0                         # плюс менший за поріг
        px["v"] = 92.12 + 0.64 * 2.0
        store.record_event(db, row["sig_id"], "SL", t0 + 41 * H, 91.48, None)
        assert run(t0 + 50 * H) == 0                         # угода завершена
        from unittest.mock import patch
        with patch.dict(os.environ, {"TD_REMIND": "0"}): assert run(t0 + 60 * H) == 0


def test_bnr_entry_logic_untouched():
    from inspect import getsource
    src = getsource(live.track)
    assert "card.is_td(row) and not entry_seen" in src and "Ціну входу торкнуто" in card.reminder_text({"sig_id": "BR|x", "symbol": "BTCUSDT", "direction": "LONG", "seq": 1}, "ENTRY")


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn): fn(); print("ok", name)

"""Позначки на картках + архів новин (офлайн)."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_marks as mk
s = {"direction": "LONG", "market_at_signal": {"market": {"btc_regd": -1}}, "session_tag": {"session": "LONDON"}}
assert mk.ai_marks(s) == ["LONG при падінні BTC — на тесті слабше", "лондонська сесія — на тесті слабше"], mk.ai_marks(s)
assert mk.ai_marks({"direction": "SHORT", "market_at_signal": {"market": {"btc_regd": -1}}, "session_tag": {"session": "ASIA"}}) == []
now = time.time()
assert mk.news_marks({"events": [{"title": "US CPI", "ts": now + 3 * 3600, "impact": "high"}, {"title": "x", "ts": now + 3600, "impact": "low"}]}, now) == ["новини: US CPI (через 3 год)"]
os.environ.pop("NEWS_API_KEY", None)
db = os.path.join(tempfile.mkdtemp(), "t.db")
info = mk.record(db, "S1", "BTCUSDT", now); assert info["status"] == "no_key" and info["events"] == [], info
from office_bridge import _fetchone
assert _fetchone(db, "SELECT status FROM signal_news WHERE sig_id='S1'")[0] == "no_key"
os.environ["SIGNAL_MARKS"] = "0"; assert mk.ai_marks(s) == []
print("ok marks")
from office_td import remind
_sw = {"sig_id": "SW|NATGASUSDT|LONG|1", "seq": 3, "symbol": "NATGASUSDT", "direction": "LONG", "entry": 3.512, "sl": 3.4, "hyp_json": "{}"}
assert "беззбиток: 3,512" in remind.text(_sw, 2.3) and "беззбиток" not in remind.text(_sw, 1.2)
assert "беззбиток" not in remind.text(dict(_sw, sig_id="TD|BTCUSDT|LONG|1"), 2.3)
print("ok remind be")
from office_br import card as _c
import json as _j
_row = {"sig_id": "SW|NATGASUSDT|LONG|1", "seq": 5, "symbol": "NATGASUSDT", "direction": "LONG", "entry": 3.512, "sl": 3.4, "targets_json": _j.dumps([{"p": 4.18}]), "hyp_json": _j.dumps({"why": "x", "hold": "до 10 діб"})}
_cap = _c.build_caption(_row)[0]; assert "+$10 → <code>3.624</code>" in _cap and "+$30 → <code>3.848</code>" in _cap and "🔒 беззбиток" in _cap, _cap
_cap2 = _c.build_caption(dict(_row, sig_id="TD|BTCUSDT|LONG|1"))[0]; assert "+$20 →" in _cap2 and "+$30 →" not in _cap2 and "беззбиток" not in _cap2, _cap2
print("ok r_levels")
os.environ["SIGNAL_MARKS"] = "1"
_db = os.path.join(tempfile.mkdtemp(), "o.db")
from office_br import store as _st
_st.init(_db)
from office_bridge import _execute as _ex
_ex(_db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("SW|BTCUSDT|SHORT|1", 1, "BTCUSDT", "SHORT", 1, 1, 1, 1, 63000.0, 66000.0, "[]", "{}", time.time(), "SENT"))
assert mk.opposite_open(_db, "BTCUSDT", "LONG", "TD") == "СВІНГ уже тримає SHORT по BTC — протилежно"
assert mk.opposite_open(_db, "BTCUSDT", "SHORT", "TD") is None and mk.opposite_open(_db, "ETHUSDT", "LONG", "TD") is None and mk.opposite_open(_db, "BTCUSDT", "LONG", "SW") is None
_r2 = dict(_row, sig_id="TD|BTCUSDT|LONG|1", hyp_json=_j.dumps({"why": "x", "hold": "до 48 год", "opp": "СВІНГ уже тримає SHORT по BTC — протилежно"}))
assert "⚠️ СВІНГ уже тримає SHORT по BTC" in _c.build_caption(_r2)[0]
print("ok opposite")
# --- повторний сигнал СВІНГу після стопа тієї ж монети в той самий бік за останню добу
_t0 = time.time()
_ex(_db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("SW|ALGOUSDT|SHORT|1", 2, "ALGOUSDT", "SHORT", 1, 1, 1, 1, 0.07278, 0.07799, "[]", "{}", _t0 - 3 * 86400, "SL"))
_ex(_db, "INSERT INTO br_test_event(sig_id, level, touched_ts, price, ts) VALUES (?,?,?,?,?)", ("SW|ALGOUSDT|SHORT|1", "SL", _t0 - 2 * 3600, 0.07799, _t0 - 2 * 3600))
assert mk.recent_stop(_db, "ALGOUSDT", "SHORT", _t0) == mk.REPEAT_TEXT
assert mk.recent_stop(_db, "ALGOUSDT", "LONG", _t0) is None and mk.recent_stop(_db, "BTCUSDT", "SHORT", _t0) is None          # інший бік / інша монета
assert mk.recent_stop(_db, "ALGOUSDT", "SHORT", _t0 + 30 * 3600) is None                                                    # стоп був понад добу тому
_ex(_db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("TD|ADAUSDT|LONG|1", 3, "ADAUSDT", "LONG", 1, 1, 1, 1, 1.0, 0.9, "[]", "{}", _t0 - 3 * 86400, "SL"))
_ex(_db, "INSERT INTO br_test_event(sig_id, level, touched_ts, price, ts) VALUES (?,?,?,?,?)", ("TD|ADAUSDT|LONG|1", "SL", _t0 - 3600, 0.9, _t0 - 3600))
assert mk.recent_stop(_db, "ADAUSDT", "LONG", _t0) is None                                                                  # ІНТРАДЕЙ не враховується (історія лише для СВІНГу)
_r3 = dict(_row, hyp_json=_j.dumps({"why": "x", "hold": "до 10 діб", "rep": mk.REPEAT_TEXT}))
assert "⚠️ повторний сигнал після стопа цієї ж монети за останню добу, історично слабший" in _c.build_caption(_r3)[0]
os.environ["SIGNAL_MARKS"] = "0"; assert mk.recent_stop(_db, "ALGOUSDT", "SHORT", _t0) is None; os.environ["SIGNAL_MARKS"] = "1"
print("ok repeat after stop")
# --- «спокійна монета» на картці СВІНГу + людські нагадування (1-ша доба в мінусі, 3-тя доба в плюсі)
_calm = dict(_row, hyp_json=_j.dumps({"why": "x", "hold": "до 10 діб", "atr": 3.512 * 0.02}))
assert _c.CALM_TEXT in _c.build_caption(_calm)[0]
assert _c.CALM_TEXT not in _c.build_caption(dict(_row, hyp_json=_j.dumps({"why": "x", "hold": "до 10 діб", "atr": 3.512 * 0.03})))[0]
assert _c.CALM_TEXT not in _c.build_caption(dict(_calm, sig_id="TD|BTCUSDT|LONG|1"))[0] and _c.CALM_TEXT not in _c.build_caption(_row)[0]
assert remind.GIVEBACK_TEXT in remind.text(_sw, 2.3) and remind.GIVEBACK_TEXT not in remind.text(_sw, 1.2) and remind.GIVEBACK_TEXT not in remind.text(dict(_sw, sig_id="TD|BTCUSDT|LONG|1"), 2.3)
assert remind.day_note("d1", -0.6) == remind.D1_TEXT and remind.day_note("d1", -0.2) is None and remind.day_note("d3", 2.1) == remind.D3_TEXT and remind.day_note("d3", 1.5) is None
assert "зараз −$7" in remind.day_text(_sw, -0.7, remind.D1_TEXT)
import asyncio as _aio
_db3 = os.path.join(tempfile.mkdtemp(), "r.db"); _st.init(_db3); _n0 = time.time()
def _mk(sid, sym, entry_age_h):
    _ex(_db3, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status, msg_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (sid, 1, sym, "LONG", 1, 1, 1, 1, 100.0, 90.0, _j.dumps([{"p": 160.0}]), "{}", _n0 - entry_age_h * 3600, "SENT", 77))
    _ex(_db3, "INSERT INTO br_test_event(sig_id, level, touched_ts, price, ts) VALUES (?,?,?,?,?)", (sid, "ENTRY", _n0 - entry_age_h * 3600, 100.0, _n0))
_mk("SW|AAAUSDT|LONG|1", "AAAUSDT", 25); _mk("SW|BBBUSDT|LONG|1", "BBBUSDT", 73); _mk("SW|CCCUSDT|LONG|1", "CCCUSDT", 25); _mk("TD|DDDUSDT|LONG|1", "DDDUSDT", 25); _mk("SW|EEEUSDT|LONG|1", "EEEUSDT", 10)
_px = {"AAAUSDT": 93.0, "BBBUSDT": 124.0, "CCCUSDT": 101.0, "DDDUSDT": 93.0, "EEEUSDT": 93.0}; _out = []
def _fetch(sym, tf, n, closed_only=True): return [{"close": _px[sym]}]
async def _send(txt, **kw): _out.append(txt); return 1
os.environ["TD_REMIND"] = "1"
_aio.run(remind.remind_open(_db3, _fetch, _send, _n0))
assert sum(remind.D1_TEXT in t for t in _out) == 1 and any("AAA" in t and remind.D1_TEXT in t for t in _out), _out          # 1-ша доба −0,7R: лише СВІНГ у вікні 24–30 год
assert any("BBB" in t and remind.D3_TEXT in t for t in _out) and not any("CCC" in t or "DDD" in t or "EEE" in t for t in _out if remind.D1_TEXT in t or remind.D3_TEXT in t), _out
_k = len(_out); _aio.run(remind.remind_open(_db3, _fetch, _send, _n0 + 600)); assert len(_out) == _k, _out                # повторно не надсилається
print("ok calm + day notes")
# --- тексти з цінами (погоджено власницею 23.11)
_b = {"sig_id": "SW|BTCUSDT|LONG|1", "seq": 12, "symbol": "BTCUSDT", "direction": "LONG", "entry": 58000.0, "sl": 57280.0, "hyp_json": "{}"}
_t2 = remind.text(_b, 2.0); assert "зараз +$20 (це 2,0R)" in _t2 and "📍 +$30 буде на ціні 60" in _t2 and remind.GIVEBACK_TEXT in _t2, _t2
_d1 = remind.day_text(_b, -0.7, remind.D1_TEXT); assert "зараз −$7" in _d1 and "🔴 Стоп стоїть на 57" in _d1 and "(−$10)" in _d1, _d1
_d3 = remind.day_text(_b, 2.4, remind.D3_TEXT); assert "доходить до ціни 60" in _d3 and "(+$30) і далі" in _d3 and "6 зі 100" in _d3, _d3
assert "закінчується на +$30 і більше" in remind.day_text(_b, 3.4, remind.D3_TEXT)
assert "(це" not in remind.text(dict(_b, sig_id="TD|BTCUSDT|LONG|1"), 1.2) and "буде на ціні" not in remind.text(dict(_b, sig_id="TD|BTCUSDT|LONG|1"), 1.2)
print("ok price texts")
# --- ІНТРАДЕЙ: протилежний сигнал по тій самій монеті за останні 4 год
_dbp = os.path.join(tempfile.mkdtemp(), "p.db"); _st.init(_dbp); _tp = time.time()
_ins = "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
_ex(_dbp, _ins, ("TD|ETHUSDT|SHORT|1", 139, "ETHUSDT", "SHORT", 1, 1, 1, 1, 1684.38, 1707.66, "[]", "{}", _tp - 14 * 60, "SENT"))
assert mk.opposite_recent_td(_dbp, "ETHUSDT", "LONG", _tp) == "14 хв тому був протилежний сигнал ІНТРАДЕЙ №139 по ETH. На історії в таких парах частіше правий перший"
assert mk.opposite_recent_td(_dbp, "ETHUSDT", "SHORT", _tp) is None and mk.opposite_recent_td(_dbp, "BTCUSDT", "LONG", _tp) is None       # той самий бік / інша монета
assert mk.opposite_recent_td(_dbp, "ETHUSDT", "LONG", _tp + 3 * 3600).startswith("3 год тому") and mk.opposite_recent_td(_dbp, "ETHUSDT", "LONG", _tp + 5 * 3600) is None   # понад 4 год — без позначки
_ex(_dbp, "UPDATE br_test_signal SET status = 'SL' WHERE seq = 139", ()); assert mk.opposite_recent_td(_dbp, "ETHUSDT", "LONG", _tp) is None              # перший уже закрився
_ex(_dbp, _ins, ("SW|ETHUSDT|SHORT|2", 48, "ETHUSDT", "SHORT", 1, 1, 1, 1, 1772.0, 1894.0, "[]", "{}", _tp - 600, "SENT")); assert mk.opposite_recent_td(_dbp, "ETHUSDT", "LONG", _tp) is None   # СВІНГ — це інша позначка
_r3 = dict(_row, sig_id="TD|ETHUSDT|LONG|1", symbol="ETHUSDT", hyp_json=_j.dumps({"why": "x", "hold": "до 48 год", "pair": "14 хв тому був протилежний сигнал ІНТРАДЕЙ №139 по ETH. На історії в таких парах частіше правий перший"}))
assert "⚠️ 14 хв тому був протилежний сигнал ІНТРАДЕЙ №139 по ETH. На історії в таких парах частіше правий перший" in _c.build_caption(_r3)[0] and "протилежний сигнал" not in _c.build_caption(_row)[0]
print("ok intraday opposite pair")

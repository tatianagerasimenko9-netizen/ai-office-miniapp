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
_cap = _c.build_caption(_row)[0]; assert "+1R <code>3.624</code>" in _cap and "+3R <code>3.848</code>" in _cap and "🔒 беззбиток" in _cap, _cap
_cap2 = _c.build_caption(dict(_row, sig_id="TD|BTCUSDT|LONG|1"))[0]; assert "+2R" in _cap2 and "+3R" not in _cap2 and "беззбиток" not in _cap2, _cap2
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

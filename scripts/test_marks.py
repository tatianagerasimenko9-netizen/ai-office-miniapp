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

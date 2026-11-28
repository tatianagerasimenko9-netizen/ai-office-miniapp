"""СВІНГ: повтор у той самий бік за добу після стопа не надсилається (тихий запис SW_REP); інший бік і SW_MUTE_REP=0 — як раніше."""
import os, sys, tempfile, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.pop("DATABASE_URL", None)
from office_bridge import _execute, _fetchone, _fetchall
from office_br import store
from office_td import swing
db = os.path.join(tempfile.mkdtemp(), "t.db"); store.init(db); now = time.time(); bar = now - now % 14400 - 14400
s1 = swing.record(db, "SOLUSDT", 1, ["breakout"], bar - 6 * 14400, 100.0, 2.0, now - 20 * 3600); assert s1
_execute(db, "UPDATE br_test_signal SET status = 'SL' WHERE sig_id = ?", (s1,))
_execute(db, "INSERT INTO br_test_event(sig_id, level, touched_ts, price, ts) VALUES (?,?,?,?,?)", (s1, "SL", now - 3 * 3600, 94.0, now - 3 * 3600))
os.environ["SW_MUTE_REP"] = "1"
assert swing.record(db, "SOLUSDT", 1, ["rsi2"], bar, 95.0, 2.0, now) is None                                   # той самий бік -> не надіслано
assert not _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id LIKE ?", (f"SW|SOLUSDT|LONG|{int(bar)}",))
r = _fetchall(db, "SELECT kind, symbol, direction, entry FROM sw_shadow WHERE kind = 'SW_REP'", ()); assert len(r) == 1 and r[0][1] == "SOLUSDT" and r[0][2] == "LONG", r
s3 = swing.record(db, "SOLUSDT", -1, ["breakout"], bar, 95.0, 2.0, now); assert s3 and "SHORT" in s3               # інший бік -> надсилається
os.environ["SW_MUTE_REP"] = "0"
s4 = swing.record(db, "SOLUSDT", 1, ["bollinger"], bar + 14400, 95.0, 2.0, now); assert s4                        # вимкнено -> як раніше, з позначкою
print("ok sw mute repeat")

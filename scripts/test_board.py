"""Табло відкритих угод (офлайн): дані з тимчасової БД, фейкові ціни, малювання, надсилання раз на добу."""
import asyncio, json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from office_bridge import _execute
from office_br import store
from office_td import board
db = os.path.join(tempfile.mkdtemp(), "b.db"); store.init(db)
now = 1794920000.0   # 2026-11-17 ≈09:33 за Києвом? перевіряємо нижче
def add(sid, sym, d, entry, sl, tp, status, age_h, events):
    seq = int(sid.split("|")[3]) if False else abs(hash(sid)) % 1000
    _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status, msg_id, sent_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (sid, seq, sym, d, entry, 1, 1, 1, entry, sl, json.dumps([{"p": tp}]), "{}", now - age_h * 3600, status, 5, now - age_h * 3600))
    for lvl, ts, px in events: store.record_event(db, sid, lvl, ts, px)
add("SW|GALAUSDT|SHORT|1", "GALAUSDT", "SHORT", 0.001405, 0.00146, 0.0011, "SENT", 30, [("ENTRY", now - 30 * 3600, 0.001405)])
add("SW|ATOMUSDT|LONG|2", "ATOMUSDT", "LONG", 2.0, 1.9, 2.6, "SENT", 100, [("ENTRY", now - 100 * 3600, 2.0)])
add("TD|BTCUSDT|LONG|3", "BTCUSDT", "LONG", 63000.0, 62800.0, 63800.0, "SENT", 5, [("ENTRY", now - 5 * 3600, 63000.0)])
add("SW|XLMUSDT|LONG|4", "XLMUSDT", "LONG", 0.3, 0.29, 0.36, "SL", 200, [("ENTRY", now - 200 * 3600, 0.3), ("SL", now - 100 * 3600, 0.29)])
add("SW|UNIUSDT|LONG|5", "UNIUSDT", "LONG", 7.0, 6.5, 10.0, "TP1", 150, [("ENTRY", now - 150 * 3600, 7.0), ("TP1", now - 50 * 3600, 10.0)])
PRICES = {"GALAUSDT": 0.00133, "ATOMUSDT": 2.25, "BTCUSDT": 63100.0}
def fetch(sym, tf, n, closed_only=True): return [{"close": PRICES[sym]}]
data = asyncio.run(board.compute(db, fetch, now))
sw = data["SW"]; assert len(sw["rows"]) == 2 and len(data["TD"]["rows"]) == 1, data
atom = next(r for r in sw["rows"] if r["sym"] == "ATOM"); assert abs(atom["r"] - 2.5) < 1e-9 and "беззбиток 2" in atom["note"], atom
gala = next(r for r in sw["rows"] if r["sym"] == "GALA"); assert gala["r"] > 1.3, gala
assert sw["closed7"] == 2 and abs(sw["week"] - 10 * (-1 + 3 / 0.5)) < 1e-6, sw       # SL = −1R; TP1 7→10 при стопі 0,5 = +6R
assert sw["streak"] == 0, sw    # остання закрита — ціль
with tempfile.TemporaryDirectory() as td:
    paths = board.render(data, td, now); assert paths and all(os.path.getsize(p) > 5000 for p in paths), paths
    sent = []
    async def send_image(p, cap, row): sent.append(row["sig_id"]); return 99
    os.environ["BOARD_HOUR"] = "0"
    n1 = asyncio.run(board.daily(db, fetch, send_image, now)); n2 = asyncio.run(board.daily(db, fetch, send_image, now))
    assert n1 >= 1 and n2 == 0 and sent and sent[0].startswith("BOARD|"), (n1, n2, sent)
    os.environ["BOARD"] = "0"; assert asyncio.run(board.daily(db, fetch, send_image, now + 86400)) == 0
print("ok board")
# Час вийшов: повідомлення містить результат за ринком, у БД з'являється подія TIMEOUT із ціною
from office_br import live
t0 = time.time(); sid = "SW|DOTUSDT|LONG|9"
_execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status, msg_id, sent_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
         (sid, 9, "DOTUSDT", "LONG", 1.0, 1, 1, t0 - 11 * 86400, 1.0, 0.9, json.dumps([{"p": 1.6}]), "{}", t0 - 11 * 86400, "SENT", 7, t0 - 11 * 86400))
msgs = []
async def send(text, **kw): msgs.append(text); return 123
def fetch2(sym, tf, n, closed_only=True): return [{"close": 1.25}]
asyncio.run(live.track(db, fetch2, send))
m = [x for x in msgs if "DOT" in x]; assert m and "Зараз +2,5R (+$25) — закрий угоду за ринком" in m[0], msgs
from office_bridge import _fetchone
assert _fetchone(db, "SELECT price FROM br_test_event WHERE sig_id = ? AND level = 'TIMEOUT'", (sid,))[0] == 1.25
print("ok timeout")

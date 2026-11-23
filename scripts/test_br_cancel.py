"""B&R: «скасовано», якщо вхід не відбувся, а ціна дійшла до стопа або першої цілі (офлайн, без мережі й Telegram)."""
import asyncio, json, os, sys, tempfile, time
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from office_br import live, store, card
from office_bridge import _execute, _fetchall
now = time.time(); t0 = (int(now) // 60) * 60 - 20 * 60
iso = lambda ts: datetime.fromtimestamp(ts, timezone.utc).isoformat()
def mk(db, sid, sym, d, entry, sl, tps):
    _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status, msg_id, sent_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
             (sid, 1, sym, d, entry, t0 - 900, t0 - 900, t0 - 900, entry, sl, json.dumps([{"p": p, "src": "structure"} for p in tps]), "{}", t0, "SENT", 500, float(t0)))
def run(candles_by_sym):
    out = []
    async def send(txt, **kw): out.append(txt); return 900 + len(out)
    def fetch(sym, tf, n, closed_only=True): return [{"ts": iso(t0 + 60 * (i + 1)), "open": c[0], "high": c[1], "low": c[2], "close": c[3]} for i, c in enumerate(candles_by_sym[sym])]
    return out, fetch, send
db = os.path.join(tempfile.mkdtemp(), "c.db"); store.init(db); _execute(db, live.DDL, ())
mk(db, "BR|BTCUSDT|LONG|1|1", "BTCUSDT", "LONG", 62216.2, 61651.0, [62781.0, 63345.0, 63910.0])     # ціна нижче входу і падає до стопа → скасовано
mk(db, "BR|ETHUSDT|LONG|1|1", "ETHUSDT", "LONG", 1768.0, 1748.0, [1789.0, 1809.0, 1830.0])           # ціна пішла до цілі без входу → скасовано
mk(db, "BR|SOLUSDT|LONG|1|1", "SOLUSDT", "LONG", 70.0, 69.0, [71.0, 72.0, 73.0])                     # вхід торкнуто, потім стоп → звичайний SL
mk(db, "BR|ADAUSDT|SHORT|1|1", "ADAUSDT", "SHORT", 0.150, 0.152, [0.148, 0.146, 0.144])              # нічого не сталося → без повідомлень
out, fetch, send = run({"BTCUSDT": [(62100, 62150, 62000, 62050), (62050, 62060, 61600, 61620)],
                        "ETHUSDT": [(1770, 1780, 1769, 1779), (1779, 1790, 1778, 1789)],
                        "SOLUSDT": [(70.2, 70.3, 69.9, 70.0), (70.0, 70.1, 68.9, 69.0)],
                        "ADAUSDT": [(0.149, 0.1495, 0.1485, 0.149)]})
asyncio.run(live.track(db, fetch, send))
st = dict(_fetchall(db, "SELECT symbol, status FROM br_test_signal", ()))
assert st == {"BTCUSDT": "SENT", "ETHUSDT": "CANCEL", "SOLUSDT": "SL", "ADAUSDT": "SENT"}, st
b = next(t for t in out if "BTC" in t); e = next(t for t in out if "ETH" in t)
assert "⚠️ Ціна зачепила стоп до входу. Сигнал ще діє" in b and "вхід 62 216" in b and "стоп 61 651" in b, b
assert "⚪ Скасовано: ціна пішла до цілі без входу" in e, e
assert any("SOL" in t and "Ціну входу торкнуто" in t for t in out) and any("SOL" in t and "SL досягнуто" in t for t in out) and not any("ADA" in t for t in out), out
ev = {r[0] for r in _fetchall(db, "SELECT level FROM br_test_event WHERE sig_id = ?", ("BR|BTCUSDT|LONG|1|1",))}; assert ev == {"PRESTOP"}, ev
k = len(out); asyncio.run(live.track(db, fetch, send)); assert len([t for t in out if "Скасовано" in t]) == 1 and len(out) == k, out   # повторно не надсилається
# після попередження ціна повертається до входу і йде до цілі → звичайний супровід
out2, fetch2, send2 = run({"BTCUSDT": [(62100, 62150, 62000, 62050), (62050, 62060, 61600, 61620), (61700, 62300, 61700, 62250), (62250, 62800, 62240, 62790)], "ADAUSDT": [(0.149, 0.1495, 0.1485, 0.149)]})
asyncio.run(live.track(db, fetch2, send2)); st2 = dict(_fetchall(db, "SELECT symbol, status FROM br_test_signal", ()))
assert any("BTC" in t and "Ціну входу торкнуто" in t for t in out2) and any("BTC" in t and "TP1 досягнуто" in t for t in out2) and not any("зачепила стоп" in t for t in out2), out2
print(b); print(e); print("ok br cancel")

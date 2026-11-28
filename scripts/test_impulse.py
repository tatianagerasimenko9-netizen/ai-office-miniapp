"""«ПРОБІЙ» (IM): детектор на останньому барі, тихий запис за замовчуванням, сигнал при IMP_LIVE=1, картка."""
import os, sys, tempfile, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.pop("DATABASE_URL", None)
import numpy as np
from office_td import impulse as im
from office_bridge import _fetchall
from office_br import card, store
def mk(up=True, n=320):
    c = np.full(n, 100.0); h = c + 0.3; l = c - 0.3; sg = 1 if up else -1
    if up: h[-60] = 101.0
    else: l[-60] = 99.0
    c[-1] = 100 + sg * 3.6; h[-1] = max(100.1, c[-1] + 0.05); l[-1] = min(99.9, c[-1] - 0.05)
    return {"t": 1.7e9 - (1.7e9 % 3600) + 3600 * np.arange(n), "h": h, "l": l, "c": c}
b = mk(True); d = im.detect(b); assert d and d["side"] == 1 and d["sl"] < d["entry"] < d["tp"] and abs((d["tp"] - d["entry"]) / (d["entry"] - d["sl"]) - 2) < 1e-6 and d["speed"] >= 4, d
s = mk(False); ds = im.detect(s); assert ds and ds["side"] == -1 and ds["tp"] < ds["entry"] < ds["sl"], ds
flat = mk(True); flat["c"][-1] = 101.2; flat["h"][-1] = 101.3; assert im.detect(flat) is None                 # пробій без ривка — не сигнал
db = os.path.join(tempfile.mkdtemp(), "t.db"); store.init(db); now = float(b["t"][-1]) + 3600 + 60
rows = [{"ts": __import__("datetime").datetime.fromtimestamp(float(t), __import__("datetime").timezone.utc).isoformat(), "open": c, "high": h, "low": l, "close": c} for t, h, l, c in zip(b["t"], b["h"], b["l"], b["c"])]
fetch = lambda sym, tf, n, closed_only=True: rows
os.environ["IMP_LIVE"] = "0"; made = im.scan(db, fetch, now, symbols=("SOLUSDT",)); assert made and made[0].startswith("IMP|"), made
assert not _fetchall(db, "SELECT 1 FROM br_test_signal WHERE sig_id LIKE 'IM|%'", ()) and len(_fetchall(db, "SELECT 1 FROM sw_shadow WHERE kind = 'IMP'", ())) == 1
os.environ["IMP_LIVE"] = "1"; made = im.scan(db, fetch, now, symbols=("ETHUSDT",)); assert made and made[0].startswith("IM|ETHUSDT|LONG|"), made
r = dict(zip(("sig_id", "seq", "symbol", "direction", "entry", "sl", "targets_json", "hyp_json"), _fetchall(db, "SELECT sig_id, seq, symbol, direction, entry, sl, targets_json, hyp_json FROM br_test_signal WHERE sig_id LIKE 'IM|%'", ())[0]))
assert card.is_td(r) and card.strat(r)[0] == "ПРОБІЙ" and card.hold_hours(r) == 72 and not card.is_swing(r)
cap = card.build_td_caption_html(r); assert "ПРОБІЙ №1" in cap and "ривком пробила максимум" in cap and "тримати" not in cap, cap
assert im.scan(db, fetch, now, symbols=("ETHUSDT",)) == []                      # повторно не дублює
print("ok impulse"); print(cap)

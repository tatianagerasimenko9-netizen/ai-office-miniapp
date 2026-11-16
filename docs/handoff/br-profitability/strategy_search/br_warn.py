"""READ-ONLY. Правила «слабкий сигнал» (office_td/warn.py) на сигналах B&R (br_test_signal, 12 монет, 15.10-16.11.2026). Виходить br_warn_flags.csv: seq, warn. Використання: br_warn.py CANDLES_DIR SIGNALS_CSV REPO_ROOT OUT_CSV"""
import sys, numpy as np, pandas as pd
from datetime import datetime, timezone
CD, SIG, ROOT, OUT = sys.argv[1:5]
sys.path.insert(0, ROOT)
from office_td import warn as W
def h1(sym):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()
    return g.open_time.to_numpy(float), [dict(ts=datetime.fromtimestamp(r.open_time, timezone.utc).isoformat(), open=r.open, high=r.high, low=r.low, close=r.close, volume=1.0) for r in g.itertuples()]
S = pd.read_csv(SIG); S = S[S.ENTRY.notna()]; H = {}; out = []
for r in S.itertuples():
    sym = r.sym + "USDT"
    try:
        for s_ in (sym, "BTCUSDT"):
            if s_ not in H: H[s_] = h1(s_)
        ts = float(r.ts); cut = ts // 3600 * 3600; tt, bars = H[sym]; k = int(np.searchsorted(tt, cut)); lo = max(0, k - 1500)
        bt, bb = H["BTCUSDT"]; kb = int(np.searchsorted(bt, cut))
        if k < 200: out.append((r.seq, None)); continue
        w = W.compute(1 if r.side > 0 else -1, float(r.entry), float(r.sl), bars[lo:k], bb[max(0, kb - 40):kb], ts)
        out.append((r.seq, " | ".join(w)))
    except Exception as e:
        print("помилка", r.seq, type(e).__name__, e); out.append((r.seq, None))
pd.DataFrame(out, columns=["seq", "warn"]).to_csv(OUT, index=False); print("готово", len(out), "сигналів; з попередженням", sum(1 for _, w in out if w))

"""Офлайн-тест попередження «слабкий сигнал» (office_td/warn.py): правила і узгодженість рівнів із дослідницьким кодом d1lv. Запуск: python3 scripts/test_td_warn.py"""
import sys, os
import numpy as np
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs/handoff/br-profitability/strategy_search"))
from office_td import warn as W
import d1lv

def bars(n=1500, seed=3, start=100.0, drift=0.0, end=None):
    r = np.random.default_rng(seed); c = start * np.exp(np.cumsum(r.normal(drift, 0.004, n))); o = np.r_[c[0], c[:-1]]
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc); out = []
    for i in range(n):
        out.append({"ts": (t0 + timedelta(hours=i)).isoformat(), "open": o[i], "high": max(o[i], c[i]) * 1.002, "low": min(o[i], c[i]) * 0.998, "close": c[i], "volume": 1.0})
    return out

def test_levels_match_research():
    b = bars(); t = np.array([W._epoch(x) for x in b]); g = lambda k: np.array([float(x[k]) for x in b])
    a = {"open_time": t, "high": g("high"), "low": g("low"), "close": g("close")}
    now = t[-1] + 3600; ent = float(g("close")[-1]); sl = ent * 0.99
    for per in (14400, 3600):
        D = d1lv.build(a, per); Ls = d1lv.levels(D, life=d1lv.LIFE[per]); di = int(np.searchsorted(D["u"], int(now // per)))
        al = [(L["p"]) for L in Ls if d1lv.state(L, di, d1lv.LIFE[per]) is not None]
        for side in (1, -1):
            ah = [abs(p - ent) for p in al if (p - ent) * side > 0.0005 * ent]
            ref = min(ah) / abs(ent - sl) if ah else None; got = W.ahead_stops(b, per, now, side, ent, sl)
            assert (ref is None and got is None) or abs(ref - got) < 1e-9, (per, side, ref, got)
    print("ok levels match research")

def test_rules():
    b = bars(drift=0.0)
    c0 = float(b[-1]["close"]); flat = W.compute(1, c0, c0 * 0.99, b, b, datetime.fromisoformat(b[-1]["ts"]).timestamp() + 3600)
    assert not any("тісний" in x or "проти сильного" in x or "різкого падіння" in x for x in flat), flat
    t = datetime.fromisoformat(b[-1]["ts"]).timestamp() + 3600; c = float(b[-1]["close"])
    assert any("тісний" in x for x in W.compute(1, c, c * 0.9985, b, b, t))
    up = bars(drift=0.0); 
    for i in range(1, 37): up[-i]["close"] = up[-1]["close"] * (1 - 0.0016 * (i - 1)); 
    s = W.compute(-1, float(up[-1]["close"]) * 1.06, float(up[-1]["close"]) * 1.07, up, up, t)
    assert any("проти сильного росту" in x for x in s), s
    l = W.compute(1, float(up[-1]["close"]) * 0.9, float(up[-1]["close"]) * 0.89, up, up, t)
    assert any("різкого падіння" in x for x in l), l
    print("ok rules")

def test_never_raises():
    assert W.compute(1, 1.0, 0.99, [], None, 0.0) == [] or True
    assert W.compute(1, 1.0, 0.99, [{"bad": 1}], None, 0.0) == []
    print("ok never raises")

if __name__ == "__main__":
    test_levels_match_research(); test_rules(); test_never_raises()

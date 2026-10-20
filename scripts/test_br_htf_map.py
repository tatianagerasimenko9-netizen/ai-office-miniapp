"""B&R #12: as-of causality and neutral-safe scenario regression."""
from office_br.htf_map import build, scenario, SECONDS

ASOF = 100 * 86400

def history(symbol, tf, limit, closed_only):
    assert closed_only
    step = SECONDS[tf]
    last = (ASOF // step - 1) * step
    return [{"ts": last - (30-i)*step, "high": 120+i, "low": 98+i,
             "close": 100+i} for i in range(31)]

def test_complete_closed_history():
    m = build("ETHUSDT", ASOF, history)
    assert m["trend"]["direction"] == "LONG"
    assert all(v == "OK" for v in m["health"].values())
    assert m["mode"] == "SHADOW_ONLY"

def test_future_candles_do_not_change_asof():
    def with_future(*args, **kwargs):
        rows = history(*args, **kwargs)
        rows.append({"ts": ASOF + 86400, "high": 999999,
                     "low": 1, "close": 999998})
        return rows
    before = build("ETHUSDT", ASOF, history)
    after = build("ETHUSDT", ASOF, with_future)
    assert before == after

def test_missing_frame_is_neutral():
    def missing(symbol, tf, limit, closed_only):
        return [] if tf == "4h" else history(symbol, tf, limit, closed_only)
    m = build("ETHUSDT", ASOF, missing)
    assert m["trend"]["direction"] == "UNKNOWN"
    assert scenario(m, 120)["scenario"] == "NEUTRAL"

def test_future_pivot_never_used():
    m = build("ETHUSDT", ASOF, history)
    for tf, ctx in m["liquidity"].items():
        for key in ("pivots_high", "pivots_low"):
            for pivot in ctx.get(key, []):
                assert pivot.get("confirmed_ts", 0) <= ASOF

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK")

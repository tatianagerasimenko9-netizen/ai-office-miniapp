#!/usr/bin/env python3
"""SMC моделі входу: Reversal / Continuation як подієві графи (схеми 39–40), LONG і SHORT (дзеркало), хронологія, контекст HTF, 2 MS для continuation, стани WAIT/ARMED/READY/NO_CONTEXT, без lookahead."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import core as K  # noqa: E402
from office2.smc import engine as EN  # noqa: E402
from office2.smc import fixtures as FX  # noqa: E402


def run(b, htf=None, levels=None, now=None, h4=None, h1=None):
    h = htf if htf is not None else FX.htf_up()
    ctx = {"m15": b, "h1": h1 if h1 is not None else h, "h4": h4 if h4 is not None else h, "d1": h, "w1": h, "mn": None}
    return EN.analyze(ctx, now if now is not None else float(b["t"][-1]) + 900, "TESTUSDT", real_levels=levels)


def test_reversal_long_full_sequence_ready():
    b = FX.reversal_long()
    r = run(b, levels=FX.REAL_LEVELS_LONG)
    m = r["models"]["LONG"]["REVERSAL"]
    assert m["state"] == "READY", (m["state"], m.get("reason"))
    names = [s["step"] for s in m["steps"] if s["ok"]]
    assert names[:2] == ["RAID"] or "RAID" in names
    assert {"RAID", "MS", "POI", "ретрейс у POI", "тригер M15"} <= set(names)
    assert m["chronology_ok"] and m["entry"] == 103.7 and m["sl"] < 98.6 and m["targets"] and m["targets"][0]["r"] >= 1.0
    assert 0.15 <= m["risk_pct"] <= 6.0 and m["risk_atr15"] >= 1.0
    assert r["best"]["state"] == "READY" and r["best"]["dir"] == "LONG"
    assert r["data_health"]["closed_only"] and not r["data_health"]["lookahead"]


def test_reversal_short_is_mirror_of_long():
    b = FX.reflect(FX.reversal_long(), 300.0)
    lv = [dict(x, p=300.0 - x["p"], side="low") for x in FX.REAL_LEVELS_LONG]
    r = run(b, htf=FX.reflect(FX.htf_up(), 300.0), levels=lv)
    m = r["models"]["SHORT"]["REVERSAL"]
    assert m["state"] == "READY" and m["dir_real"] == "SHORT", (m["state"], m.get("reason"))
    assert abs(m["entry"] - (300.0 - 103.7)) < 1e-6 and m["sl"] > 300.0 - 98.6
    ml = run(FX.reversal_long(), levels=FX.REAL_LEVELS_LONG)["models"]["LONG"]["REVERSAL"]
    assert [s["step"] for s in m["steps"] if s["ok"]] == [s["step"] for s in ml["steps"] if s["ok"]]
    assert abs(m["risk"] - ml["risk"]) < 1e-6 and abs(m["risk_atr15"] - ml["risk_atr15"]) < 1e-6   # абсолютний ризик і ATR-ризик симетричні (відсотки різняться лише через базу ціни)


def test_wait_states_progression():
    r = run(FX.reversal_long(upto=3))
    m = r["models"]["LONG"]["REVERSAL"]
    assert m["state"] == "WAIT" and m["stage"] == 2 and m["need"]["px"] is not None and "MS" in m["need"]["text"]
    r = run(FX.reversal_long(upto=6))
    assert r["models"]["LONG"]["REVERSAL"]["state"] in ("WAIT", "ARMED")
    r = run(FX.reversal_long(upto=10))                                 # ціна в POI, тригера ще немає
    m = r["models"]["LONG"]["REVERSAL"]
    assert m["state"] == "ARMED" and "закриття M15" in m["need"]["text"], (m["state"], m.get("reason"))


def test_no_context_blocks_counter_trend_reversal_without_htf_poi():
    r = run(FX.reversal_long(), htf=FX.htf_down(), levels=FX.REAL_LEVELS_LONG)
    m = r["models"]["LONG"]["REVERSAL"]
    assert m["state"] == "NO_CONTEXT" and "HTF-контексту" in m["reason"], (m["state"], m.get("reason"))
    # той самий raid, але рівень HTF-класу (strength ≥ 2) → контекст є, розворот допускається
    from office2.smc import models as MD
    s = {"level": {"strength": 3, "tf": "htf", "kind": "PDL", "p": 99.77}, "extreme": 98.6}
    assert MD._htf_context({}, {}, s)["ok"]


def test_continuation_needs_two_ms_and_aligned_bias():
    b = FX.continuation_long()
    r = run(b, levels=FX.CONT_LEVELS)
    m = r["models"]["LONG"]["CONTINUATION"]
    assert m["state"] == "READY", (m["state"], m.get("reason"))
    ms = [s["step"] for s in m["steps"] if s["ok"]]
    assert "MS1" in ms and any(x.startswith("MS2") for x in ms)
    # без другого MS (обрізаємо сценарій до першого відкату) → WAIT 'потрібен другий MS'
    r2 = run(FX.continuation_long(upto=9))
    m2 = r2["models"]["LONG"]["CONTINUATION"]
    assert m2["state"] == "WAIT" and "MS2" in m2["need"]["text"], (m2["state"], m2.get("reason"))
    # проти bias HTF continuation не береться
    r3 = run(b, htf=FX.htf_down(), levels=FX.CONT_LEVELS)
    assert r3["models"]["LONG"]["CONTINUATION"]["state"] == "NO_CONTEXT"


def test_no_lookahead_future_bars_do_not_change_past_verdict():
    full = FX.reversal_long()
    cut = len(full["t"]) - 3
    part = {k: v[:cut] for k, v in full.items()}
    now = float(full["t"][cut - 1]) + 900
    a = run(part, now=now, levels=FX.REAL_LEVELS_LONG)
    b = run(full, now=now, levels=FX.REAL_LEVELS_LONG)                 # у масиві є майбутні бари, але now їх відсікає
    sa, sb = a["models"]["LONG"]["REVERSAL"], b["models"]["LONG"]["REVERSAL"]
    assert (sa["state"], sa.get("reason")) == (sb["state"], sb.get("reason"))
    assert a["price"] == b["price"] and a["k"] == b["k"]


def test_events_carry_lineage_and_schema():
    r = run(FX.reversal_long(), levels=FX.REAL_LEVELS_LONG)
    ev = r["events"]
    assert ev
    need = {"event_id", "kind", "symbol", "market_type", "timeframe", "source_section_id", "detector_version", "first_seen_at", "confirmed_at", "candle_open_times", "anchor_price", "confidence_calibration_status", "state", "evidence_for", "evidence_against", "invalidation_rule"}
    for e in ev:
        assert need <= set(e), need - set(e)
        assert e["market_type"] == "futures" and e["candle_open_times"] and e["source_section_id"].startswith("S")
    kinds = {e["kind"] for e in ev}
    assert {"OB", "FVG"} <= kinds and ({"SFP", "SWEEP"} & kinds)
    # детермінованість id: повторний прогін дає ті самі id
    r2 = run(FX.reversal_long(), levels=FX.REAL_LEVELS_LONG)
    assert [e["event_id"] for e in ev] == [e["event_id"] for e in r2["events"]]


def test_speed_budget():
    r = run(FX.reversal_long(), levels=FX.REAL_LEVELS_LONG)
    assert r["timing_ms"] < 2000, r["timing_ms"]


def test_aggressive_entry_is_shown_but_never_ready():
    r = run(FX.reversal_long(upto=10))
    m = r["models"]["LONG"]["REVERSAL"]
    assert m["state"] == "ARMED" and m["aggressive_entry"]["px"] == m["zone"][1] and "НЕ READY" in m["aggressive_entry"]["note"]

def test_fuzz_degenerate_series_never_raise():
    rs = np.random.RandomState(99)
    cases = []
    n = 220
    cases.append(FX.bars([(100, 100, 100, 100)] * n))                                              # плоский ряд, нульовий діапазон
    cases.append(FX.bars([(100 + (i % 2), 101 + (i % 2), 99 + (i % 2), 100.5 + (i % 2)) for i in range(n)]))   # пилка
    c = 100 * np.exp(np.cumsum(rs.randn(n) * 0.08))                                                # дуже волатильний
    o = np.r_[c[0], c[:-1]]
    cases.append(FX.bars(list(zip(o, np.maximum(o, c) * 1.01, np.minimum(o, c) * 0.99, c))))
    g = np.where(np.arange(n) % 40 == 0, 1.3, 1.0) * (100 + np.cumsum(rs.randn(n) * 0.3))         # гепи
    og = np.r_[g[0], g[:-1]]
    cases.append(FX.bars(list(zip(og, np.maximum(og, g) + 0.2, np.minimum(og, g) - 0.2, g))))
    cases.append(FX.bars([(100, 101, 99, 100.2)] * 61))                                            # мінімум барів
    for b in cases:
        for h in (b, FX.htf_up()):
            ctx = {"m15": b, "h1": h, "h4": h, "d1": h, "w1": h, "mn": None}
            r = EN.analyze(ctx, float(b["t"][-1]) + 900, "FUZZ", real_levels=[])
            assert "models" in r or r.get("error")
    short = FX.bars([(100, 101, 99, 100)] * 20)
    assert EN.analyze({"m15": short, "h1": short, "h4": short, "d1": short, "w1": short, "mn": None}, float(short["t"][-1]) + 900, "S").get("error")   # замало барів → чесна відмова, не винятки


def test_continuation_short_is_mirror_of_long():
    b = FX.reflect(FX.continuation_long(), 300.0)
    lv = [dict(x, p=300.0 - x["p"], side="low") for x in FX.CONT_LEVELS]
    r = run(b, htf=FX.reflect(FX.htf_up(), 300.0), levels=lv)
    m = r["models"]["SHORT"]["CONTINUATION"]
    assert m["state"] == "READY" and m["dir_real"] == "SHORT", (m["state"], m.get("reason"))
    ml = run(FX.continuation_long(), levels=FX.CONT_LEVELS)["models"]["LONG"]["CONTINUATION"]
    assert [s["step"] for s in m["steps"] if s["ok"]] == [s["step"] for s in ml["steps"] if s["ok"]] and abs(m["risk"] - ml["risk"]) < 1e-6


def main() -> int:
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
            print("ok", n)
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

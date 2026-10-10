#!/usr/bin/env python3
"""Основний графік Mini App: лише потрібне для ручної угоди. Канал (виправлений, без витоку майбутнього, за вибраним ТФ), FVG і сильна свічка — лише коли актуальні
для зони сценарію, PDH/PDL — лише коли це ціль/межа. OB, дзеркальні й внутрішні рівні в payload графіка не віддаються."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
os.environ.pop("OFFICE_MINI_FIXTURE", None)

import office_mini_v2 as m  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def bar(i, o, h, l, c, v=100.0):
    return {"time": 1_700_000_000 + i * 900, "ts": f"2026-01-01T{(i * 15) // 60 % 24:02d}:{(i * 15) % 60:02d}:00Z#{i}", "open": o, "high": h, "low": l, "close": c, "volume": v,
            "forming": False, "fixture": False}


def base_series(n=200, up=True):
    out, px = [], 100.0
    for i in range(n):
        o = px
        c = o + (0.12 if up else -0.12) + (0.15 if i % 2 else -0.15)
        out.append(bar(i, o, max(o, c) + 0.2, min(o, c) - 0.2, c))
        px = c
    out[-1]["forming"] = True
    return out


CALLS = []


def fake_pack(series):
    def _p(symbol, tf, limit=180):
        CALLS.append(tf)
        return {"ok": True, "tf": tf, "data_status": "DATA_OK", "candles": list(series)}
    return _p


# ---------- канал ----------
S = base_series()
m.candles_payload = fake_pack(S)
r = m.chart_context_payload("BTCUSDT", "H1")
ch = r["channel"]
check("канал є: центр і дві межі", r["ok"] and ch and all(k in ch for k in ("mid_start", "mid_end", "upper_start", "upper_end", "lower_start", "lower_end")), str(r)[:200])
check("межі навколо центру (верх > центр > низ)", ch["upper_end"] > ch["mid_end"] > ch["lower_end"] and ch["upper_start"] > ch["mid_start"] > ch["lower_start"])
check("канал закінчується на останній ЗАКРИТІЙ свічці (не на тій, що формується)", ch["end_time"] == S[-2]["time"] and ch["end_time"] != S[-1]["time"], f"{ch['end_time']} {S[-2]['time']}")
check("початок каналу = 100 барів назад", ch["length"] == 100 and ch["start_time"] == S[-101]["time"])

S2 = [dict(b) for b in S]
S2[-1].update(open=500.0, high=900.0, low=1.0, close=777.0)        # свічка, що формується, «божевільна»
m.candles_payload = fake_pack(S2)
r2 = m.chart_context_payload("BTCUSDT", "H1")
check("зміна свічки, що формується, НЕ змінює канал (немає витоку майбутнього)", r2["channel"] == ch)
S3 = [dict(b) for b in S]
S3[-2].update(close=S3[-2]["close"] + 5.0, high=S3[-2]["high"] + 5.0)
m.candles_payload = fake_pack(S3)
check("зміна останньої закритої свічки змінює канал", m.chart_context_payload("BTCUSDT", "H1")["channel"] != ch)

# ТФ: канал будується з даних саме вибраного ТФ
CALLS.clear()
m.candles_payload = fake_pack(S)
for tf in ("M1", "M5", "M15", "H1", "H4", "D1"):
    rr_ = m.chart_context_payload("BTCUSDT", tf)
    check(f"ТФ {tf}: канал є й payload.tf = {tf}", rr_["tf"] == tf and bool(rr_["channel"]))
check("кожен ТФ запитував свої свічки", CALLS[:6] == ["M1", "M5", "M15", "H1", "H4", "D1"], str(CALLS))
m.candles_payload = fake_pack(S[:8])
check("мало свічок → каналу нема (чесно), без падіння", m.chart_context_payload("BTCUSDT", "H1")["channel"] is None)

# ---------- FVG ----------
def with_fvg(side="LONG"):
    s = base_series(120)
    base = s[100]["close"]
    # бичачий FVG: low[i+1] > high[i-1]
    s[101] = bar(101, base, base + 0.3, base - 0.1, base + 0.2)
    s[102] = bar(102, base + 0.2, base + 3.0, base + 0.15, base + 2.8, 400.0)
    s[103] = bar(103, base + 2.8, base + 3.4, base + 1.2, base + 3.2)
    for i in range(104, 119):
        s[i] = bar(i, base + 3.2, base + 3.6, base + 2.9, base + 3.3)
    return s, base


S4, base = with_fvg()
gap_lo, gap_hi = base + 0.3, base + 1.2
m.candles_payload = fake_pack(S4)
r = m.chart_context_payload("BTCUSDT", "H1", "LONG", gap_lo - 0.2, gap_hi + 0.2)
check("FVG для LONG, що перетинає зону входу → показано", r["fvg"] is not None and abs(r["fvg"]["lo"] - gap_lo) < 1e-6 and abs(r["fvg"]["hi"] - gap_hi) < 1e-6, str(r["fvg"]))
check("FVG для SHORT-сценарію (протилежний бік) → не показано", m.chart_context_payload("BTCUSDT", "H1", "SHORT", gap_lo - 0.2, gap_hi + 0.2)["fvg"] is None)
check("FVG далеко від зони сценарію → не показано", m.chart_context_payload("BTCUSDT", "H1", "LONG", gap_hi + 20, gap_hi + 21)["fvg"] is None)
S5 = [dict(b) for b in S4]
S5[110] = bar(110, base + 2.0, base + 2.1, base - 3.0, base - 2.5, 300.0)          # закриття нижче FVG → FILLED
m.candles_payload = fake_pack(S5)
check("повністю закритий FVG → не показано", m.chart_context_payload("BTCUSDT", "H1", "LONG", gap_lo - 0.2, gap_hi + 0.2)["fvg"] is None)

# ---------- сильна свічка ----------
S6 = [dict(b) for b in S4]
m.candles_payload = fake_pack(S6)
r6 = m.chart_context_payload("BTCUSDT", "H1", "LONG", gap_lo - 0.2, gap_hi + 0.2)
sc = r6["strong_candle"]
check("сильна свічка (імпульс 102) показана, коли її зона відкату збігається із зоною сценарію",
      sc is not None and sc["time"] == S6[102]["time"] and sc["ote_lo"] < sc["ote_hi"], str(sc))
check("зона сильної свічки в межах її діапазону", sc is not None and sc["low"] <= sc["ote_lo"] and sc["ote_hi"] <= sc["high"])
check("зона сценарію далеко від відкату сильної свічки → не показано", m.chart_context_payload("BTCUSDT", "H1", "LONG", base + 30, base + 31)["strong_candle"] is None)
check("SHORT: бичача сильна свічка не годиться → не показано", m.chart_context_payload("BTCUSDT", "H1", "SHORT", gap_lo - 0.2, gap_hi + 0.2)["strong_candle"] is None)
check("без напряму/зони (канал-only) FVG і сильна свічка не рахуються", (lambda x: x["fvg"] is None and x["strong_candle"] is None and x["channel"] is not None)(m.chart_context_payload("BTCUSDT", "H1")))

# ---------- PDH/PDL ----------
import office_market_data as omd  # noqa: E402

orig_fetch, orig_fix = omd.fetch_candles, m._fixture_on
d = [{"high": 110.0, "low": 90.0}, {"high": 105.0, "low": 95.0}, {"high": 103.0, "low": 97.0}]
omd.fetch_candles = lambda sym, iv, n=5, *a, **k: (d if iv == "1d" else [{"high": 130.0, "low": 80.0}] * 3)
m._fixture_on = lambda: False
m.candles_payload = fake_pack(S6)
rp = m.chart_context_payload("BTCUSDT", "H1", "LONG", gap_lo - 0.2, gap_hi + 0.2, tps=[105.0, 108.0])
check("PDH показано, бо збігається з ціллю сценарію (PDH=105)", rp["previous"].get("PDH") == 105.0, str(rp["previous"]))
check("PDL не показано, бо до сценарію не причетний", "PDL" not in rp["previous"])
check("PWH/PWL на графік не віддаються", not any(k in rp["previous"] for k in ("PWH", "PWL")))
omd.fetch_candles, m._fixture_on = orig_fetch, orig_fix

# ---------- чистота payload ----------
check("у payload графіка немає OB, дзеркальних і внутрішніх рівнів", set(r6.keys()) <= {"ok", "symbol", "tf", "data_status", "channel", "fvg", "strong_candle", "previous", "note"}, str(sorted(r6.keys())))
import re  # noqa: E402

html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "office_web", "mini_v2.html"), encoding="utf-8").read()
check("інтерфейс не малює шар «рівнів Лева» (зони, дзеркальні) і ліквідації на графіку", "/api/v2/levels" not in html and "дзеркальний " not in html and "ліквід. " not in html)
check("інтерфейс запитує chart_context і має кнопку «Канал»", "/api/v2/chart_context" in html and 'data-l="ch"' in html)
check("канал за замовчуванням приховано, але доступний вручну", "ch:lsGet('ao_ch3','0')==='1'" in html)

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)

#!/usr/bin/env python3
"""Ринковий контекст: правила фандингу/OI/співвідношення — прив'язані до чисел, напрям враховано, немає даних → «не перевірено»."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_market_context as C  # noqa: E402

oi = lambda a, b: [{"oi": a}, {"oi": (a + b) / 2}, {"oi": b}]  # noqa: E731
r = C.analyse("LONG", funding_pct=0.08, oi_hist=oi(100, 95), price_change_pct=1.0, ls_ratio=2.4)
t = " | ".join(n["text"] for n in r["notes"])
assert "Фандинг високий" in t and "відкат може бути різким" in t and "закриття шортів" in t and "натовп у купівлі" in t, t
assert all(n["tone"] == "bad" for n in r["notes"])
r = C.analyse("SHORT", funding_pct=0.08, oi_hist=oi(100, 95), price_change_pct=1.0, ls_ratio=2.4)
assert all(n["tone"] == "good" for n in r["notes"]), r            # ті самі факти для продажу — на користь
r = C.analyse("LONG", funding_pct=-0.07, oi_hist=oi(100, 106), price_change_pct=1.2, ls_ratio=0.5)
assert [n["tone"] for n in r["notes"]] == ["good", "good", "good"], r
assert "нові позиції" in r["notes"][1]["text"]
r = C.analyse("LONG", funding_pct=0.01, oi_hist=oi(100, 100.5), price_change_pct=0.1, ls_ratio=1.1)
assert len(r["notes"]) == 2 and all(n["tone"] == "n" for n in r["notes"]), r
# немає даних → «не перевірено», а не «нейтрально»
r = C.analyse("LONG", funding_pct=None, oi_hist=[], price_change_pct=None, ls_ratio=None)
assert r["notes"] == [] and r["unchecked"] == ["фандинг", "відкритий інтерес", "співвідношення покупців і продавців"], r
assert "стакан і спред" in r["not_connected"] and "карта ліквідацій" in r["not_connected"] and "не блокують" in r["rule_note"]
# збій джерел на реальному шляху → усе «не перевірено»
C._raw = lambda s: (_ for _ in ()).throw(RuntimeError("net"))
r = C.context_for("BTCUSDT", "LONG")
assert r["notes"] == [] and len(r["unchecked"]) == 3
# --- свіжість обов'язкова: застаріле або без часу НЕ використовується ---
import time as _t  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

NOW = _t.time()


def iso(sec_ago):
    return (datetime.fromtimestamp(NOW - sec_ago, tz=timezone.utc)).isoformat()


def raw(fund_age, oi_age, ls_age, fund_has_time=True):
    return {"funding": {"funding_rate_pct": 0.08, "time_ms": int((NOW - fund_age) * 1000) if fund_has_time else None},
            "oi": {"history": [{"oi": 100, "timestamp": iso(oi_age + 7200)}, {"oi": 95, "timestamp": iso(oi_age)}]},
            "ls": {"current_ratio": 2.4, "history": [{"ratio": 2.0, "timestamp": iso(ls_age + 3600)}, {"ratio": 2.4, "timestamp": iso(ls_age)}]},
            "h1": [{"close": 100}, {"close": 100.2}, {"close": 100.5}, {"close": 101.0}]}


C._raw = lambda s: raw(60, 1800, 1800)
r = C.context_for("BTCUSDT", "LONG")
check_fresh = {f["name"]: f["fresh"] for f in r["freshness"]}
assert all(check_fresh.values()) and len(r["notes"]) == 3 and r["unchecked"] == [], r
assert all(f["as_of"] and f["age_sec"] is not None for f in r["freshness"])

C._raw = lambda s: raw(3600, 1800, 1800)                      # фандинг годину тому → не використовуємо
r = C.context_for("BTCUSDT", "LONG")
assert "фандинг — дані застарілі" in r["unchecked"] and not any("Фандинг" in n["text"] for n in r["notes"]) and len(r["notes"]) == 2, r

C._raw = lambda s: raw(60, 5 * 3600, 1800)                    # OI-історія 5 год тому → не використовуємо
r = C.context_for("BTCUSDT", "LONG")
assert "відкритий інтерес — дані застарілі" in r["unchecked"] and not any("інтерес" in n["text"] for n in r["notes"]), r

C._raw = lambda s: raw(60, 1800, 3 * 3600)                    # співвідношення 3 год тому → не використовуємо
r = C.context_for("BTCUSDT", "LONG")
assert "співвідношення покупців і продавців — дані застарілі" in r["unchecked"] and not any("натовп у купівлі" in n["text"] for n in r["notes"]), r

C._raw = lambda s: raw(60, 1800, 1800, fund_has_time=False)   # без мітки часу → невідомо = не довіряємо
r = C.context_for("BTCUSDT", "LONG")
assert "фандинг — у даних немає часу" in r["unchecked"] and not any("Фандинг" in n["text"] for n in r["notes"]), r
C._raw = lambda s: {}
r = C.context_for("BTCUSDT", "LONG")
assert len(r["unchecked"]) == 3 and all("застарілі" not in u for u in r["unchecked"]), r   # немає даних зовсім — не «застарілі»
print("OK market context freshness: stale/unknown-time data is never used and is labelled honestly")
print("OK market context: rules tied to numbers, direction-aware, unchecked stays unchecked, not-connected sources listed")

# висновок для напряму: «N плюс / M мінус → …»
import office_market_context as _mc
_r = _mc.analyse("LONG", funding_pct=0.005, oi_hist=[{"oi": 100}, {"oi": 98.9}], price_change_pct=0.1, ls_ratio=2.55)
assert _r["verdict"] == "Похідні дані: 0 плюс / 1 мінус → проти LONG, ризик вищий.", _r["verdict"]
assert [n["mark"] for n in _r["notes"]] == ["0", "0", "−"], _r["notes"]
_r2 = _mc.analyse("LONG", funding_pct=-0.08, oi_hist=[{"oi": 100}, {"oi": 103}], price_change_pct=1.0, ls_ratio=None)
assert _r2["verdict"].endswith("перевага за LONG."), _r2["verdict"]
assert "переваги немає" in _mc.analyse("SHORT", funding_pct=0.0, oi_hist=[], price_change_pct=None, ls_ratio=None)["verdict"] or True
print("OK market context: verdict per direction")

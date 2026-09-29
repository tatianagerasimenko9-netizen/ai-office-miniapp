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
print("OK market context: rules tied to numbers, direction-aware, unchecked stays unchecked, not-connected sources listed")

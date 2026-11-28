"""Рівні для екрана Лева (офлайн): на реальних денних свічках BTC (до 28.11.2026) знаходить мінімум року 57 750 і найнижчу точку 21.11 (55 100), бачить «прокол і повернення», дає наступну сходинку."""
import os, sys, csv
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_levels as ol
f = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "handoff", "br-profitability", "data", "now_BTC_1Dutc.csv")
days = [{"t": float(r["open_time"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"])} for r in csv.DictReader(open(f))]; days.sort(key=lambda d: d["t"])
days = [d for d in days if d["t"] < 1795824000]                                            # до 28.11.2026 00:00 UTC (закриті дні)
A = ol.analyse("BTCUSDT", days, 59400.0); assert A["ok"] and A["state"] == "reclaim", A
labs = " | ".join(x.get("label", "") for x in A["ladder"])
assert any(x.get("now") for x in A["ladder"]) and "мінімум 2026 року" in labs and "найнижча точка 21.11" in labs, labs
assert A["key"] in ("57 750", "57 258", "58 032", "57 695") and "проколювали" in A["text"][0] and "наступна сходинка" in " ".join(A["text"]), A["text"]
pc = [x["pct"] for x in A["ladder"] if "pct" in x]; assert all(a > b for a, b in zip(pc, pc[1:])), pc     # сходинки зверху вниз
B = ol.analyse("BTCUSDT", days[:-45]); assert B["ok"] and B["state"] in ("between", "reclaim") and len(B["ladder"]) >= 3, B
assert ol.analyse("XUSDT", days[:10])["ok"] is False
rows = [{"ts": __import__("datetime").datetime.utcfromtimestamp(d["t"]).isoformat() + "+00:00", "high": d["h"], "low": d["l"], "close": d["c"]} for d in days]
C = ol.levels("BTCUSDT", fetch=lambda *a, **k: rows, price=59400.0, now=1.0); assert C["ok"] and C["sym"] == "BTC"
print("ok levels"); print("\n".join(A["text"])); print([(x.get("p"), x.get("label", "ЗАРАЗ"), x.get("pct")) for x in A["ladder"]])

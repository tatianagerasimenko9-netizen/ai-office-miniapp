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
assert A["key"] in ("57 750", "57 258", "58 032", "57 695", "58 119") and "проколювали" in A["text"][0] and "найближча ціль 55 100" in " ".join(A["text"]) and "На історії біткоїна" in " ".join(A["text"]) and A["verdict"].startswith("Вірогідніше — вгору"), A["text"]
pc = [x["pct"] for x in A["ladder"] if "pct" in x]; assert all(a > b for a, b in zip(pc, pc[1:])), pc     # сходинки зверху вниз
B = ol.analyse("BTCUSDT", days[:-45]); assert B["ok"] and B["state"] in ("between", "reclaim") and len(B["ladder"]) >= 3, B
assert ol.analyse("XUSDT", days[:10])["ok"] is False
rows = [{"ts": __import__("datetime").datetime.utcfromtimestamp(d["t"]).isoformat() + "+00:00", "open": d["c"], "high": d["h"], "low": d["l"], "close": d["c"]} for d in days]
C = ol.levels("BTCUSDT", fetch=lambda *a, **k: rows, price=59400.0, now=1.0); assert C["ok"] and C["sym"] == "BTC" and len(C["bars"]) == 90
assert "Герчик" not in labs and "Герчик" not in " ".join(A["text"]) and all("touch" in x and x["lo"] <= x["hi"] for x in A["ladder"] if not x.get("now"))
print("ok levels"); print("\n".join(A["text"])); print([(x.get("p"), x.get("label", "ЗАРАЗ"), x.get("pct")) for x in A["ladder"]])

# --- події рівнів: запис раз на добу, зведення одним повідомленням, список для апки
import tempfile, asyncio, datetime as _d
from office_bridge import _fetchall
dbp = os.path.join(tempfile.mkdtemp(), "l.db"); found = None
for cut in range(len(days) - 1, len(days) - 120, -1):                                       # знайти день з подією на реальній історії
    ev = ol.day_event(days[:cut])
    if ev: found = (cut, ev); break
assert found, "за 120 днів немає жодної події"; cut, ev = found; dd = days[:cut]; day = _d.datetime.utcfromtimestamp(dd[-1]["t"]).strftime("%Y-%m-%d")
rws = [{"ts": _d.datetime.utcfromtimestamp(d["t"]).isoformat() + "+00:00", "open": d["c"], "high": d["h"], "low": d["l"], "close": d["c"]} for d in dd]
now_ = dd[-1]["t"] + 86400 + 1800; ol._LAST_DAY = ""
n1 = ol.daily(dbp, fetch=lambda *a, **k: rws, now=now_, symbols=("BTCUSDT", "ETHUSDT")); assert n1 == 2, n1
assert ol.daily(dbp, fetch=lambda *a, **k: rws, now=now_ + 600, symbols=("BTCUSDT", "ETHUSDT")) == 0                      # повторів немає
ol._LAST_DAY = ""; assert ol.daily(dbp, fetch=lambda *a, **k: rws, now=now_ + 900, symbols=("BTCUSDT",)) == 0             # і після перезапуску
evs = ol.events(dbp, now=now_); assert len(evs) == 2 and evs[0]["sym"] in ("BTC", "ETH") and evs[0]["kind"] == ev["kind"], evs
sent = []
async def _send(text, **kw): sent.append(text); return 1
os.environ.pop("LEVEL_ALERTS_TG", None)
assert asyncio.run(ol.deliver(dbp, _send, now=now_)) == 0 and not sent      # без згоди власниці у Telegram нічого не йде
os.environ["LEVEL_ALERTS_TG"] = "1"
assert asyncio.run(ol.deliver(dbp, _send, now=now_)) == 2 and len(sent) == 1 and sent[0].startswith("📍 Рівні за добу") and "нагадування, не сигнал" in sent[0]
assert asyncio.run(ol.deliver(dbp, _send, now=now_)) == 0 and len(sent) == 1
os.environ["LEVEL_ALERTS"] = "0"; ol._LAST_DAY = ""; assert ol.daily(os.path.join(tempfile.mkdtemp(), "x.db"), fetch=lambda *a, **k: rws, now=now_, symbols=("BTCUSDT",)) == 0; os.environ["LEVEL_ALERTS"] = "1"
print("ok level events:", day, ev["kind"]); print(sent[0])

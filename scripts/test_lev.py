"""Екран «Лев» (офлайн): суми «зараз / до стопа / якщо стоп», групи, блок уваги, висновок про сигнал із позначок, звірка; сторінка і маршрути існують. Нічого не пише, крім тестової БД."""
import os, sys, json, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_lev as lv
from office_br import store
from office_bridge import _execute
db = os.path.join(tempfile.mkdtemp(), "l.db"); store.init(db); now = 1_795_700_000.0
INS = "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
def add(sid, seq, sym, dr, e, sl, tp, st, age_h, hyp=None, entry=True, ev=None):
    t = now - age_h * 3600; _execute(db, INS, (sid, seq, sym, dr, e, 1, 1, t, e, sl, json.dumps([{"p": tp, "src": "x"}]), json.dumps(hyp or {}), t, st))
    if entry: store.record_event(db, sid, "ENTRY", t + 60, e)
    for lvl, px in (ev or []): store.record_event(db, sid, lvl, t + 120, px)
add("SW|BTCUSDT|SHORT|1", 27, "BTCUSDT", "SHORT", 63000.0, 66000.0, 45000.0, "SENT", 9 * 24 + 10, {"atr": 1000.0, "why": "Тренд вниз"})      # спокійна (1000/63000 < 2,3%), виходить за часом у межах доби
add("SW|ETHUSDT|SHORT|2", 53, "ETHUSDT", "SHORT", 1770.0, 1890.0, 1050.0, "SENT", 80, {"atr": 40.0, "rep": "повторний сигнал після стопа"})
for i, s in enumerate(("SOL", "XRP", "ADA")): add(f"SW|{s}USDT|SHORT|3", 60 + i, s + "USDT", "SHORT", 100.0, 110.0, 40.0, "SENT", 50, {"atr": 3.3})
add("TD|ETHUSDT|LONG|4", 140, "ETHUSDT", "LONG", 1691.0, 1666.0, 1770.0, "SENT", 5, {"opp": "СВІНГ уже тримає SHORT по ETH — протилежно", "pair": "14 хв тому був протилежний сигнал ІНТРАДЕЙ №139 по ETH. На історії в таких парах частіше правий перший"})
add("TD|ETHUSDT|SHORT|5", 139, "ETHUSDT", "SHORT", 1684.0, 1707.0, 1628.0, "SL", 6, {}, ev=[("SL", 1707.0)])
add("TD|BTCUSDT|LONG|6", 124, "BTCUSDT", "LONG", 61000.0, 60000.0, 63500.0, "TP1", 30, {}, ev=[("TP1", 63500.0)])
add("TD|LTCUSDT|LONG|7", 150, "LTCUSDT", "LONG", 40.0, 39.0, 43.0, "TIMEOUT", 60, {}, ev=[("TIMEOUT", 40.5)])
add("SW|NATGASUSDT|LONG|8", 70, "NATGASUSDT", "LONG", 3.5, 3.4, 4.1, "SENT", 30, {"atr": 0.03})                                           # ціни немає
P = {"BTCUSDT": 60000.0, "ETHUSDT": 1716.0, "SOLUSDT": 95.0, "XRPUSDT": 105.0, "ADAUSDT": 100.0, "LTCUSDT": 41.0}
s = lv.state(db, P, now - 5, now)
assert s["ok"] and s["order_authorized"] is False and s["stale"] is False and s["sums"]["n"] == 7 and s["sums"]["unknown"] == 1 and s["sums"]["if_stop"] == -70, s["sums"]
T = {t["sig_id"]: t for g in s["groups"] for t in g["trades"]}
b = T["SW|BTCUSDT|SHORT|1"]; assert b["now"] == 10.0 and b["to_stop"] == 20.0 and b["if_stop"] == -10 and b["dist_pct"] == 10.0 and b["age"] == "10-й день із 10" and 0 < b["pos"] < 1, b
e = T["SW|ETHUSDT|SHORT|2"]; assert e["now"] == 4.5 and e["rep"] is True, e
l = T["TD|ETHUSDT|LONG|4"]; assert l["now"] == 10.0 and l["strat"] == "ІНТРАДЕЙ" and l["pair"], l
assert T["SW|NATGASUSDT|LONG|8"]["now"] is None and T["SW|XRPUSDT|SHORT|3"]["now"] == -5.0
exp = round(sum(t["now"] for t in T.values() if t["now"] is not None), 0); assert s["sums"]["now"] == exp and s["sums"]["to_stop"] == exp + 60, (s["sums"], exp)
titles = [g["title"] for g in s["groups"]]; assert titles[0] == "СВІНГ · шорти · 5" and s["groups"][0]["sub"] == "одна ставка на падіння" and "ІНТРАДЕЙ · лонги · 1" in titles, titles
att = {a["filter"]: a for a in s["attention"]}
assert att["short"]["title"] == "5 шортів — одна ставка" and "−$50" in att["short"]["detail"] and att["soon"]["title"] == "За часом сьогодні виходить 1 угода" and "BTC" in att["soon"]["detail"] and att["both"]["title"].startswith("ETH — угоди в обидва боки"), att
assert att["near"]["level"] == "red" and att["near"]["title"] == "XRP біля стопа" and T["SW|XRPUSDT|SHORT|3"]["near"] and not T["SW|BTCUSDT|SHORT|1"]["near"] and T["SW|BTCUSDT|SHORT|1"]["soon"] and T["TD|ETHUSDT|LONG|4"]["both"], att
assert lv._pl(1, *lv.UG) == "1 угода" and lv._pl(3, *lv.SH) == "3 шорти" and lv._pl(11, *lv.LG) == "11 лонгів" and lv._pl(21, *lv.UG) == "21 угода" and lv._pl(45, *lv.SH) == "45 шортів"
assert s["lev"] == "Є угоди біля стопа — подивіться першими."            # 5 шортів із 7 — менше ніж 80%, тож про «одну ставку» в заголовку не кажемо
S = {x["sig_id"]: x for x in s["signals"]}
v = S["TD|ETHUSDT|LONG|4"]["lev"]; assert v["title"].startswith("Є застереження") and "частіше правий перший" in v["text"] and "СВІНГ уже тримає SHORT" in v["text"] and "Разом із ним зараз відкрито 2 лонги в один бік" in v["after"], v
assert S["TD|ETHUSDT|SHORT|5"]["status"] == "стоп" and S["TD|BTCUSDT|LONG|6"]["status"] == "ціль" and "SW|BTCUSDT|SHORT|1" not in S            # СВІНГ BTC старший за 48 год — лише у відкритих
c = lv._verdict({"sig_id": "SW|BTCUSDT|SHORT|1", "direction": "SHORT", "entry": 63000.0, "sl": 66000.0, "hyp_json": json.dumps({"atr": 1000.0})}, 4, -40.0, 10.0)
assert c["title"] == "Чистий сигнал на спокійній монеті" and c["calm"] and "буде 5 шортів в один бік" in c["after"] and "−$50" in c["after"], c
s2 = lv.state(db, {}, None, now); assert s2["stale"] is True and s2["sums"]["unknown"] == 7 and s2["sums"]["now"] == 0
z = {r["name"]: r for r in lv.zvirka(db, P, now)["rows"]}
assert z["ІНТРАДЕЙ"]["sl"] == 1 and z["ІНТРАДЕЙ"]["tp"] == 1 and z["ІНТРАДЕЙ"]["time"] == 1 and z["ІНТРАДЕЙ"]["closed_usd"] == 20.0 and z["ІНТРАДЕЙ"]["open"] == 1 and z["ІНТРАДЕЙ"]["open_usd"] == 10.0, z["ІНТРАДЕЙ"]     # −10 +25 +5
assert z["СВІНГ"]["open"] == 6 and z["СВІНГ"]["open_unknown"] == 1 and z["СВІНГ"]["sl"] == 0, z["СВІНГ"]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(root, "office_web", "lev.html"), encoding="utf-8").read(); app = open(os.path.join(root, "office_mini_app.py"), encoding="utf-8").read()
for fn in ("manifest.webmanifest", "sw.js", "icon-180.png", "icon-192.png", "icon-512.png", "lev.jpg"): assert os.path.getsize(os.path.join(root, "office_web", "lev_static", fn)) > 100, fn
mf = json.load(open(os.path.join(root, "office_web", "lev_static", "manifest.webmanifest"), encoding="utf-8")); assert mf["display"] == "standalone" and mf["start_url"] == "/lev/" and len(mf["icons"]) == 2
assert b["opened"] and b["tp_usd"].startswith("+$") and 'rel="manifest"' in html and "apple-touch-icon" in html and "lev_static" in app
assert "/api/lev/state" in html and "/api/lev/zvirka" in html and "Потребує уваги" in html and '"/api/lev/state"' in app and '"/lev"' in app
os.environ["LEV_APP"] = "0"; assert lv.enabled() is False; os.environ["LEV_APP"] = "1"
print("ok lev")

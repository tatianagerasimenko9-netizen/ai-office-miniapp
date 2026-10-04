#!/usr/bin/env python3
"""office_time_structure + office_market_bias на синтетичних свічках (без мережі)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_market_bias as mb  # noqa: E402
import office_time_structure as ts  # noqa: E402

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


def days(start, n, base=100.0, step=1.0):
    out = []
    for i in range(n):
        d = start + timedelta(days=i)
        o = base + i * step
        out.append({"ts": d.isoformat(), "open": o, "high": o + 2, "low": o - 2, "close": o + step})
    return out


def hours(start, n, base=100.0, step=0.1):
    out = []
    for i in range(n):
        d = start + timedelta(hours=i)
        c = base + i * step
        out.append({"ts": d.isoformat(), "open": c - step, "high": c + 0.05, "low": c - step - 0.05, "close": c})
    return out


# ---- час: середа 2026-10-07 14:30 UTC; тиждень з 05.10, місяць з 01.10, квартал з 01.10
D0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
dly = days(D0, 70)   # до 09.10 включно
now = datetime(2026, 10, 7, 14, 30, tzinfo=timezone.utc)
px = 160.0
s = ts.snapshot(now.timestamp(), px, dly)
w, m, q = s["week"], s["month"], s["quarter"]
wo_expect = [c for c in dly if c["ts"].startswith("2026-10-05")][0]["open"]
mo_expect = [c for c in dly if c["ts"].startswith("2026-10-01")][0]["open"]
check(w["open"] == wo_expect, f"weekly open {w['open']} != {wo_expect}")
check(m["open"] == mo_expect and q["open"] == mo_expect, "monthly/quarterly open (жовтень = початок кварталу)")
check(abs(w["dist_open_pct"] - (px / wo_expect - 1) * 100) < 0.01, "відстань від Weekly Open у %")
check(s["weekday"] == "середа", s["weekday"])
check(w["phase"] == "MID_WEEK" and m["phase"] == "MID_MONTH" and q["phase"] == "QUARTER_OPEN", (w["phase"], m["phase"], q["phase"]))
check(abs(w["hours_to_close"] - (datetime(2026, 10, 12, tzinfo=timezone.utc) - now).total_seconds() / 3600) < 0.01, "час до закриття тижня")
check(w["prev"] and abs(w["prev"]["open"] - [c for c in dly if c["ts"].startswith("2026-09-28")][0]["open"]) < 1e-9, "попередній тиждень: open")
check(m["prev"] and m["prev"]["high"] >= m["prev"]["low"], "попередній місяць: H/L")

# неділя ввечері + кінець місяця й кварталу → перетин WEEK_CLOSE + MONTH_CLOSE + QUARTER_CLOSE
now2 = datetime(2026, 12, 27, 21, 0, tzinfo=timezone.utc)   # неділя, до 31.12 ще 4 дні
dly2 = days(datetime(2026, 9, 1, tzinfo=timezone.utc), 120)
s2 = ts.snapshot(now2.timestamp(), 200.0, dly2)
check(s2["week"]["phase"] == "WEEK_CLOSE", s2["week"]["phase"])
now3 = datetime(2026, 9, 27, 21, 0, tzinfo=timezone.utc)     # неділя, 30.09 через 2,1 дня
s3 = ts.snapshot(now3.timestamp(), 150.0, dly2)
check(s3["month"]["phase"] == "MID_MONTH" and s3["week"]["phase"] == "WEEK_CLOSE", (s3["month"]["phase"], s3["week"]["phase"]))
now4 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
s4 = ts.snapshot(now4.timestamp(), 150.0, dly2)
check(s4["month"]["phase"] == "MONTH_CLOSE" and s4["quarter"]["phase"] == "QUARTER_CLOSE", (s4["month"]["phase"], s4["quarter"]["phase"]))
now5 = datetime(2026, 9, 27, 23, 0, tzinfo=timezone.utc)
now5 = datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc) - timedelta(hours=1)
check(ts.snapshot(now4.timestamp(), 150.0, dly2)["closing"] == ["month", "quarter"], ts.snapshot(now4.timestamp(), 150.0, dly2)["closing"])

# нема свічки першого дня періоду → Open не вигадуємо
cut = [c for c in dly if not c["ts"].startswith("2026-10-05")]
sc = ts.snapshot(now.timestamp(), px, cut)
check(sc["week"]["open"] is None and sc["week"]["dist_open_pct"] is None, "без свічки відкриття тижня Open = None")
check(ts.snapshot(now.timestamp(), px, [])["week"]["open"] is None, "порожньо → None")

# прийняття Weekly Open за годинними закриттями
hh = hours(datetime(2026, 10, 5, tzinfo=timezone.utc), 60, base=wo_expect - 0.5, step=0.05)
sa = ts.snapshot(now.timestamp(), px, dly, hourly=hh)
check(sa["week"].get("accept") and sa["week"]["accept"]["hours"] >= 6, sa["week"].get("accept"))

# текст: цифри, без загальних слів
ln = ts.lines(s, "BTC")
check(any(x.startswith("До закриття тижня") for x in ln), ln)
check(any("вище Weekly Open" in x or "нижче Weekly Open" in x for x in ln), ln)
check(not any("може впливати" in x for x in ln), ln)

# ---- ринок
T0 = datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)
up = hours(T0, 30, base=100, step=0.3)        # +~1.2% за 4 год
dn = hours(T0, 30, base=100, step=-0.3)
fl = hours(T0, 30, base=100, step=0.0)
basket_up = {f"C{i}": up for i in range(10)}
basket_dn = {f"C{i}": dn for i in range(10)}
m_long = mb.assess(btc_1h=up, eth_1h=up, basket_1h=basket_up, btc_week_dist_pct=0.6)
check(m_long["bias"] == "LONG" and m_long["long"] == 4 and m_long["short"] == 0 and m_long["checked"] == 4, m_long)
m_short = mb.assess(btc_1h=dn, eth_1h=dn, basket_1h=basket_dn, btc_week_dist_pct=-0.6)
check(m_short["bias"] == "SHORT", m_short)
m_mix = mb.assess(btc_1h=up, eth_1h=dn, basket_1h={f"C{i}": (up if i % 2 else dn) for i in range(10)}, btc_week_dist_pct=0.0)
check(m_mix["bias"] == "MIXED", m_mix)
check(mb.assess(btc_1h=[], eth_1h=[])["bias"] == "UNKNOWN", "без даних — UNKNOWN, не вигадуємо")
check(mb.assess(btc_1h=fl, eth_1h=fl, basket_1h={f"C{i}": fl for i in range(10)}, btc_week_dist_pct=0.05)["bias"] == "MIXED", "плоский ринок")

al = mb.alignment(m_long, direction="LONG", coin="SOON", coin_1h=hours(T0, 30, base=100, step=0.7), btc_1h=up)
check(al["state"] == "WITH" and al["rel_pp"] > 0, al)
ln2 = mb.signal_lines(m_long, al)
check(ln2[0].startswith("Ринок: перевага LONG") and any("сильніший за BTC" in x for x in ln2) and ln2[-1] == "Напрямок: разом із ринком ✅", ln2)
al2 = mb.alignment(m_long, direction="SHORT", coin="ALGO", coin_1h=dn, btc_1h=up)
check(al2["state"] == "COUNTER" and mb.signal_lines(m_long, al2)[-1].startswith("Напрямок: проти ринку"), al2)
check(mb.alignment(m_mix, direction="LONG", coin="X", coin_1h=up, btc_1h=up)["state"] == "MIXED", "змішаний")
check(mb.alignment(m_long, direction="LONG", coin="X", coin_1h=up, btc_1h=up, corr_btc=0.1)["state"] == "INDEPENDENT", "незалежна монета")
check(mb.signal_lines({"bias": "UNKNOWN"}, al) == [], "немає висновку про ринок — рядків немає")

# кореляція
import math  # noqa: E402

a = [{"close": 100 + math.sin(i / 3) * 3 + i * 0.01} for i in range(60)]
check(mb.corr(a, a) is not None and mb.corr(a, a) > 0.99, "corr(a,a)")
check(mb.corr(a[:5], a[:5]) is None, "замало даних")

# портфель
pl = mb.portfolio([{"direction": "SHORT"}] * 8 + [{"direction": "LONG"}] * 2, corrs={"A": 0.8, "B": 0.7})
check(pl["long"] == 2 and pl["short"] == 8 and "8 із 10" in pl["warning"] and "одна спільна ставка" in pl["warning"], pl)
check(mb.portfolio([{"direction": "LONG"}, {"direction": "SHORT"}])["warning"] == "", "мало планів — без попередження")

# огляд
br = mb.brief_lines(m_long, mb.portfolio([{"direction": "LONG"}] * 4 + [{"direction": "SHORT"}] * 7))
check(br[0] == "📊 РИНОК ЗАРАЗ" and br[1] == "Перевага: LONG" and br[-1] == "Висновок: ринок зараз більше підтримує LONG." and any("Активні плани: 4 LONG / 7 SHORT" in x for x in br), br)
check(len(br) <= 9, len(br))

# мова: жодного жаргону у виводі
import office_language as lang  # noqa: E402

for t in ln + br + ln2 + mb.signal_lines(m_long, al2):
    bad = lang.problems(t)
    check(not bad, (t, bad))

if fails:
    print("FAIL:")
    for f in fails:
        print("  ", f)
    sys.exit(1)
print("OK time/market: Weekly/Monthly/Quarterly, фази, перетини, лічильники, відповідність, портфель, огляд, мова")

# ---- реальний випадок 04.10 17:35 UTC (MERL/XMR/SOON): BTC 4 год +0,16%, ETH +0,10%, BTC +1,07% від Weekly Open, 12 із 20 монет ростуть
def flat(total_pct, n=40):
    return [{"close": 100.0 * (1 + total_pct / 100.0 * max(0, i - (n - 17)) / 16.0) if i >= n - 17 else 100.0, "open": 100.0, "high": 100.0, "low": 100.0, "ts": "x"} for i in range(n)]


bk = {f"U{i}": flat(0.8) for i in range(12)}
bk.update({f"D{i}": flat(-0.5) for i in range(8)})
mr = mb.assess(btc_1h=flat(0.16), eth_1h=flat(0.10), basket_1h=bk, btc_week_dist_pct=1.07, bph=4)
check(mr["bias"] == "MIXED" and mr["long"] == 2 and mr["short"] == 0 and mr["checked"] == 4, ("2 із 4 за LONG без відриву більшості — це не «перевага LONG»", mr))
check(abs(mr["btc_4h"] - 0.16) < 0.01, mr["btc_4h"])
brr = mb.brief_lines(mr)
check(brr[1] == "Перевага: ЗМІШАНА" and brr[-1] == "Висновок: чіткої переваги немає.", brr)

# ---- картка READY із реальними рядками ринку: порядок і зміст
import office_user_messages as um  # noqa: E402

al3 = mb.alignment(mr, direction="LONG", coin="SOON", coin_1h=flat(0.47), btc_1h=flat(0.08), bph=4)
card = um.ready_signal(symbol="SOONUSDT", direction="LONG", entry=0.3617, sl=0.35426, tp1=0.3729, tp2=0.3809, valid_until="05.10 20:35",
                       setup="Спадний клин", why=["Вхід 0,3617 — у зоні 0,3614–0,3622"], market=mb.signal_lines(mr, al3) + ts.lines(s, "BTC"))
check("Ринок: перевага ЗМІШАНА (2 за LONG, 0 за SHORT, 2 без руху — із 4)" in card and "Напрямок: ринок змішаний, переваги немає" in card, card)
check(card.index("Ринок:") < card.index("Вхід:"), "ринок — до рівнів")
for t in card.split("\n"):
    check(not lang.problems(t), (t, lang.problems(t)))
print(card)

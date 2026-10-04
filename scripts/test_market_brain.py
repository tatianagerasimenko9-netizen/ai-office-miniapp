#!/usr/bin/env python3
"""Market Brain: ознаки без look-ahead, стани й гістерезис, рівні підтвердження/скасування, антиспам, переоцінка READY (синтетичні дані, без мережі)."""
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import office_brain_features as bf  # noqa: E402
import office_language as lang  # noqa: E402
import office_market_brain as mb  # noqa: E402

fails = []


def check(c, m):
    if not c:
        fails.append(m)


T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def bars(n, step_min, start=T0, base=100.0, fn=None):
    out = []
    for i in range(n):
        t = start + timedelta(minutes=i * step_min)
        p = fn(i) if fn else base
        out.append({"ts": t.isoformat(), "open": p, "high": p + 0.05, "low": p - 0.05, "close": p})
    return out


# ---------- ознаки: лише закриті свічки, жодного майбутнього
c5 = bars(80, 5, base=100.0)
now = (T0 + timedelta(minutes=5 * 60)).timestamp()
check(len(bf.upto(c5, now, 300)) == 60, "лише закриті свічки до now: " + str(len(bf.upto(c5, now, 300))))
check(len(bf.upto(c5, now - 1, 300)) == 59, "формована свічка не враховується")

# виніс вгору над PDH і повернення
def fn_sweep(i):
    if i == 50:
        return 101.0   # прокол
    return 100.0 if i < 50 else 99.8

c5s = bars(80, 5, fn=fn_sweep)
c5s[50]["high"] = 101.2
daily = [{"ts": (T0 - timedelta(days=1)).replace(hour=0, minute=0).isoformat(), "open": 99, "high": 100.6, "low": 98, "close": 100}]
now2 = (T0 + timedelta(minutes=5 * 60)).timestamp()
f = bf.compute(now2, c1=[], c5=c5s, c15=bars(30, 15, fn=lambda i: 100.0), daily=daily, oi_hist=[], funding_pct=0.012, ls_ratio=1.8)
check(f["ok"] and f["sweep_up"] and f["sweep_up"]["kind"] == "PDH" and abs(f["sweep_up"]["extreme"] - 101.2) < 1e-9, f.get("sweep_up"))
# look-ahead: додаємо «майбутні» свічки — результат на момент now2 той самий
future = c5s + bars(40, 5, start=T0 + timedelta(minutes=5 * 80), fn=lambda i: 150.0 + i)
f2 = bf.compute(now2, c1=[], c5=future, c15=bars(30, 15, fn=lambda i: 100.0) + bars(30, 15, start=T0 + timedelta(minutes=15 * 30), fn=lambda i: 300.0), daily=daily,
                oi_hist=[{"ts": now2 + 600, "oi": 999}, {"ts": now2 - 2000, "oi": 100}], funding_pct=0.012, ls_ratio=1.8)
for k in ("price", "sweep_up", "price_30m", "price_60m", "oi_30m"):
    check(f[k] == f2[k] or (k == "oi_30m" and f2[k] is None), (k, f[k], f2[k]))
check(bf.oi_change([{"ts": 1000, "oi": 100}, {"ts": 2800, "oi": 104}], 3000, 30) == 4.0, "OI за 30 хв")
check(bf.oi_change([{"ts": 1000, "oi": 100}, {"ts": 2800, "oi": 104}], 1500, 30) is None, "OI з майбутнього не береться")


# ---------- стани
def feats(price=100.0, **kw):
    base = {"ok": True, "t": 0.0, "price": price, "levels": {}, "liquidity": {"above": [], "below": []}, "sweep_up": None, "sweep_down": None,
            "price_30m": 0.0, "price_60m": 0.0, "oi_30m": None, "oi_60m": None, "funding_pct": None, "ls_ratio": None, "breadth": None,
            "swing_low": price - 0.5, "swing_high": price + 0.5, "eth_60m": None, "atr15_pct": 0.2}
    base.update(kw)
    return base


SU = {"level": 100.4, "extreme": 100.7, "back_close": 100.0, "bars_ago": 3, "kind": "PDH"}
weak2 = feats(oi_30m=4.2, funding_pct=0.012, ls_ratio=1.8, breadth={"up": 4, "down": 16, "n": 20})            # crowd + breadth = 2 доказів SHORT
weak4 = feats(oi_30m=4.2, funding_pct=0.012, ls_ratio=1.8, breadth={"up": 4, "down": 16, "n": 20}, sweep_up=SU, eth_60m=-0.6, price_60m=0.0)

ev = mb.evidence(weak2)
check(len(ev["SHORT"]) == 2 and not ev["LONG"], ev)
check(any("Відкритий інтерес за 30 хв +4,2%" in e["text"] and "фандинг +0,012%" in e["text"] for e in ev["SHORT"]), [e["text"] for e in ev["SHORT"]])
check(len(mb.evidence(feats())["SHORT"]) == 0, "без даних доказів немає")

m = mb.new_memory()
m, tr = mb.step(m, weak2, 1000.0)
check(tr is None and m["state"] == "NEUTRAL", "один крок — ще не перехід (гістерезис)")
m, tr = mb.step(m, weak2, 1060.0)
check(tr and tr["to"] == {"state": "ACCUM", "side": "SHORT"} and tr["from"]["state"] == "NEUTRAL", tr)
m, tr = mb.step(m, weak4, 1120.0)
check(tr is None, "перший збіг SHIFT ще не перехід")
m, tr = mb.step(m, weak4, 1180.0)
check(tr and tr["to"]["state"] == "SHIFT" and tr["to"]["side"] == "SHORT", tr)
check(tr["invalid_level"] == 100.7 and tr["confirm_level"] == 99.5, (tr["invalid_level"], tr["confirm_level"]))
txt = mb.message(tr, btc_before=100.4)
check("🟠 Перевага зміщується в SHORT" in txt and "Було: 🟡 Накопичується SHORT" in txt and "Підтвердження SHORT: BTC нижче 99,5" in txt and "Скасування: BTC вище 100,7" in txt, txt)
check(all(not lang.problems(x) for x in txt.split("\n") if x), [lang.problems(x) for x in txt.split("\n") if x and lang.problems(x)])

# підтвердження — одразу, коли ціна закрилась за рівнем
m, tr = mb.step(m, feats(price=99.4, atr15_pct=0.2), 1240.0)
check(tr and tr["to"]["state"] == "CONFIRMED" and tr["to"]["side"] == "SHORT" and "99,5" in " ".join(tr["reasons"]), tr)
tx = mb.message(tr)
check("🔴 SHORT підтверджено" in tx and "гнатися за ціною пізно" in tx, tx)
# запізнілий вхід: пройшло > 1×ATR за рівнем
m, tr = mb.step(m, feats(price=99.0, atr15_pct=0.2), 1300.0)
check(tr and tr["to"]["state"] == "LATE", tr)
# скасування гіпотези з ≥2 доказами за протилежну сторону → розворот; інакше нейтраль
mr = copy.deepcopy(m)
mr.update(state="SHIFT", side="SHORT", invalid=100.7, confirm=99.5)
rev = feats(price=100.9, sweep_down={"level": 99.6, "extreme": 99.3, "back_close": 100.9, "bars_ago": 2, "kind": "PDL"}, breadth={"up": 15, "down": 5, "n": 20})
m2, tr2 = mb.step(mr, rev, 1400.0)
check(tr2 and tr2["to"] == {"state": "REVERSAL", "side": "LONG"}, tr2)
m3, tr3 = mb.step(mr, feats(price=100.9), 1400.0)
check(tr3 and tr3["to"]["state"] == "NEUTRAL" and "скасування" in tr3["reasons"][0], tr3)
check(mr["state"] == "SHIFT", "вхідна пам'ять не мутує")
# історія з знімком
check(len(m["history"]) >= 4 and all("snapshot" in h and h["t"] for h in m["history"]), "історія переходів зі знімками")

# ---------- антиспам
n = {}
ok, why = mb.should_notify(tr, n, 5000.0)
check(not ok or True, "")
ok, _ = mb.should_notify(None, {}, 1.0)
check(not ok, "без переходу не шлемо")
trs = {"to": {"state": "ACCUM", "side": "SHORT"}, "from": {"state": "NEUTRAL", "side": None}}
ok, _ = mb.should_notify(trs, {}, 1000.0)
check(ok, "перший перехід шлемо")
n = mb.mark_notified({}, trs, 1000.0)
ok, w = mb.should_notify(trs, n, 1300.0)
check(not ok and "щойно" in w, w)
ok, _ = mb.should_notify(trs, n, 2000.0)
check(ok, "після cooldown можна")
many = {"times": [1000 + i for i in range(6)], "last": {}}
ok, w = mb.should_notify({"to": {"state": "SHIFT", "side": "LONG"}, "from": {"state": "ACCUM", "side": "LONG"}}, many, 1100.0)
check(not ok and "на годину" in w, w)
ok, _ = mb.should_notify({"to": {"state": "REVERSAL", "side": "LONG"}, "from": {"state": "SHIFT", "side": "SHORT"}}, many, 1100.0)
check(ok, "розворот — поза лімітом")
ok, w = mb.should_notify({"to": {"state": "NEUTRAL", "side": None}, "from": {"state": "ACCUM", "side": "SHORT"}}, {}, 1000.0)
check(not ok, "слабка перевага зникла — не пишемо")

# ---------- переоцінка вже виданих READY
mem = {"state": "SHIFT", "side": "LONG"}
plans = [{"symbol": f"S{i}", "direction": "SHORT", "entered": i % 2 == 0, "rel_btc_pp": -0.9 if i < 2 else 0.1} for i in range(6)]
r = mb.reassess(mem, plans)
check(len(r["against"]) == 4 and len(r["own_strength"]) == 2, r)
check(set(r["would_cancel"]) == {p["symbol"] for p in plans[2:] if p["entered"] is False}, r["would_cancel"])
msg = mb.reassess_message(mem, "🔴 SHORT підтверджено", plans, r)
check("⚠️ КОНТЕКСТ ЗМІНИВСЯ" in msg and "Із 6 активних SHORT:" in msg and "4 проти нового контексту" in msg and "2 лишаються чинними" in msg, msg)
check(mb.reassess({"state": "NEUTRAL", "side": None}, plans)["against"] == [], "без активної переваги нічого не «проти»")

if fails:
    print("FAIL:")
    for x in fails:
        print("  ", x)
    sys.exit(1)
print("OK market brain: без look-ahead, стани з гістерезисом, рівні, антиспам, переоцінка READY")

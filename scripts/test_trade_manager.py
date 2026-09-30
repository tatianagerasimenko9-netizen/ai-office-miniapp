#!/usr/bin/env python3
"""Ведення позначеної угоди до кінця руху: беззбиток → TP1 40% → TP2 30% → runner (трейлінг за HL/LH, кінець за зламом структури H1) → добір → перезахід."""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["OFFICE_DEPO_USDT"] = "1000"
os.environ["OFFICE_EXINFO_SEED"] = "1"
import office_trade_manager as TM  # noqa: E402

T0 = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc).timestamp()
H = 3600.0


def h1(spec, t0=T0):
    """spec: (low, high, close) на годину; open = попереднє закриття."""
    out, prev = [], spec[0][2]
    for i, (lo, hi, cl) in enumerate(spec):
        out.append({"ts": datetime.fromtimestamp(t0 + i * H, tz=timezone.utc).isoformat(), "open": prev, "high": hi, "low": lo, "close": cl})
        prev = cl
    return out


def texts(res):
    return [(r["code"].split(":")[0], r["text"]) for r in res]


# ---------------- LONG: entry 100, sl 98 (R=2), tp1 103, tp2 106
pos = {"symbol": "AKEUSDT", "direction": "LONG", "entry": 100.0, "sl": 98.0, "tp1": 103.0, "tp2": 106.0, "opened_at": datetime.fromtimestamp(T0, tz=timezone.utc).isoformat()}
base = [(99.5, 100.6, 100.2), (100.0, 101.0, 100.6), (100.4, 101.2, 101.0), (100.8, 101.3, 101.1)]
now = T0 + 40 * H
# тільки рух до 1R (102): беззбиток, без TP
a = TM.advise(pos, h1=h1(base + [(100.9, 102.4, 102.0)]), m15=[], h4=[], now_ts=now, price=102.0)
assert [c for c, _ in texts(a)] == ["BREAKEVEN"] and "стоп → 100" in a[0]["text"], a
# TP1: закрий 40%, стоп у беззбиток
up1 = base + [(100.9, 102.4, 102.0), (101.8, 103.4, 103.2)]
a = TM.advise(pos, h1=h1(up1), m15=[], h4=[], now_ts=now, price=103.2)
codes = [c for c, _ in texts(a)]
assert "TP1" in codes and any("закрий 40%, стоп у беззбиток 100" in t for _, t in texts(a)), a
# уже надіслане не повторюється
a2 = TM.advise(pos, h1=h1(up1), m15=[], h4=[], sent={"BREAKEVEN", "TP1"}, now_ts=now, price=103.2)
assert a2 == [], a2
# TP2: закрий ще 30%, стоп на TP1; далі runner: HL підтягує стоп
run = up1 + [(106.0, 106.6, 106.4), (106.3, 107.2, 107.0), (105.0, 107.4, 107.2), (106.6, 108.4, 108.2), (106.8, 109.0, 108.8), (107.0, 109.4, 109.2)]   # HL = 105.0
a = TM.advise(pos, h1=h1(run), m15=[], h4=[], sent={"BREAKEVEN", "TP1"}, now_ts=now, price=109.2)
cs = [c for c, _ in texts(a)]
assert "TP2" in cs and any("закрий ще 30%, стоп на TP1 103" in t for _, t in texts(a)), a
a = TM.advise(pos, h1=h1(run), m15=[], h4=[], sent={"BREAKEVEN", "TP1", "TP2"}, now_ts=now, price=109.2)
tr = [x for x in a if x["code"].startswith("TRAIL")]
assert tr and "трейлінг · стоп → 105" in tr[0]["text"], a
# кінець: закриття H1 нижче останнього HL → «злам структури», а не стоп-повідомлення про закриття
brk = run + [(103.0, 106.0, 104.0)]
a = TM.advise(pos, h1=h1(brk), m15=[], h4=[], sent={"BREAKEVEN", "TP1", "TP2", "TRAIL:105.0"}, now_ts=now, price=104.0)
assert "END_STRUCTURE" in [c for c, _ in texts(a)] and "закрий залишок" in [t for _, t in texts(a)][0], a
# ціна досягла стопа — без слова «закрито»
dn = h1(base + [(97.0, 100.0, 97.5)])
a = TM.advise(pos, h1=dn, m15=[], h4=[], now_ts=now, price=97.5)
assert a and a[-1]["text"] == "🔴 AKE · ціна досягла стопа" and "закрит" not in a[-1]["text"], a
# немає свічок → порад немає
assert TM.advise(pos, h1=[], m15=[], h4=[], now_ts=now) == []

# ---------------- SHORT (LONGXIA-подібний): entry 0.130, sl 0.140, tp1 0.120, tp2 0.110
sp = {"symbol": "LONGXIAUSDT", "direction": "SHORT", "entry": 0.130, "sl": 0.140, "tp1": 0.120, "tp2": 0.110, "opened_at": datetime.fromtimestamp(T0, tz=timezone.utc).isoformat()}
sh = [(0.128, 0.1305, 0.129), (0.125, 0.129, 0.126), (0.118, 0.126, 0.119), (0.1155, 0.121, 0.117), (0.108, 0.118, 0.109),
      (0.1075, 0.1085, 0.1085), (0.1040, 0.1080, 0.1050), (0.1030, 0.1100, 0.1040), (0.0995, 0.1070, 0.1005), (0.0950, 0.1050, 0.0960)]   # TP1 0.120 → TP2 0.110; LH = 0.1100
a = TM.advise(sp, h1=h1(sh), m15=[], h4=[], sent={"BREAKEVEN"}, now_ts=now, price=0.096)
cs = [c for c, _ in texts(a)]
assert "TP1" in cs and "TP2" in cs, a
assert "закрий 40%, стоп у беззбиток 0,13" in [t for c, t in texts(a) if c == "TP1"][0]
a = TM.advise(sp, h1=h1(sh), m15=[], h4=[], sent={"BREAKEVEN", "TP1", "TP2"}, now_ts=now, price=0.096)
tr = [x for x in a if x["code"].startswith("TRAIL")]
assert tr and tr[0]["text"].startswith("📈 LONGXIA · трейлінг · стоп → 0,11"), a
# ---------------- добір: один раз, ретест пробитого рівня з підтвердженням M15
add_h1 = h1([(99.5, 100.6, 100.2), (100.0, 101.0, 100.6), (100.4, 101.5, 100.9), (100.5, 101.0, 100.7), (100.6, 101.2, 101.0),   # свінг-максимум 101.5 (пробитий рівень)
             (100.8, 103.6, 103.4), (102.6, 104.0, 103.8), (102.9, 104.4, 104.0), (103.0, 104.2, 103.9), (101.6, 103.9, 102.0)])
m15 = [{"ts": datetime.fromtimestamp(T0 + 9 * H + i * 900, tz=timezone.utc).isoformat(), "open": 101.7 + i * 0.05, "high": 102.3, "low": 101.55 if i == 3 else 101.7, "close": 101.9 + i * 0.08} for i in range(4)]
m15[3].update({"open": 101.7, "close": 102.2})
ad = TM.advise(pos, h1=add_h1, m15=m15, h4=[], sent={"BREAKEVEN", "TP1"}, now_ts=T0 + 10 * H + 3600, price=102.2)
adds = [x for x in ad if x["code"] == "ADD"]
assert adds and adds[0]["text"].startswith("➕ AKE · добір · 102,2") and "стоп 101" in adds[0]["text"], ad
assert not [x for x in TM.advise(pos, h1=add_h1, m15=m15, h4=[], sent={"BREAKEVEN", "TP1", "ADD"}, now_ts=T0 + 10 * H + 3600, price=102.2) if x["code"] == "ADD"], "добір лише один раз"

# ---------------- перезахід: один раз після стопу, якщо H4-структура ціла й є нове підтвердження; RR ≥ 1,5
def h4rows():
    return [{"ts": datetime.fromtimestamp(T0 - (40 - i) * 4 * H, tz=timezone.utc).isoformat(), "open": 100, "high": 101 + (0.3 if i % 5 == 2 else 0), "low": 99 - (0.6 if i == 20 else 0), "close": 100.4} for i in range(40)]


stop_ts = T0 + 10 * H
mm = [{"ts": datetime.fromtimestamp(stop_ts + i * 900, tz=timezone.utc).isoformat(), "open": 99.0, "high": 99.6, "low": 98.4 if i == 1 else 98.9, "close": 99.3} for i in range(4)]
mm[3].update({"open": 99.4, "high": 100.6, "low": 99.2, "close": 100.5})
re_ = TM.reentry(pos, m15=mm, h4=h4rows(), sent={"STOP_PRICE"}, now_ts=stop_ts + 4 * 900 + 60, stop_alert_ts=stop_ts, tp1=106.0)
assert re_ and re_["code"] == "REENTRY" and re_["text"].startswith("🔄 AKE · перезахід · 100,5"), re_
assert TM.reentry(pos, m15=mm, h4=h4rows(), sent={"STOP_PRICE", "REENTRY"}, now_ts=stop_ts + 4 * 900 + 60, stop_alert_ts=stop_ts, tp1=106.0) is None, "один раз на ідею"
assert TM.reentry(pos, m15=mm, h4=h4rows(), sent={"STOP_PRICE"}, now_ts=stop_ts + 8 * H, stop_alert_ts=stop_ts) is None, "вікно закінчилось"
# RR після комісій < 1,5 → перезаходу немає
assert TM.reentry(pos, m15=mm, h4=h4rows(), sent={"STOP_PRICE"}, now_ts=stop_ts + 4 * 900 + 60, stop_alert_ts=stop_ts, tp1=101.0) is None
print("OK trade manager: breakeven, TP1 40%, TP2 30%, runner trail by HL/LH, structure end, add once, re-entry once")

# ---------------- runner: кінець за зламом структури H4 (старший ТФ)
def h4c(spec, t0=T0 - 12 * 4 * H):
    out, prev = [], spec[0][2]
    for i, (lo, hi, cl) in enumerate(spec):
        out.append({"ts": datetime.fromtimestamp(t0 + i * 4 * H, tz=timezone.utc).isoformat(), "open": prev, "high": hi, "low": lo, "close": cl})
        prev = cl
    return out


H4SPEC = [(99, 100, 99.5)] * 10 + [(104.6, 107, 106), (105.0, 107.4, 106.6), (104.0, 107.5, 105), (105.2, 108, 107.6), (105.8, 109, 108.5), (106.6, 110, 109.4)]
# HL H4 = 104.0; закриття H4 нижче нього після TP2 → кінець (у пласкому H4 до цього — нічого)
h4_break = h4c(H4SPEC + [(101.0, 108.0, 102.0)])
a = TM.advise(pos, h1=h1(run), m15=[], h4=h4_break, sent={"BREAKEVEN", "TP1", "TP2", "TRAIL:105.0"}, now_ts=T0 + 200 * H, price=109.0)
assert "END_STRUCTURE_H4" in [x["code"] for x in a] and "H4" in [x["text"] for x in a if x["code"] == "END_STRUCTURE_H4"][0], a
print("OK trade manager: H4 structure end for the runner")

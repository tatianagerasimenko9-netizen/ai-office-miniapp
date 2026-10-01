"""Еталон Pine (office_pine_ref.py): перевірка семантики Pine на вручну зібраних даних + узгодженість із продакшн-арифметикою."""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import office_pine_parity as pp  # noqa: E402
import office_pine_ref as ref  # noqa: E402
import office_trade_steer as steer  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


# ta.rma: старт із SMA перших n; rsi зростаючого ряду = 100
r = ref.rma([1, 2, 3, 4, 5, 6], 3)
check("rma: na до n-го бару, далі SMA, далі Wilder", r[:2] == [None, None] and abs(r[2] - 2.0) < 1e-12 and abs(r[3] - (4 + 2 * 2.0) / 3) < 1e-12, str(r))
check("rsi зростаючого ряду = 100", ref.rsi(list(range(1, 40)), 14)[-1] == 100.0)
# ta.ema стартує з першого значення
e = ref.ema([10.0, 20.0], 3)
check("ema: старт із першого значення", e[0] == 10.0 and abs(e[1] - (0.5 * 20 + 0.5 * 10)) < 1e-12)
# ema = продакшн ema_last (та сама арифметика старту)
xs = [100 + (i % 7) * 0.3 for i in range(300)]
rows = [{"open": x, "high": x, "low": x, "close": x} for x in xs]
check("ema еталона = ema_last продакшн", abs(ref.ema(xs, 55)[-1] - steer.ema_last(rows, 55)) < 1e-9)
# півот підтверджується через R барів
h = [1, 2, 3, 9, 3, 2, 1, 1, 1, 1]
check("pivothigh(3,3): на барі півота — na, на i+3 — значення", ref.pivot_high(h, 3, 3, 3) is None and ref.pivot_high(h, 3, 3, 6) == 9)
check("crossover: a>b і a[1]<=b[1]; na → false", ref.crossover(2, 1, 1, 1) and not ref.crossover(2, 1, 2, 1) and not ref.crossover(2, None, 1, 1))
# сесії Київ: 07:00 Київ = 04:00 UTC влітку (UTC+3), 05:00 UTC взимку (UTC+2)
check("сесія MO: літо 04:00 UTC, зима 05:00 UTC", ref.in_session(datetime(2026, 7, 1, 4, 0, tzinfo=timezone.utc), 420, 425) and ref.in_session(datetime(2026, 1, 15, 5, 0, tzinfo=timezone.utc), 420, 425)
      and not ref.in_session(datetime(2026, 7, 1, 4, 5, tzinfo=timezone.utc), 420, 425))

# азійський рендж скидається щодня, MO береться з відкриття бару 07:00 Київ
bars = []
t = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
for i in range(96 * 3):
    base = 100 + 10 * (i // 96)            # щодоби рівень +10
    bars.append({"ts": t, "open": base, "high": base + 1, "low": base - 1, "close": base, "volume": 10.0})
    t += timedelta(minutes=15)
out = ref.run(bars)
i_d3 = 96 * 2 + 60                          # третя доба, після азійської сесії (після 07:00 Київ)
check("азійський рендж = остання сесія (не мінімум усіх днів)", out["asian_low"][i_d3] is not None and out["asian_low"][i_d3] >= 119.0, str(out["asian_low"][i_d3]))
check("MO = open бару 07:00 Київ поточної доби", abs(out["mo_price"][i_d3] - 120.0) < 1e-9, str(out["mo_price"][i_d3]))
check("щоденний OTE 0.5 береться з попередньої доби (UTC): (109+111)/2=110", abs(out["ote"][i_d3] - 110.0) < 1e-9 and abs(out["eq"][i_d3] - (109 + 2 * 0.786)) < 1e-9, f"{out['ote'][i_d3]} {out['eq'][i_d3]}")

# повністю детермінований синтетичний прогін + звірка не падає
bars2 = pp.synthetic(n_days=12, seed=3)
o1, o2 = ref.run(bars2), ref.run(bars2)
check("еталон детермінований", all(o1[k] == o2[k] for k in ("sms_bull", "sms_bear", "tap_hi", "tap_lo", "ifvg_bear", "ifvg_bull", "amd_long_high", "ts_long")))
pine, stats = pp.compare(bars2, warmup=250, step=5)
check("звірка рахує всі патерни", len(stats) == 12 and all(s["bars"] > 0 for s in stats.values()))

# продакшн-азійський рендж = Pine на кожному барі (остання сесія, не всі доби)
import office_ict_hunter as _hunter  # noqa: E402

_b3 = pp.synthetic(n_days=6, seed=11)
_ref3 = ref.run(_b3)
_bad = 0
_chk = 0
for _i in range(96, len(_b3), 7):
    _rows = [{"ts": b["ts"].isoformat(), "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": b["volume"]} for b in _b3[: _i + 1]]
    _ar = _hunter._asia_range(_rows)
    _pa, _pl = _ref3["asian_high"][_i], _ref3["asian_low"][_i]
    _chk += 1
    if _pa is None or _ar["high"] is None:
        _bad += 0 if (_pa is None and _ar["high"] is None) else 1
    elif abs(_ar["high"] - _pa) > 1e-9 or abs(_ar["low"] - _pl) > 1e-9:
        _bad += 1
check("азійський рендж Python = Pine на кожному перевіреному барі", _chk > 50 and _bad == 0, f"розбіжностей {_bad} з {_chk}")
# дві доби з різним рівнем: береться остання сесія, а не мінімум усіх діб
_two = []
_t = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
for _i in range(96 * 2):
    _lvl = 100.0 if _i < 96 else 150.0
    _two.append({"ts": (_t + timedelta(minutes=15 * _i)).isoformat(), "open": _lvl, "high": _lvl + 1, "low": _lvl - 1, "close": _lvl, "volume": 1.0})
_ar2 = _hunter._asia_range(_two)
check("дві доби: рендж останньої сесії (150±1), не мінімум 99", _ar2 == {"high": 151.0, "low": 149.0}, str(_ar2))

# одноразова звірка на «реальних» свічках: архів підставлено, результат у БД, повтору нема
import io  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402
from office_bridge import init_office_db, _fetchall  # noqa: E402

_rnd = random.Random(5)
_px = [100.0]


def _zip_for(day):
    d0 = datetime.fromisoformat(day + "T00:00:00+00:00")
    lines = []
    for i in range(96):
        t = d0 + timedelta(minutes=15 * i)
        o = _px[0]
        c = o * (1 + _rnd.gauss(0, 0.003))
        _px[0] = c
        lines.append(f"{int(t.timestamp() * 1000)},{o},{max(o, c) * 1.001},{min(o, c) * 0.999},{c},{100 * (1 + 30 * abs(c / o - 1))},0,0,0,0,0,0")
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", "\n".join(lines))
    return b.getvalue()


_cache = {}


def _getter(url):
    day = "-".join(url.rsplit("-", 3)[-3:]).replace(".zip", "")
    if day not in _cache:
        _cache[day] = _zip_for(day)
    return _cache[day]


_db = os.path.join(tempfile.mkdtemp(), "p.db")
init_office_db(_db)
_msgs = []
check("одноразова звірка виконується вперше", pp.run_once(_db, printer=_msgs.append, getter=_getter, days=8, step=10) is True)
_ev = [json.loads(r[0]) for r in _fetchall(_db, "SELECT payload_json FROM office_events WHERE event_type = ?", ("LAUNCH_DIAG",))]
_par = [e for e in _ev if e.get("task") == "pine_parity"]
check("у БД по кожному символу є результат із патернами й рівнями", len(_par) == len(pp.SYMBOLS) and all(("patterns" in e and "levels" in e) or "error" in e for e in _par), str(_par[:1])[:300])
check("жоден символ не впав із помилкою", all("error" not in e for e in _par), str([e.get("error") for e in _par]))
check("повторний запуск нічого не робить", pp.run_once(_db, printer=_msgs.append, getter=_getter, days=8, step=10) is False)

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)

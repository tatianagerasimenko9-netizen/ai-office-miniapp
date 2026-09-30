#!/usr/bin/env python3
"""Replay угод журналу у вікні ±2 год від запису (LONGXIA/ENA), одноразова діагностика запуску (маркер у БД, повтору нема), календар із запасною адресою."""
import io
import os
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")

import office_replay as rp  # noqa: E402
import office_launch_once as lo  # noqa: E402
import office_calendar as cal  # noqa: E402
from office_bridge import init_office_db, _fetchall  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def make_zip(day, path):
    d0 = datetime.fromisoformat(day + "T00:00:00+00:00")
    lines = []
    for i in range(96):
        t = d0 + timedelta(minutes=15 * i)
        o, c = path(t), path(t + timedelta(minutes=15))
        lines.append(f"{int(t.timestamp() * 1000)},{o},{max(o, c) * 1.001},{min(o, c) * 0.999},{c},100,0,0,0,0,0,0")
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", "\n".join(lines))
    return b.getvalue()


# ціна: стоїть на 100 до 13:00 UTC 2026-09-29, потім повільно росте до 106 і тримається
BASE = datetime(2026, 9, 29, tzinfo=timezone.utc)


def price(t):
    h = (t - BASE).total_seconds() / 3600.0
    if h < 13:
        return 100.0
    return min(100.0 + (h - 13) * 0.6, 106.0)


def getter(url):
    day = "-".join(url.rsplit("-", 3)[-3:]).replace(".zip", "")
    if day >= "2026-09-30":
        raise OSError("ще нема в архіві")
    return make_zip(day, price)


db = os.path.join(tempfile.mkdtemp(), "t.db")
init_office_db(db)
import sqlite3  # noqa: E402

con = sqlite3.connect(db)
cols = [r[1] for r in con.execute("PRAGMA table_info(trade_journal)")]
check("таблиця trade_journal є в схемі", {"ts_open_utc", "entry_price", "stop_loss", "take_profit", "r_multiple"} <= set(cols), str(cols))


def add(tid, ts, sym, dr, en, sl, tp, rm=None, oc="OPEN"):
    con.execute("INSERT INTO trade_journal (trade_id, ts_open_utc, symbol, direction, entry_price, stop_loss, take_profit, outcome, r_multiple, status, mistake_tags_json, context_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, ts, sym, dr, en, sl, tp, oc, rm, "CLOSED", "[]", "{}"))


# вхід 100 торкається ціни ДО 13:00 (вона стоїть на 100); запис о 14:00 → вхід був на годину раніше, у вікні ±2 год
add("lx1", "2026-09-29T14:00:00+00:00", "龙虾USDT", "LONG", 100.0, 96.0, 104.0, 1.2, "WIN")
# вхід 100 торкається ціни о 12:00; запис о 16:30 (через 4,5 год) — поза вікном ±2 год
add("lx2", "2026-09-29T16:30:00+00:00", "龙虾USDT", "LONG", 100.0, 96.0, 104.0)
add("en1", "2026-09-29T12:30:00+00:00", "ENAUSDT", "LONG", 100.0, 96.0, 103.0)
add("xx1", "2026-09-29T12:30:00+00:00", "SENAUSDT", "LONG", 100.0, 96.0, 103.0)     # не ENAUSDT — не має потрапити
con.commit()
con.close()

cases = rp.journal_cases(db)
check("з журналу взято LONGXIA (2) і ENA (1); схожий символ SENAUSDT — ні", sorted(c["label"] for c in cases) == ["ENA", "LONGXIA", "LONGXIA"], str([(c["label"], c["symbol"]) for c in cases]))
check("вікно ±2 год задано", all(c["window_before_sec"] == 7200 and c["window_after_sec"] == 7200 for c in cases))
check("фактичний результат з журналу збережено для порівняння", [c["actual"] for c in cases if c["trade_id"] == "lx1"][0]["r_multiple"] == 1.2)

lines = []
res = rp.run_journal(db, getter=getter, printer=lines.append)
by = {r["trade_id"]: r for r in res}
check("запис о 14:00, ціна торкалась входу о 12:45–13:00 → вхід у вікні −2 год знайдено (FILLED)", by["lx1"]["result"]["status"] == "FILLED", str(by["lx1"]["result"])[:200])
check("запис через 4,5 год після торкання → поза вікном → NOT_FILLED (чесно)", by["lx2"]["result"]["status"] == "NOT_FILLED", str(by["lx2"]["result"])[:200])
check("ENA у вікні → FILLED", by["en1"]["result"]["status"] == "FILLED")
tl = by["lx1"]["result"].get("timeline") or []
check("ведення: є порада по цілі 1 (ціна дійшла до 104) і беззбиток/стоп-логіка з кодом", any(x["code"].startswith("TP1") for x in tl) or any("BREAKEVEN" in x["code"] for x in tl), str([x["code"] for x in tl]))
check("у рядках звіту — фактичний R і хронологія", any("R=1.2" in ln for ln in lines) and any("TP1" in ln or "беззбиток" in ln.lower() or "40%" in ln for ln in lines), "\n".join(lines)[:500])
check("пошуку за вікном немає слів «закрито» без підтвердження", not any("закрито" in (x["text"] or "").lower() for r in res for x in (r["result"].get("timeline") or [])))

# --- календар: основна адреса недоступна → дзеркало ---
calls = []


def fake_one(url):
    calls.append(url)
    if "nfs.faireconomy" in url and "cdn-" not in url:
        raise OSError("основна недоступна")
    now = datetime.now(timezone.utc) + timedelta(days=1)
    return cal.parse([{"title": "CPI", "country": "USD", "date": now.isoformat(), "impact": "High"}])


cal._fetch_one = fake_one
cal.set_events_for_tests(None)
cal._CACHE["fail_at"] = 0.0
d = cal.diagnose()
check("diagnose: основна ✗, дзеркало ✓ → загалом ok", d["ok"] is True and d["sources"][0]["ok"] is False and any(s["ok"] and s["high_usd_events"] == 1 for s in d["sources"]), str(d))
ev = cal._fetch()
check("_fetch бере дзеркало, коли основна не відповіла", len(ev) == 1 and any("cdn-nfs" in c for c in calls))
cal._fetch_one = lambda u: (_ for _ in ()).throw(OSError("усе лягло"))
check("усі адреси недоступні → diagnose чесно ok=False", cal.diagnose()["ok"] is False)
cal._fetch_one = fake_one

# --- одноразовість ---
out = []
check("одноразова діагностика виконується вперше", lo.run(db, printer=out.append, getter=getter) is True)
rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = 'LAUNCH_DIAG'", ())
import json  # noqa: E402

tasks = [json.loads(r[0])["task"] for r in rows]
check("у БД: маркер, календар, ліквідації, стабільність, replay журналу (3 угоди), done", all(t in tasks for t in ("marker", "calendar", "liq_map", "stability", "done")) and tasks.count("replay_journal") == 3, str(tasks))
check("повторний запуск НІЧОГО не повторює", lo.run(db, printer=out.append, getter=getter) is False and len(_fetchall(db, "SELECT 1 FROM office_events WHERE event_type = 'LAUNCH_DIAG'", ())) == len(rows))

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)

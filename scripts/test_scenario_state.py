#!/usr/bin/env python3
"""Єдиний людський стан сценарію (LSK-подібні дані): «План готовий» лише за суворих умов, без суперечностей,
без жаргону; цілі 2/3 за рівнями (не вигадані); список ніколи не каже «готовий». Офлайн."""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
from datetime import datetime, timezone  # noqa: E402
import office_scenario_state as S  # noqa: E402
_build = S.build
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
S.build = lambda *a, **k: _build(*a, now=NOW, **k)  # час фіксований: тест не залежить від годинника
import office_targets as T  # noqa: E402
from office_lev_watch import check_plan  # noqa: E402

SYM = "LSKUSDT"
ROW = {"signal_id": "SCN|LSKUSDT|LONG|H1|54994d1a", "symbol": SYM, "direction": "LONG", "entry_low": 0.30028, "entry_high": 0.30525,
       "sl": 0.29531, "tp1": 0.31393, "tp2": None, "status": "ACTIVE", "ts_created": "2026-09-29T11:11:40+00:00",
       "analysis_note": "ЛЕВ cancel=0.2953189 ckey=LSKUSDT|LONG|0.30028|0.30525 origin=desk tf=H1 scenario_id=SCN|LSKUSDT|LONG|H1|54994d1a"}
THESIS = {"invalidation": "закриття за 0.295319", "confirmation": "Чекаю на M15: подвійне дно або SFP у зоні"}
FRESH = {"price": 0.3106, "fresh": True, "as_of": "2026-09-29T11:45:00+00:00"}
STALE = {"price": None, "fresh": False, "as_of": None}
BAD = re.compile(r"WATCHING|LONG|SHORT|Risk Officer|shadow|SFP|TTL|CONFIRMED|ACTIVE|SCN\||sc_ote|COMPRESSION|regime|RR\b|scenario_id", re.I)


def texts(v):
    keys = ("headline", "wait", "cancel", "next", "prelim_note", "state_ua")
    return " ".join(str(v.get(k) or "") for k in keys) + " " + " ".join(v.get("prelim") or []) + " " + " ".join(v.get("missing") or [])


# 1. Реальний LSK (ACTIVE, ціна вища за зону): «Чекаємо», умова й скасування прочитані з тези/примітки, без суперечностей
v = S.build(ROW, thesis=THESIS, price=FRESH, plan_check=check_plan)
assert v["state"] == "WAIT" and v["icon"] == "🟡" and "не купувати" in v["headline"] and "вища" in v["headline"], v
assert "0,30028–0,30525 $" in v["wait"] and "15-хвилинному" in v["wait"] and "0,29531" in v["cancel"] and "нижче" in v["cancel"], v
assert "plan" not in v and v["prelim"][0].startswith("Ціль 1: 0,3139") and "немає обґрунтованої" in v["prelim"][1]
assert "не підтверджено" in v["next"], "без перевіреної доставки не обіцяємо «напишу сам»"
assert not BAD.search(texts(v)), BAD.search(texts(v)).group(0)

# 2. Немає рівня скасування й умови підтвердження → «План не готовий» з переліком (а не «план активний»)
row2 = {**ROW, "analysis_note": "службові метадані", "sl": None}
v = S.build(row2, thesis=None, price=FRESH)
assert v["state"] == "NOT_READY" and len(v["missing"]) >= 2 and "не визначено рівень скасування" in v["missing"], v
assert "Зараз не входити" in v["headline"] and "готовий" not in v["state_ua"].lower().replace("не готовий", "")

# 3. Ціна в зоні
v = S.build(ROW, thesis=THESIS, price={**FRESH, "price": 0.3040})
assert v["state"] == "IN_ZONE" and "ще немає" in v["headline"]

# 4. Немає свіжої ціни → «Даних немає» (ніколи не готовий план)
for st in ("ACTIVE", "CONFIRMED", "WATCHING"):
    v = S.build({**ROW, "status": st, "analysis_note": ROW["analysis_note"] + " confirmed_px=0.3035"}, thesis=THESIS, price=STALE)
    assert v["state"] == "NO_DATA" and "plan" not in v and v["price"] is None, (st, v)

# 5. CONFIRMED + свіжа ціна + вхід + стоп + ціль 1 + скасування + перевірки → «План готовий», цілі 2/3 лише за рівнями
row5 = {**ROW, "status": "CONFIRMED", "analysis_note": ROW["analysis_note"] + " confirm_sent=1 confirmed_px=0.3035"}
lv = {"asia_high": 0.3200, "asia_low": 0.29, "pdh": 0.3300, "pdl": 0.28, "w_high": 0.35, "w_low": 0.25}
tg = T.structural_targets(direction="LONG", entry=0.3035, tp1=0.31393, lv=lv)
assert tg["tp2"]["price"] == 0.32 and tg["tp3"]["price"] == 0.33 and tg["tp2"]["why"] == "межа азійської сесії", tg
v = S.build(row5, thesis=THESIS, price={**FRESH, "price": 0.3036}, targets=tg, plan_check=check_plan)
assert v["state"] == "READY" and v["icon"] == "🟢", v
p = v["plan"]
assert p["entry"] == "0,3035 $" and p["tp1"].startswith("0,3139") and "азійської" in p["tp2"] and "попереднього дня" in p["tp3"] and "після комісій" in p["potential"], p
# без цілей за рівнями — «немає обґрунтованої», рівні не вигадуємо
v = S.build(row5, thesis=THESIS, price={**FRESH, "price": 0.3036}, targets={"tp2": None, "tp3": None}, plan_check=check_plan)
assert v["plan"]["tp2"] == "немає обґрунтованої" and v["plan"]["tp3"] == "немає обґрунтованої"

# 6. План підтверджено, але не проходить перевірку (ціль надто близько) → «не готовий», не зелений
v = S.build({**row5, "tp1": 0.3070}, thesis=THESIS, price=FRESH, plan_check=check_plan)
assert v["state"] == "NOT_READY" and v["icon"] != "🟢" and any("замалий" in m for m in v["missing"]), v
assert "надто близько" in check_plan("SOLUSDT", "LONG", {"entry": 100.5, "sl": 99.0, "tp1": 103.0}, 100, 101)   # правило мінімальної цілі (не змінено)
assert check_plan("SOLUSDT", "LONG", {"entry": 100.5, "sl": 99.0, "tp1": 104.0}, 100, 101) is None
# ...і без збереженої ціни входу
v = S.build({**row5, "analysis_note": ROW["analysis_note"]}, thesis=THESIS, price=FRESH, plan_check=check_plan)
assert v["state"] == "NOT_READY" and any("ціну входу" in m for m in v["missing"])

# 7. Термінальні статуси перемагають; watch-рядок — «Лише спостерігаємо»
assert S.build({**ROW, "status": "CANCELLED"}, thesis=THESIS, price=STALE)["state"] == "CANCELLED"
assert S.build({**ROW, "status": "EXPIRED"}, thesis=THESIS, price=FRESH)["state"] == "EXPIRED"
w = S.build({**ROW, "signal_id": "watch-near-LSKUSDT-scalp", "sl": None, "tp1": None}, thesis=None, price=FRESH)
assert w["state"] == "OBSERVE" and "Входити не можна" in w["headline"]

# 7b. Строк дії картки (H1 = 12 год) минув, а статус у базі ще ACTIVE → «Час очікування минув», не «Чекаємо»
old = _build({**ROW, "ts_created": "2026-09-28T20:00:00+00:00"}, thesis=THESIS, price=FRESH, now=NOW)
assert old["state"] == "EXPIRED", old["state"]
assert _build({**row5, "ts_created": "2026-09-28T20:00:00+00:00"}, thesis=THESIS, price=FRESH, plan_check=check_plan, now=NOW)["state"] == "READY", "підтверджений план за часом не застарює"

# 8. Список без ціни ніколи не каже «готовий»
for st in ("ACTIVE", "WATCHING", "CONFIRMED", "HIT_ENTRY"):
    lab = S.list_label({**ROW, "status": st})
    assert "готов" not in lab["text"].lower() or "не готов" in lab["text"].lower(), lab
assert S.list_label({**ROW, "status": "CONFIRMED"})["state"] == "CHECK"

# 9. Історія — події людською мовою, без кодів і без однакових підряд
h = S.history([{"ts": "1", "type": "THESIS_VERSION"}, {"ts": "2", "type": "THESIS_VERSION"}, {"ts": "3", "type": "RISK_SHADOW_REVIEW"},
               {"ts": "4", "type": "ZONE_REACHED"}, {"ts": "5", "type": "ZONE_REACHED"}, {"ts": "6", "type": "CANCELLED"}])
assert [x["text"] for x in h] == ["Лев оновив план", "Ціна досягла зони", "План скасовано"], h

# 10. Цілі: SHORT дзеркально; без рівня — немає; занадто близько до попередньої — немає (санітарний мінімум)
assert T.structural_targets(direction="SHORT", entry=100, tp1=97, lv={"asia_low": 95, "pdl": 90})["tp3"]["price"] == 90
assert T.structural_targets(direction="LONG", entry=100, tp1=103, lv={"asia_high": 103.1})["tp2"] is None
assert T.structural_targets(direction="LONG", entry=100, tp1=103, lv={})["tp2"] is None
print("OK scenario state: one truth for Telegram+Mini App, strict READY, no contradictions, structural TP2/TP3, plain language")

# рядок «lev-watch-*» з новою приміткою: рівень скасування й умова підтвердження записані → сторінка не каже «не визначено»
from datetime import datetime as _D, timezone as _Z
import office_scenario_state as _S
_row = {"signal_id": "lev-watch-BTCUSDT-1", "symbol": "BTCUSDT", "direction": "LONG", "entry_low": 100.0, "entry_high": 101.0, "sl": 98.0, "tp1": 106.0,
        "status": "WATCHING", "ts_created": NOW.isoformat(), "ts_updated": NOW.isoformat(),
        "analysis_note": "WAIT чекаю cancel=98.0 confirm=M15"}
_v = _S.build(_row, thesis=None, price={**FRESH, "price": 103.0}, targets=None, events=[], plan_check=None)
assert not any("скасування" in m or "підтвердження" in m for m in _v["missing"]), _v["missing"]
_row2 = dict(_row, analysis_note="WAIT чекаю")
_v2 = _S.build(_row2, thesis=None, price={**FRESH, "price": 103.0}, targets=None, events=[], plan_check=None)
assert any("скасування" in m for m in _v2["missing"]) and any("підтвердження" in m for m in _v2["missing"])
print("OK legacy watch rows: cancel/confirm from note; old rows stay honest")

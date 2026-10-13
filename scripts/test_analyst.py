"""Аналітик READY: розбір LINK SHORT / TIA LONG з реальних фактів на момент рішення (фікстура), критичні дефекти, збереження, тижневий розбір."""
import json, os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from office2 import analyst as AN

cases = json.load(open(os.path.join(os.path.dirname(__file__), "..", "office2", "fixtures", "analyst_cases.json")))
ok = True
def check(name, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + name)
    ok = ok and bool(cond)

L = AN.analyze(cases["LINK_SHORT"])
T = AN.analyze(cases["TIA_LONG"])
for a in (L, T):
    for k in ("hypothesis", "for", "against", "key_contradiction", "nearest_obstacle", "confirmed", "not_confirmed", "invalidation", "now_or_wait", "levels", "follow_up", "cards", "links", "grade", "verdict"):
        check(f"12-пунктів поле {k}", k in a)
    check("немає критичних дефектів у реальному READY", a["critical"] == [])
check("LINK: R:R TP1 3.0 ≥ джерела 3 (G-RR-MIN3 виконано)", L["rr_source_check"]["met"] is True)
check("LINK: найближча перешкода 12.766 на 0.63R", abs(L["nearest_obstacle"]["r"] - 0.633) < 0.01)
check("LINK: усі три стопи не обґрунтовані → прапор + advisory would_block", "STOP_NOT_JUSTIFIED" in L["flags"] and L["would_block_advisory"] == ["STOP_NOT_JUSTIFIED"])
check("LINK: діапазон не від правильної межі", "RANGE_WRONG_EDGE" in L["flags"])
check("LINK: суперечності не блокують (critical пустий, verdict не CRITICAL)", L["verdict"] != "CRITICAL_PROBLEM")
check("LINK: M1 ретест відбувся і це відображено", any("відбувся" in w for w in L["now_or_wait"]["why"]))
check("TIA: R:R TP1 1.22 < джерела 3 → прапор", "RR_BELOW_SOURCE_MIN" in T["flags"] and T["rr_source_check"]["met"] is False)
check("TIA: перешкода 0.87R < 1R → прапор", "OBSTACLE_LT_1R" in T["flags"])
check("TIA: вхід за межею зони + M1 ретест чекає → рекомендація чекати, лімітний вхід = середина зони", T["alt_entry"] and abs(T["alt_entry"]["price"] - 0.588490) < 1e-5 and T["now_or_wait"]["decision"] in ("ENTER_ON_LIMIT", "WAIT"))
check("TIA: на лімітному вході R до TP1 більше за 1.22 (арифметика на тих самих SL/TP)", T["alt_entry"]["tp_r"][0] > 1.22)
check("TIA: вердикт PREFER_BETTER_ENTRY", T["verdict"] == "PREFER_BETTER_ENTRY")
check("картки: premium/discount суперечить напряму в обох кейсах", L["cards"]["S-OTE-PD"] == -1 and T["cards"]["S-OTE-PD"] == -1)
check("зв'язок намиста: S-OTE-PD ↔ G-LVL-MIRROR суперечить (проти / за)", any(l["a"] == "S-OTE-PD" and l["b"] == "G-LVL-MIRROR" and l["relation"] == "суперечить" for l in L["links"]))
bad = dict(cases["LINK_SHORT"], sl=12.5)
check("критичний дефект: SL з неправильного боку входу", AN.analyze(bad)["critical"] and AN.analyze(bad)["verdict"] == "CRITICAL_PROBLEM")
check("критичний дефект: немає розміру", "не визначено розмір позиції/ризик" in AN.critical_defects(dict(cases["LINK_SHORT"], sizing=None)))

H = AN.analyze(cases["LINK_SHORT"], [{"family": "FALSE_BREAK_RECLAIM", "direction": "LONG", "stage": "TRIGGERED"}])
check("гіпотези: протилежна активна → CONFLICTS + advisory, grade не змінено", H["hypotheses"]["net"] == "CONFLICTS" and "HYP_OPPOSITE_ACTIVE" in H["would_block_advisory"] and H["grade"] == L["grade"])
H2 = AN.analyze(cases["LINK_SHORT"], [{"family": "SMC_REVERSAL", "direction": "SHORT", "stage": "ARMED"}])
check("гіпотези: однонапрямлена → SUPPORTS", H2["hypotheses"]["net"] == "SUPPORTS" and "HYP_SUPPORTS" in H2["flags"])
check("гіпотези: без даних → поле None", L["hypotheses"] is None)
check("тактика: рекомендація є, без таблиці = план як є", L["tactic"]["tactic"] == "T0_enter_now" and not L["tactic"]["table_used"] and "T1_scalp_to_obstacle" in L["tactic"]["options"])
check("тактика: TIA — лімітний вхід дає більше R, ніж 1.22", T["tactic"]["options"]["T3_limit_zone_mid"]["r_to_tp"] > 1.22)
from office2.method_evidence import load_rules
from office2.method_sequence import evaluate_chain
mc = evaluate_chain(load_rules(), {"G-RR-MIN3": {"rr": 1.2}, "G-SIGNAL-CLOSE": {"close": 100.0, "level": 99.0, "direction": "LONG"}})
cc = AN.compact_chain(mc)
check("ланцюг 82: 9 фаз, усього 82 картки", len(cc["phases"]) == 9 and cc["total"] == 82)
check("ланцюг: розрив у фазі ризику (R:R<3), PASS у вході", cc["first_break"] == "07_RISK" and "G-SIGNAL-CLOSE" in next(p for p in cc["phases"] if p["phase"] == "06_ENTRY")["pass"])
Z = AN.analyze(cases["TIA_LONG"], None, cc)
check("розбір: chain82 і картки ланцюга потрапили в cards", Z["chain82"]["first_break"] == "07_RISK" and Z["cards"].get("G-RR-MIN3") == -1)
d = tempfile.mkdtemp(); db = os.path.join(d, "t.db"); os.environ["OFFICE_DB_PATH"] = db
import office_bridge  # noqa
from office2 import paper
paper._ensure(db)
now = time.time()
AN.persist(db, "S1|1", "LINKUSDT", "SHORT", now - 100, L); AN.persist(db, "S1|1", "LINKUSDT", "SHORT", now - 100, L)
AN.persist(db, "S2|1", "TIAUSDT", "LONG", now - 90, T)
check("збереження ідемпотентне", len(AN.list_records(db)) == 2)
from office_bridge import _execute
_execute(db, "INSERT INTO office2_paper_position(scenario_id, symbol, direction, status, r_a, close_reason) VALUES (?,?,?,?,?,?)", ("S1|1", "LINKUSDT", "SHORT", "CLOSED", 3.0, "TP1"))
_execute(db, "INSERT INTO office2_paper_position(scenario_id, symbol, direction, status, r_a, close_reason) VALUES (?,?,?,?,?,?)", ("S2|1", "TIAUSDT", "LONG", "CLOSED", -1.0, "SL"))
w = AN.weekly_review(db, now)
check("тижневий розбір: 2 сигнали, 2 закриті", w["signals"] == 2 and w["closed"] == 2)
check("тижневий розбір: по прапору RR_BELOW_SOURCE_MIN є середній R", w["by_flag"]["RR_BELOW_SOURCE_MIN"]["with"]["mean_r"] == -1.0)
check("розбір не містить результату (лише факти до рішення)", "tp_share" not in json.dumps(L) and "r_a" not in json.dumps(L))
sys.exit(0 if ok else 1)

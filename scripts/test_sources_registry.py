"""Офлайн-перевірка реєстру першоджерел docs/sources: цілісність manifest.csv/evidence.jsonl і заборона публікації оригіналів.

Запуск: python3 scripts/test_sources_registry.py  (код виходу 1 при збої)."""
import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "sources")
FAILS = []


def check(name, ok, extra=""):
    print(("ok   " if ok else "FAIL ") + name + ((" — " + str(extra)) if (extra and not ok) else ""))
    if not ok:
        FAILS.append(name)


TYPES = {"DARIA_METHOD", "GERCHIK", "SMC", "OTHER_VERIFIED", "OFFICE_UX_EXAMPLE", "OFFICE_PRODUCT_QA", "NEEDS_SOURCE_MAPPING"}
CLASSES = {"SOURCE_NUMERIC", "SOURCE_QUALITATIVE", "SOURCE_NUMERIC_AMBIGUOUS_CLOCK", "SOURCE_NUMERIC_ATTRIBUTION_BY_CONTEXT",
           "SOURCE_QUALITATIVE_ATTRIBUTION_BY_CONTEXT", "USER_REQUIREMENT", "STUDENT_EXAMPLE_NOT_RULE", "UX_EXAMPLE_NOT_RULE",
           "PRODUCT_QA_NOT_RULE", "NEEDS_SOURCE_MAPPING", "NOT_SPECIFIED_IN_PROVIDED_SOURCES"}
REQUIRED = ["rule_id", "author", "method", "source_files", "fragment_paraphrase", "context_tf", "measurable_inputs", "explicit_conditions",
            "invalidation", "missing_parameters", "automation_assumptions", "evidence_class", "implementation_status", "conformity",
            "tests_required", "last_audit_commit"]

rows = list(csv.DictReader(open(os.path.join(SRC, "manifest.csv"), encoding="utf-8")))
check("manifest: 427 записів", len(rows) == 427, len(rows))
check("manifest: 415 зображень + 12 файлів", sum(r["kind"] == "image" for r in rows) == 415 and sum(r["kind"] == "support_file" for r in rows) == 12)
check("manifest: унікальні шляхи", len({r["path"] for r in rows}) == 427)
check("manifest: SHA-256 64 hex", all(re.fullmatch(r"[0-9a-f]{64}", r["sha256"]) for r in rows))
check("manifest: унікальність SHA для зображень не обов'язкова, але SHA непорожні", all(r["sha256"] for r in rows))
check("manifest: типи з дозволеного переліку", all(r["source_type"] in TYPES for r in rows), {r["source_type"] for r in rows} - TYPES)
check("manifest: послідовні seq 1..427", [int(r["seq"]) for r in rows] == list(range(1, 428)))
check("manifest: порядок архіву (зображення 1..415)", [int(r["seq"]) for r in rows if r["kind"] == "image"] == list(range(1, 416)))
by_seq = {int(r["seq"]): r for r in rows}
check("override: IMG_9211-9213 = PRODUCT_QA", all(by_seq[n]["source_type"] == "OFFICE_PRODUCT_QA" for n in (296, 297, 298)))
check("override: IMG_9221/9222 = UX_EXAMPLE", all(by_seq[n]["source_type"] == "OFFICE_UX_EXAMPLE" for n in (299, 300)))
check("manifest: автор Дарії не приписаний інфографіці #302", by_seq[302]["source_type"] == "NEEDS_SOURCE_MAPPING")
check("manifest: сторіс #280-295 позначені як контекстна атрибуція", all(by_seq[n]["author_status"] == "ESTABLISHED_BY_OWNER_CONTEXT_ONLY" for n in range(280, 296)))

ev = [json.loads(l) for l in open(os.path.join(SRC, "evidence.jsonl"), encoding="utf-8") if l.strip()]
ids = [e["rule_id"] for e in ev]
check("evidence: непорожній, rule_id унікальні", len(ev) >= 50 and len(ids) == len(set(ids)), len(ev))
check("evidence: усі обов'язкові поля", all(all(k in e for k in REQUIRED) for e in ev), [e["rule_id"] for e in ev if not all(k in e for k in REQUIRED)][:3])
check("evidence: клас доказу з переліку", all(e["evidence_class"] in CLASSES for e in ev), {e["evidence_class"] for e in ev} - CLASSES)
paths = {r["path"]: r["sha256"] for r in rows}
bad = [(e["rule_id"], s["path"]) for e in ev for s in e["source_files"] if paths.get(s["path"]) != s["sha256"]]
check("evidence: кожне джерело правила є в manifest із тим самим SHA", not bad, bad[:3])
check("evidence: кожне джерело має сторінку/кадр", all(s.get("page_or_frame") for e in ev for s in e["source_files"]))
check("evidence: припущення автоматизації позначені IMPLEMENTATION_HYPOTHESIS", all(a.get("label") == "IMPLEMENTATION_HYPOTHESIS" for e in ev for a in e["automation_assumptions"]))
check("evidence: USER_REQUIREMENT / NOT_SPECIFIED не мають статусу LIVE", all("LIVE" not in e["implementation_status"] for e in ev))
check("evidence: правила без джерела-класу не мають продакшн-статусу", all(not (e["evidence_class"] in ("USER_REQUIREMENT", "NEEDS_SOURCE_MAPPING", "NOT_SPECIFIED_IN_PROVIDED_SOURCES") and e["implementation_status"] in ("IMPLEMENTED", "PRODUCTION") ) for e in ev))
check("evidence: Дарія, Герчик, SMC присутні окремо", {"Герчик", "Дарія Жданова", "SM Trader"} <= {e["author"].split(" (")[0] for e in ev})
numeric = {e["rule_id"] for e in ev if e["evidence_class"].startswith("SOURCE_NUMERIC")}
check("evidence: ключові числові правила з джерела присутні", {"G-RR-MIN3", "G-LUFT", "G-ATR-DAYUSED", "D-STOP-ATR-MARGIN", "D-POST-IMPULSE-BASE", "S-OTE-PD"} <= numeric)
check("evidence: HTF сценарій — USER_REQUIREMENT, не авторське правило", next(e for e in ev if e["rule_id"] == "D-HTF-STRONG-CANDLE-PULLBACK")["evidence_class"] == "USER_REQUIREMENT")
check("evidence: Булковскі = NOT_SPECIFIED_IN_PROVIDED_SOURCES", next(e for e in ev if e["rule_id"] == "X-NOT-SPECIFIED-BULKOWSKI")["evidence_class"] == "NOT_SPECIFIED_IN_PROVIDED_SOURCES")
check("evidence: коротка парафраза (не копія книги)", all(len(e["fragment_paraphrase"]) <= 900 for e in ev))
check("evidence: цитати короткі (≤ 8 слів)", all(len((e.get("fragment_quote_short") or "").split()) <= 8 for e in ev))

# заборона публікації оригіналів у docs/sources
forbidden = [f for f in os.listdir(SRC) if f.lower().endswith((".png", ".jpg", ".jpeg", ".docx", ".zip", ".mp4", ".pdf"))]
check("docs/sources: немає зображень/docx/zip", not forbidden, forbidden)
check("docs/sources: немає повного тексту книг (.txt)", not [f for f in os.listdir(SRC) if f.lower().endswith(".txt")])
check("docs/sources: розмір evidence.jsonl розумний (< 400 КБ)", os.path.getsize(os.path.join(SRC, "evidence.jsonl")) < 400_000)
check("unresolved.md містить розділ конфліктів і NEEDS_SOURCE_MAPPING", all(k in open(os.path.join(SRC, "unresolved.md"), encoding="utf-8").read() for k in ("NEEDS_SOURCE_MAPPING", "Конфлікти")))

# код: усі «ДЖЕРЕЛО»-мітки HTF-сценарію мають rule_id з реєстру
html = open(os.path.join(ROOT, "office2", "htf_scenario.py"), encoding="utf-8").read()
cited = set(re.findall(r"\b([DGS]-[A-Z0-9-]{3,})\b", html))
check("htf_scenario: усі rule_id у мітках існують у evidence.jsonl", cited <= set(ids), cited - set(ids))
check("htf_scenario: сценарій позначений USER_REQUIREMENT, а не авторським правилом", "USER_REQUIREMENT" in html)

print("\nFAILED: %d" % len(FAILS) if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)

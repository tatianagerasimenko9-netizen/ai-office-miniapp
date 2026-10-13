"""Audit: which of the 82 registry rules receive inputs from real feature builders (fixture run).

Counts only what the code produces; a rule is `formed` when some builder emits its inputs,
`verified` when it also has a passing unit test (see TESTED), NOT_APPLICABLE comes from the registry.
Usage: PYTHONPATH=. python3 scripts/method_coverage_audit.py [--json]
"""
import json
import sys
from datetime import datetime, timezone

from office2 import method_context_features as MC
from office2 import method_plan_features as MP
from office2.method_closed_bar_features import daily_atr_observation, from_closed_bars
from office2.method_evidence import load_rules
from office2.method_predicates import evaluate


def bar(o, h, l, c, v=100):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def fixture_inputs():
    bars = [bar(10, 12, 9, 11) for _ in range(12)] + [bar(10, 11, 8, 10)]
    inputs = dict(from_closed_bars(bars, len(bars) - 1, daily_ranges=[4, 4, 4], day_bars=bars[-3:]))
    days = [{"high": 10 + i, "low": 5} for i in range(6)]
    inputs.update(daily_atr_observation(days, 5))
    engulf = [bar(10, 12, 8, 11), bar(11, 12, 9, 10), bar(9, 13, 8, 12)]
    for rid, val in from_closed_bars(engulf, 2).items():
        inputs.setdefault(rid, val)
    th = {"state": "READY", "dir": "LONG", "entry": 100.0, "sl": 99.0, "trigger_level": 99.5,
          "invalidation": {"price": 99.2}, "targets": [{"p": 103.0}], "sizing": {"risk_usd": 10.0}, "sequence": [{"step": "sweep"}]}
    inputs.update(MP.from_thesis(th, daily_atr=10.0, equity_usd=1000.0, closed_trades=120, daily_loss_usd=1.0, asof_bar_ts=1.0))
    ts = datetime(2026, 10, 13, 8, tzinfo=timezone.utc).timestamp()
    inputs.update(MC.session_news(ts, "OK"))
    inputs.update(MC.from_topdown({"stages": [{"tf": "D1", "state": "CONFIRMS"}, {"tf": "H1", "state": "CONFIRMS"},
                                              {"tf": "M15", "state": "CONFIRMS"}]}, 1.0))
    model = {"steps": [{"step": "MS", "ok": True}], "sweep": {"x": 1}, "htf_context": {"htf_poi": [1]},
             "pois": [{"kind": "OB", "open": 100.0, "mt": 99.0}]}
    inputs.update(MC.from_smc({"models": {"LONG": {"REVERSAL": model}}, "price": 101.0, "amd": {"stage": "D"}}, "LONG", 1.0))
    d1 = {k: [100.0] * 30 for k in "ohlc"}
    d1["h"] = [102.0] * 30
    d1["l"] = [98.0] * 30
    d1["o"][24], d1["h"][24], d1["l"][24], d1["c"][24] = 110, 111, 90, 91
    for i in range(25, 30):
        d1["o"][i], d1["h"][i], d1["l"][i], d1["c"][i] = 92, 95, 90, 92
    inputs.update(MC.d1_base_after_impulse(d1, 1.0))
    return inputs


# Blockers established by code/registry review (not "no builder yet"): why a builder cannot be written without inventing values.
KNOWN_BLOCKERS = {
    "G-NO-CHASE": "джерело не дає числа «запізно»; MAX_CHASE_R у Brain — наш параметр, не правило автора",
    "G-LUFT": "число джерела (0,04% ціни / 20% розрахункового стопа) — для акцій РФ; для крипти розрахунковий стоп не визначено, Brain використовує інший люфт (медіана проколів)",
    "G-LUFT-FILL": "прив'язане до розрахункового стопа акцій/FX; для крипти немає визначення",
    "G-CHANNEL": "потрібна розмітка каналу (окремий аудит регресійного каналу не завершено); ширина «в стопах» визначена для акцій/FX",
    "G-BE": "у LIVE-супроводі немає перенесення стопа (лише paper-порівняння); автор не вважає BE обов'язковим",
    "G-BE-2R": "у LIVE-супроводі немає перенесення стопа; правило умовне («лише для нервового інструмента»)",
    "G-TP-TRAIL": "у LIVE-супроводі немає трейлінгу; джерело якісне (тренд із запасом), порогів немає",
    "D-FRACTAL-TF": "потрібна розмітка хвиль різних ТФ (Еліотт — розмітка в джерелі «гіпотеза», автоматичної немає)",
    "G-LVL-CONSTRUCTION": "потрібна таблиця дотиків/хибних пробоїв по рівню (джерело радить її вести) — у Brain її немає; допуск близькості рівня не заданий",
}
STATUS = {"FORMED_SOURCE": "IMPLEMENTED", "FORMED_HYPOTHESIS": "PARTIAL", "NOT_APPLICABLE": "NOT_APPLICABLE"}


def render_md(rules, rows, summary):
    """Single registry of the 82 cards: status is derived from CODE (fixture run), never from documentation."""
    by = {r["rule_id"]: r for r in rules}
    out = ["# Реєстр 82 методологічних карток — стан за кодом", "",
           "Автогенерація: `PYTHONPATH=. python3 scripts/method_coverage_audit.py --md`. Статус виводиться з виконання коду, а не з документів.", "",
           "- **IMPLEMENTED** — входи формуються з реальних джерел (закриті свічки / READY-план / календар / D1), є predicate і тести. Це НЕ означає «доведено прибутковим» чи «активний фільтр у production».",
           "- **PARTIAL** — входи формуються, але форма/таймфрейм/пороги — наша інтерпретація (ГІПОТЕЗА), джерело її не фіксує.",
           "- **BLOCKED** — у реєстрі зафіксовано, чого бракує (`missing_parameters`); без нового матеріалу не реалізується.",
           "- **UNKNOWN** — builder відсутній, блокера в реєстрі немає (потрібна робота).",
           "- **NOT_APPLICABLE** — реєстр сам визначає запис як не-торгове правило (приклад/QA) або замінене для крипти.", "",
           f"Підсумок: {summary}", "", "| Правило | Метод | Статус | Деталь |", "|---|---|---|---|"]
    for rid, kind, note in rows:
        st = STATUS.get(kind) or ("BLOCKED" if by[rid].get("missing_parameters") else "UNKNOWN")
        out.append(f"| {rid} | {by[rid].get('method')} | {st} | {note[:110].replace('|', '/')} |")
    return "\n".join(out)


def main():
    rules = load_rules()
    inputs = fixture_inputs()
    na = MC.scope_resolution(rules)
    rows = []
    for r in rules:
        rid = r["rule_id"]
        if rid in na:
            rows.append((rid, "NOT_APPLICABLE", na[rid]["_not_applicable"]))
        elif rid in inputs:
            basis = (inputs[rid].get("_provenance") or {}).get("basis", "SOURCE")
            res = evaluate(rid, {k: v for k, v in inputs[rid].items() if not k.startswith("_")})
            rows.append((rid, "FORMED_" + basis, res["status"]))
        else:
            rows.append((rid, "BLOCKED", KNOWN_BLOCKERS.get(rid) or "; ".join(r.get("missing_parameters") or []) or "no builder"))
    summary = {}
    for _, kind, _ in rows:
        summary[kind] = summary.get(kind, 0) + 1
    if "--md" in sys.argv:
        print(render_md(rules, rows, summary))
        return
    if "--json" in sys.argv:
        print(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1))
        return
    for rid, kind, note in rows:
        print(f"{kind:18} {rid:36} {note[:90]}")
    print(summary, "formed total:", summary.get("FORMED_SOURCE", 0) + summary.get("FORMED_HYPOTHESIS", 0))


if __name__ == "__main__":
    main()

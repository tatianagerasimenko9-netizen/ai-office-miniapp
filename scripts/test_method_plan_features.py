"""Plan/risk rule inputs from a frozen READY thesis: positive, negative, no-fabrication."""
import unittest

from office2.method_evidence import load_rules
from office2.method_plan_features import from_thesis, daily_atr_from_ranges
from office2.method_predicates import evaluate
from office2.method_sequence import evaluate_chain

PLAN_RULES = ("G-RR-MIN3", "G-STOP-CRYPTO", "G-STOP-TECH", "G-STOP-CRYPTO-TECHNICAL",
              "D-STOP-STRUCTURE", "G-STOP-ATR", "G-RISK-TRADE", "S-RISK", "G-RISK-DAY", "G-TRIAL-100", "G-INDICATORS-NOT-USED")


def ready(direction="LONG"):
    sg = 1 if direction == "LONG" else -1
    return {"state": "READY", "dir": direction, "entry": 100.0, "sl": 100.0 - sg * 1.0,
            "trigger_level": 100.0 - sg * 0.5, "invalidation": {"price": 100.0 - sg * 0.8, "why": "x"},
            "targets": [{"p": 100.0 + sg * 3.0, "r": 3.0}], "sizing": {"risk_usd": 10.0},
            "sequence": [{"step": "подія: sweep рівня", "ok": True}, {"step": "тригер: закриття M15 вище", "ok": True}]}


def feats(th, **kw):
    kw.setdefault("daily_atr", 10.0)
    kw.setdefault("equity_usd", 1000.0)
    kw.setdefault("closed_trades", 120)
    kw.setdefault("daily_loss_usd", 5.0)
    return from_thesis(th, **kw)


class PlanFeatureTest(unittest.TestCase):
    def test_all_ten_rules_formed_and_evaluable(self):
        for d in ("LONG", "SHORT"):
            f = feats(ready(d))
            self.assertEqual(set(f), set(PLAN_RULES), d)
            for r in PLAN_RULES:
                self.assertIn(evaluate(r, f[r])["status"], ("PASS", "FAIL"), (d, r))

    def test_oscillator_trigger_detected(self):
        th = ready("LONG")
        self.assertEqual(evaluate("G-INDICATORS-NOT-USED", feats(th)["G-INDICATORS-NOT-USED"])["status"], "PASS")
        th["sequence"].append({"step": "тригер: RSI перетнув 30"})
        self.assertEqual(evaluate("G-INDICATORS-NOT-USED", feats(th)["G-INDICATORS-NOT-USED"])["status"], "FAIL")
        th["sequence"] = []
        self.assertNotIn("G-INDICATORS-NOT-USED", feats(th))

    def test_values(self):
        f = feats(ready("LONG"))
        self.assertEqual({k: v for k, v in f["G-RR-MIN3"].items() if k[0] != "_"}, {"reward": 3.0, "risk": 1.0})
        self.assertEqual(f["G-STOP-ATR"]["_provenance"]["basis"], "HYPOTHESIS")
        self.assertEqual(evaluate("G-RR-MIN3", f["G-RR-MIN3"])["status"], "PASS")
        self.assertEqual(f["G-RISK-TRADE"]["risk_budget_usd"], 10.0)  # 1% of 1000
        self.assertEqual(evaluate("G-RISK-TRADE", f["G-RISK-TRADE"])["status"], "PASS")
        self.assertEqual(f["G-RISK-DAY"]["daily_limit_usd"], 30.0)
        self.assertEqual(evaluate("G-STOP-CRYPTO", f["G-STOP-CRYPTO"])["status"], "PASS")  # 1% <= 2%

    def test_negative_cases(self):
        th = ready("LONG")
        th["targets"] = [{"p": 101.5}]
        f = feats(th, equity_usd=500.0, closed_trades=5, daily_loss_usd=99.0)
        self.assertEqual(evaluate("G-RR-MIN3", f["G-RR-MIN3"])["status"], "FAIL")
        self.assertEqual(evaluate("G-RISK-TRADE", f["G-RISK-TRADE"])["status"], "FAIL")  # 10 > 5
        self.assertEqual(evaluate("G-RISK-DAY", f["G-RISK-DAY"])["status"], "FAIL")
        self.assertEqual(evaluate("G-TRIAL-100", f["G-TRIAL-100"])["status"], "FAIL")
        th = ready("LONG")
        th["sl"] = 90.0  # 10% stop
        self.assertEqual(evaluate("G-STOP-CRYPTO", feats(th)["G-STOP-CRYPTO"])["status"], "FAIL")
        th = ready("LONG")
        th["invalidation"]["price"] = 99.0 - 1.0  # stop 99 is above invalidation 98 -> tighter than structure
        self.assertEqual(evaluate("D-STOP-STRUCTURE", feats(th)["D-STOP-STRUCTURE"])["status"], "FAIL")

    def test_missing_sources_are_absent_not_invented(self):
        f = from_thesis(ready("LONG"))
        self.assertIn("G-INDICATORS-NOT-USED", f)   # derived from the thesis itself, no external source needed
        for r in ("G-STOP-ATR", "G-RISK-TRADE", "S-RISK", "G-RISK-DAY", "G-TRIAL-100"):
            self.assertNotIn(r, f)
        self.assertNotIn("G-RR-MIN3", from_thesis({**ready(), "targets": []}))
        self.assertEqual(from_thesis({**ready(), "state": "WAIT"}), {})
        self.assertEqual(from_thesis(None), {})
        bad = ready(); bad["sl"] = 101.0  # SL on the wrong side -> no plan
        self.assertEqual(from_thesis(bad, equity_usd=1000.0), {})
        self.assertNotIn("G-RISK-TRADE", from_thesis(ready(), equity_usd=0))
        self.assertIsNone(daily_atr_from_ranges([1, 2]))
        self.assertEqual(daily_atr_from_ranges([2, 4, 6]), 4.0)

    def test_chain_compatible_and_traced(self):
        out = evaluate_chain(load_rules(), feats(ready("SHORT")))
        states = {x["rule_id"]: x for ph in out["phases"] for x in ph["rules"]}
        for r in PLAN_RULES:
            self.assertIn(states[r]["status"], ("PASS", "FAIL"))
            self.assertIn("inputs", states[r])
        self.assertEqual(out["evaluated"], 82)

    def test_not_applicable_and_provenance_in_chain(self):
        out = evaluate_chain(load_rules(), {"G-LUFT": {"_not_applicable": "src scope", "_provenance": {"basis": "SOURCE"}},
                                            "G-RR-MIN3": {"reward": 3, "risk": 1, "_provenance": {"basis": "SOURCE", "source": "thesis"}}})
        st = {x["rule_id"]: x for ph in out["phases"] for x in ph["rules"]}
        self.assertEqual(st["G-LUFT"]["status"], "NOT_APPLICABLE")
        self.assertEqual(out["counts"]["NOT_APPLICABLE"], 1)
        self.assertEqual(st["G-RR-MIN3"]["provenance"]["source"], "thesis")
        self.assertNotIn("_provenance", st["G-RR-MIN3"]["inputs"])


if __name__ == "__main__":
    unittest.main()

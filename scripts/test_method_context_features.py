"""Context rule inputs: calendar/sessions, top-down, SMC, D1 base, scope resolution."""
import unittest
from datetime import datetime, timezone

from office2.method_context_features import (d1_base_after_impulse, from_smc, from_topdown,
                                             msk_session, scope_resolution, session_news)
from office2.method_evidence import load_rules
from office2.method_predicates import evaluate
from office2.method_sequence import evaluate_chain


def ts(h, m=0):
    return datetime(2026, 10, 13, h, m, tzinfo=timezone.utc).timestamp()


def d1(n=30, impulse_at=None, down=True, base=None):
    o, h, l, c = [], [], [], []
    for i in range(n):
        o.append(100.0); h.append(102.0); l.append(98.0); c.append(100.0)
    if impulse_at is not None:
        o[impulse_at], h[impulse_at], l[impulse_at], c[impulse_at] = (110, 111, 90, 91) if down else (91, 111, 90, 110)
        for i in range(impulse_at + 1, n):
            lo, hi = base
            o[i], h[i], l[i], c[i] = (lo + hi) / 2, hi, lo, (lo + hi) / 2
    return {"o": o, "h": h, "l": l, "c": c}


class ContextTest(unittest.TestCase):
    def test_sessions_msk(self):
        self.assertEqual(msk_session(ts(8)), "EUROPE")      # 11:00 MSK
        self.assertEqual(msk_session(ts(13)), "US")          # 16:00 MSK
        self.assertEqual(msk_session(ts(22)), "OFF_HOURS")   # 01:00 MSK
        self.assertEqual(msk_session(ts(12, 29)), "OFF_HOURS")  # 15:29 MSK
        self.assertEqual(msk_session(ts(12, 30)), "US")

    def test_news_pass_fail_unknown(self):
        ok = session_news(ts(8), "OK")["D-SESSIONS-NEWS"]
        self.assertEqual(evaluate("D-SESSIONS-NEWS", ok)["status"], "PASS")
        bad = session_news(ts(8), "FAIL")["D-SESSIONS-NEWS"]
        self.assertEqual(evaluate("D-SESSIONS-NEWS", bad)["status"], "FAIL")
        self.assertEqual(session_news(ts(8), "UNAVAILABLE"), {})
        self.assertEqual(session_news(ts(8), None), {})

    def test_topdown(self):
        td = {"stages": [{"tf": "D1", "state": "CONFIRMS"}, {"tf": "H4", "state": "NEUTRAL"},
                         {"tf": "H1", "state": "CONFIRMS"}, {"tf": "M15", "state": "CONFIRMS"}]}
        f = from_topdown(td, 1.0)
        self.assertEqual(evaluate("D-HTF-LTF-CONFIRM", f["D-HTF-LTF-CONFIRM"])["status"], "PASS")
        self.assertEqual(f["D-HTF-LTF-CONFIRM"]["_provenance"]["basis"], "HYPOTHESIS")
        td["stages"][2]["state"] = "CONFLICTS"
        f = from_topdown(td, 1.0)
        self.assertEqual(evaluate("D-HTF-LTF-CONFIRM", f["D-HTF-LTF-CONFIRM"])["status"], "FAIL")
        self.assertEqual(from_topdown({"stages": [{"tf": "D1", "state": "UNAVAILABLE"}]}, 1.0), {})
        self.assertEqual(from_topdown(None, 1.0), {})

    def test_smc(self):
        model = {"steps": [{"step": "MS", "ok": True}], "sweep": {"x": 1}, "htf_context": {"htf_poi": [1]},
                 "pois": [{"kind": "OB", "open": 100.0, "mt": 99.0}]}
        res = {"models": {"LONG": {"REVERSAL": model}}, "price": 101.0, "amd": {"stage": "D"}}
        f = from_smc(res, "LONG", 1.0)
        self.assertEqual(evaluate("S-REVERSAL-CONT", f["S-REVERSAL-CONT"])["status"], "PASS")
        self.assertEqual(evaluate("S-OB", f["S-OB"])["status"], "PASS")       # close 101 >= MT 99
        self.assertEqual(evaluate("S-PO3", f["S-PO3"])["status"], "PASS")
        res["price"] = 98.0
        self.assertEqual(evaluate("S-OB", from_smc(res, "LONG", 1.0)["S-OB"])["status"], "FAIL")
        res["amd"] = {"stage": "A"}
        self.assertEqual(evaluate("S-PO3", from_smc(res, "LONG", 1.0)["S-PO3"])["status"], "FAIL")
        res["amd"] = {"stage": "NO_RANGE"}
        self.assertNotIn("S-PO3", from_smc(res, "LONG", 1.0))
        self.assertEqual(from_smc({"error": "x"}, "LONG", 1.0), {})
        self.assertEqual(from_smc(res, "BOTH", 1.0), {})

    def test_d1_base(self):
        good = d1(impulse_at=24, down=True, base=(90, 95))   # base high 95 <= 90+21/3=97 -> lower third, retrace 25%
        f = d1_base_after_impulse(good, 1.0)["D-POST-IMPULSE-BASE"]
        self.assertEqual(evaluate("D-POST-IMPULSE-BASE", f)["status"], "PASS")
        bad = d1(impulse_at=24, down=True, base=(90, 103))   # retraced > 50%
        f = d1_base_after_impulse(bad, 1.0)["D-POST-IMPULSE-BASE"]
        self.assertEqual(evaluate("D-POST-IMPULSE-BASE", f)["status"], "FAIL")
        up = d1(impulse_at=24, down=False, base=(106, 110))
        f = d1_base_after_impulse(up, 1.0)["D-POST-IMPULSE-BASE"]
        self.assertEqual(evaluate("D-POST-IMPULSE-BASE", f)["status"], "PASS")
        self.assertEqual(d1_base_after_impulse(d1(), 1.0), {})            # no impulse
        self.assertEqual(d1_base_after_impulse(d1(n=10), 1.0), {})        # too few bars
        self.assertEqual(d1_base_after_impulse(d1(impulse_at=29, base=(1, 2)), 1.0), {})  # impulse is last bar: no base yet

    def test_d1_base_no_lookahead(self):
        a = d1(impulse_at=24, down=True, base=(90, 95))
        b = {k: v + [999.0] for k, v in a.items()}
        self.assertNotEqual(d1_base_after_impulse(a, 1.0), d1_base_after_impulse(b, 1.0))  # new closed bar IS data
        cut = {k: v[:30] for k, v in b.items()}
        self.assertEqual(d1_base_after_impulse(a, 1.0), d1_base_after_impulse(cut, 1.0))   # nothing beyond cutoff used

    def test_scope_resolution_and_chain(self):
        rules = load_rules()
        na = scope_resolution(rules)
        self.assertEqual(set(na), {"G-CRYPTO-SCORE", "X-UX-CRB-BTW", "X-QA-RUNE", "G-STOP-CALC"})
        out = evaluate_chain(rules, na)
        self.assertEqual(out["counts"]["NOT_APPLICABLE"], 4)


if __name__ == "__main__":
    unittest.main()

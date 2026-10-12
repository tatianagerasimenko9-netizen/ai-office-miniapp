#!/usr/bin/env python3
"""stage_check/гейт етапів: D1/H4 та H1 проти напряму → мітки HTF_AGAINST/H1_AGAINST; OFFICE2_STAGE_GATE=block блокує, за замовчуванням (off) — ні. Нічого не змінює без явного перемикача."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import daria_steps as DS  # noqa: E402
from office2 import engine as EN  # noqa: E402

bad = []


def check(n, c):
    if not c:
        bad.append(n)
        print("FAIL", n)


def row(tf, with_t=False, against=False, trend=0):
    return {"tf": tf, "status": "USED", "trend_eff": trend, "with_trade": with_t, "against_trade": against, "zone": "discount"}


def th(d1=(0, 0), h4=(0, 0), h1=(0, 0), proof=False):
    r = lambda tf, x: row(tf, with_t=bool(x[0]), against=bool(x[1]))  # noqa: E731
    return {"dir": "LONG", "map": {"tfs": [r("D1", d1), r("H4", h4), r("H1", h1)]}, "integral": {"proof_h1": proof}}


a = DS.stage_check(th(h1=(0, 1)))
check("H1 проти → H1_AGAINST", a["h1"] == "AGAINST" and a["codes"] == ["H1_AGAINST"])
b = DS.stage_check(th(d1=(0, 1), h4=(1, 0)))
check("D1 проти, H4 за → D1/H4 AGAINST (будь-який проти)", b["d1_h4"] == "AGAINST" and "HTF_AGAINST" in b["codes"])
c = DS.stage_check(th(d1=(1, 0), h4=(0, 0), h1=(1, 0), proof=True))
check("за напрямом → без кодів", c["codes"] == [] and c["d1_h4"] == "CONFIRMED" and c["h1"] == "CONFIRMED" and c["h1_proof"] is True)
d = DS.stage_check(th())
check("діапазон → NEUTRAL, без кодів", d["d1_h4"] == "NEUTRAL" and d["codes"] == [])

os.environ.pop("OFFICE2_STAGE_GATE", None)
check("за замовчуванням гейт вимкнено", EN.stage_gate_mode() == "off" and EN.stage_gate_reason(th(h1=(0, 1))) is None)
os.environ["OFFICE2_STAGE_GATE"] = "block"
check("block: H1 проти → причина", "H1 проти" in (EN.stage_gate_reason(th(h1=(0, 1))) or ""))
check("block: D1/H4 і H1 проти → обидві причини", all(x in (EN.stage_gate_reason(th(d1=(0, 1), h1=(0, 1))) or "") for x in ("D1/H4", "H1")))
check("block: нейтрально → не блокує", EN.stage_gate_reason(th()) is None)
check("block: за напрямом → не блокує", EN.stage_gate_reason(th(d1=(1, 0), h1=(1, 0))) is None)
os.environ["OFFICE2_STAGE_GATE"] = "що_завгодно"
check("невідоме значення → off", EN.stage_gate_mode() == "off")
os.environ.pop("OFFICE2_STAGE_GATE", None)
# мітки в знімку
fl = EN.learning_flag_codes(0.1, None, {"btc_ret_24h": 0.4}, "SHORT", 0.8, EN.stage_codes(th(h1=(0, 1))))
check("мітки: AGAINST_BTC_24H + RISK_LT_1PCT + H1_AGAINST", set(fl) >= {"AGAINST_BTC_24H", "RISK_LT_1PCT", "H1_AGAINST"})
print("OK" if not bad else f"FAIL {bad}")
sys.exit(1 if bad else 0)

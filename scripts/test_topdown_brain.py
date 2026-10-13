#!/usr/bin/env python3
"""Інтеграція top-down у Brain v2.1: знімок READY несе topdown; annotate не змінює рішення; gate вимагає підтвердження M5 (інакше WAIT 4/4); hooks викликаються щонайбільше раз."""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_office2_brain2 as TB  # noqa: E402
from office2 import brain2 as B2  # noqa: E402

bad = []


def check(n, c):
    if not c:
        bad.append(n)
        print("FAIL", n)


c, seq = TB.closes_long()
b, ctx = TB.mk(c, seq["trigger"])
now = float(b["t"][-1] + 900)


def thesis(hooks=None, mode="annotate"):
    os.environ["OFFICE2_LTF_MODE"] = mode
    return B2.thesis(ctx, "LONG", now, TB.LEVELS, 10.0, hooks=hooks)


base = thesis(mode="off")
check("базовий READY", base and base["state"] == "READY")
check("off: topdown немає", "topdown" not in base)
ann = thesis()
check("annotate: READY незмінний (той самий вхід/SL/id)", ann["state"] == "READY" and ann["entry"] == base["entry"] and ann["sl"] == base["sl"] and ann["id"] == base["id"])
td = ann["topdown"]
check("topdown у знімку: 6 етапів, тип, суперечності, ltf", [s["tf"] for s in td["stages"]] == ["D1", "H4", "H1", "M15", "M5", "M1"] and td["scenario_type"]["type"] in ("CONTINUATION", "REVERSAL", "RANGE", "UNKNOWN") and isinstance(td["conflicts"], list))
check("без M5/M1 → ltf UNAVAILABLE (не вигадуємо підтвердження)", td["ltf"]["status"] == "UNAVAILABLE")

zl, zh = base["entry_zone"]
sl = base["sl"]
w = zh - zl


def m5_bars(confirm=True):
    spec = [(zh + 4 * w, zh + 4.5 * w, zh + 3.5 * w, zh + 4 * w)] * 6
    spec += [(zh + w, zh + 1.5 * w, zl + 0.2 * w, zh + 0.5 * w), (zh + 0.5 * w, zh + w, zh + 0.3 * w, zh + 0.8 * w)]
    spec += [(zh + 0.8 * w, zh + 2 * w, zh + 0.7 * w, zh + 1.8 * w)] if confirm else [(zh + 0.8 * w, zh + w, zh + 0.7 * w, zh + 0.9 * w)]
    spec += [(zh + 1.8 * w, zh + 2.1 * w, zh + 1.7 * w, zh + 2.0 * w)] * 3 if confirm else [(zh + 0.9 * w, zh + 1.2 * w, zh + 0.8 * w, zh + 1.0 * w)] * 3
    a = np.array(spec, float)
    return {"t": now - len(a) * 300 + np.arange(len(a)) * 300.0, "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}


def m1_bars():
    a = np.array([(zh + 1.9 * w, zh + 2 * w, zh + 1.8 * w, zh + 1.95 * w)] * 15, float)
    return {"t": now - 900 + np.arange(15) * 60.0, "o": a[:, 0], "h": a[:, 1], "l": a[:, 2], "c": a[:, 3]}


calls = {"m5": 0, "m1": 0}


def mk_hooks(confirm=True):
    def f5():
        calls["m5"] += 1
        return m5_bars(confirm)

    def f1():
        calls["m1"] += 1
        return m1_bars()
    return {"m5": f5, "m1": f1}


ann2 = thesis(mk_hooks(True))
check("annotate + M5 підтверджує → READY, ltf CONFIRMED", ann2["state"] == "READY" and ann2["topdown"]["ltf"]["status"] == "CONFIRMED")
check("хуки M5/M1 викликаються щонайбільше раз на оцінку кандидата (докази + top-down)", calls["m5"] <= 2 and calls["m1"] <= 2)
ann3 = thesis(mk_hooks(False))
check("annotate + M5 НЕ підтверджує → READY лишається, ltf PENDING (суперечність показано)", ann3["state"] == "READY" and ann3["topdown"]["ltf"]["status"] == "PENDING" and any(x["tf"] == "M5" for x in ann3["topdown"]["conflicts"]))
g_ok = thesis(mk_hooks(True), mode="gate")
check("gate + M5 підтверджує → READY", g_ok["state"] == "READY")
g_no = thesis(mk_hooks(False), mode="gate")
check("gate + M5 не підтверджує → WAIT 4/4, blocked_ready", g_no["state"] == "WAIT" and "WAIT 4/4" in g_no["reason"] and g_no.get("blocked_ready") is True)
g_none = thesis(None, mode="gate")
check("gate без даних M5 → WAIT 4/4 (немає підтвердження = немає READY)", g_none["state"] == "WAIT" and "WAIT 4/4" in g_none["reason"])
os.environ.pop("OFFICE2_LTF_MODE", None)
print("OK" if not bad else f"FAIL {bad}")
sys.exit(1 if bad else 0)

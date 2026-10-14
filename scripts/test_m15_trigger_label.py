"""Підпис M15-тригера в розборі: фактична умова Brain — бичаче/ведмеже закриття за СЕРЕДИНОЮ зони, а не за краєм зони (trigger_level)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from office2 import daria_steps as DS

bad = 0


def check(name, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else " :: " + str(info)))
    bad += 0 if ok else 1


def snap(direction, zone, trig, close):
    sg = 1 if direction == "LONG" else -1
    th = {"dir": direction, "entry": close, "sl": close - sg * 0.03, "zone": zone, "entry_zone": zone, "trigger_level": trig, "state": "READY",
          "sequence": [{"step": "тригер M15", "ok": True, "value": f"закриття {close} ≥ середини зони {sum(zone) / 2}"}],
          "targets": [{"p": close + sg * 0.03, "r": 1.0}], "invalidation": {"price": close - sg * 0.025, "why": "x"}}
    return {"thesis": th, **th}


def m15(direction, zone, trig, close):
    r = DS.build(snap(direction, zone, trig, close), None, None)
    return next(x for x in r["steps"] if x["id"] == "M15")


s = m15("LONG", [1.1483, 1.1646], 1.1646, 1.1616)     # FIL №0003: закриття 1.1616 нижче краю зони, але вище середини
mid = (1.1483 + 1.1646) / 2
check("LONG: тригер названо серединою зони, а не краєм 1,1646", "середини зони" in s["result"] and "1,1646" not in s["result"].split("тригер:")[-1].split(";")[0] and abs(s["condition"]["price"] - mid) < 1e-9, s["result"])
s = m15("SHORT", [0.005193, 0.005225], 0.005193, 0.005200)
check("SHORT: ведмеже закриття ≤ середини зони", "ведмеже" in s["result"] and "≤" in s["result"] and abs(s["condition"]["price"] - (0.005193 + 0.005225) / 2) < 1e-12, s["result"])
print("ALL OK" if not bad else f"FAILED {bad}")
_sys.exit(1 if bad else 0)

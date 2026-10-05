#!/usr/bin/env python3
"""Звіт якості READY: секції «Контроль симулятора» і «Надлишок над геометричною базою» будуються на синтетичних результатах (без мережі)."""
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
plans = json.load(open(ROOT / "data/research/ready_plans_2026-10-01_04.json"))
random.seed(3)
res = []
for p in plans:
    ct = float(p["ct"])
    f = random.choice(["SL", "TP1", None])
    res.append({"mid": p["mid"], "data_end": ct + 90000, "status": "STOP" if f == "SL" else "TP1" if f else "PENDING", "first": f, "tie": False, "entry_at": ct + 60,
                "at": {"ENTRY": ct + 60, **({"SL": ct + 3000} if f == "SL" else {}), **({"TP1": ct + 4000} if f == "TP1" else {})}, "result_at": ct + 3000})
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
    json.dump({"results": res, "symbols": 1, "generated": "t"}, fh)
out = subprocess.run([sys.executable, str(ROOT / "scripts/ready_quality_report.py"), "--plans", str(ROOT / "data/research/ready_plans_2026-10-01_04.json"), "--results", fh.name], capture_output=True, text=True)
assert out.returncode == 0, out.stderr[-500:]
t = out.stdout
assert "## Контроль симулятора" in t and "Планів з обома результатами" in t, t[-800:]
assert "## Надлишок над геометричною базою" in t and "кластерів symbol+direction" in t
assert "### Напрям" in t and "### Теза: свіжа / прострочена" in t and "### RR до TP1" in t
# кластерний ІВ присутній, надлишок рахується як факт − база
assert "кластерний 95% ІВ" in t
print("OK")

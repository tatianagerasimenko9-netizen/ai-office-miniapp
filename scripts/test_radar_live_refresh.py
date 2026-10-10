#!/usr/bin/env python3
"""Static smoke guard: Radar must visibly refresh live data without leaking timers."""
from pathlib import Path

html = (Path(__file__).resolve().parents[1] / "office_web" / "mini_v2.html").read_text(encoding="utf-8")
start = html.index("async function radar(){")
end = html.index("/* ---------- Сценарії ---------- */", start)
radar = html[start:end]
assert "setInterval" in radar and "30000" in radar, "Radar must auto-refresh at most every 30 seconds"
assert "cur==='radar'" in radar, "Radar timer must stop affecting other routes"
assert "symbols_last_hour" in radar and "o2.last_cycle_ts" in radar, "Show observed symbols and freshness"
assert "function go(r){" in html and "killPoll(); cur=r;" in html, "Navigation must clear live poll"
print("PASS: Radar refresh, data freshness and route cleanup")

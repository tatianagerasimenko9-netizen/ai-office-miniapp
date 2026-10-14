#!/usr/bin/env python3
"""B&R · TEST replay на реальних свічках Binance Futures M15 (data.binance.vision, лише GitHub Actions). Нічого не пише в production.
Для кожного періоду A–G: сигнали B&R (пробій → ретест → відбій) + контроль NR (вхід на пробої без ретесту, SL за рівнем) на тих самих барах.
Використання: python scripts/br_replay.py SYMBOL out.json"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import binance_vision_fetch as BV  # noqa: E402
from office_br import detect as D  # noqa: E402
from office_br import sim as S  # noqa: E402

PERIODS = {"A": ("2026-09-25", 14), "B": ("2026-10-09", 14), "C": ("2026-10-11", 2), "D": ("2026-08-28", 14), "E": ("2026-08-14", 14), "F": ("2026-07-31", 14), "G": ("2026-07-17", 14)}


def run(sym: str) -> dict:
    import os

    if os.environ.get("BR_MIN_RISK_PCT"):
        D.HYP["min_risk_pct"] = float(os.environ["BR_MIN_RISK_PCT"])      # варіант V2 (ГІПОТЕЗА)
    out = {"symbol": sym, "hyp": {k: (list(v) if isinstance(v, tuple) else v) for k, v in D.HYP.items()}, "periods": {}}
    for pid, (end, days) in PERIODS.items():
        e = date.fromisoformat(end)
        a = BV.fetch(sym, "15m", e - timedelta(days=days + 3), e + timedelta(days=4))
        if not a:
            out["periods"][pid] = {"error": "немає даних"}
            continue
        t, o, h, l, c = (list(map(float, a[k])) for k in ("t", "o", "h", "l", "c"))
        t_from = float(__import__("datetime").datetime(e.year, e.month, e.day, tzinfo=__import__("datetime").timezone.utc).timestamp()) - days * 86400
        t_to = t_from + days * 86400
        rows, ctrl = [], []
        for s in D.scan(t, o, h, l, c):
            if not (t_from <= s["confirm_ts"] < t_to):
                continue
            r = S.simulate(s, t, o, h, l, c)
            rows.append({"ts": s["confirm_ts"], "dir": s["direction"], "status": r["status"], "r": r["r_net"], "risk_atr": s["risk"] / s["atr"]})
            # контроль NR: вхід одразу після пробою, SL за рівнем на ту саму буферну відстань
            bi = s["break_i"]
            a_b = D.atr(h, l, c, bi, D.HYP["atr_n"])
            sg = 1 if s["direction"] == "LONG" else -1
            sl = s["level"] - sg * D.HYP["sl_buffer_atr"] * a_b
            risk = abs(c[bi] - sl)
            if risk > 0 and sg * (c[bi] - sl) > 0 and D.HYP["min_risk_atr"] * a_b <= risk <= D.HYP["max_risk_atr"] * a_b:
                fake = {"direction": s["direction"], "confirm_i": bi, "sl": sl, "targets": [{"p": c[bi] + sg * risk}]}
                rn = S.simulate(fake, t, o, h, l, c)
                ctrl.append({"ts": t[bi], "dir": s["direction"], "status": rn["status"], "r": rn["r_net"]})
        out["periods"][pid] = {"signals": rows, "control_nr": ctrl, "bars": len(c)}
        print(sym, pid, "signals", len(rows), "control", len(ctrl), flush=True)
    return out


if __name__ == "__main__":
    Path(sys.argv[2]).write_text(json.dumps(run(sys.argv[1]), ensure_ascii=False))

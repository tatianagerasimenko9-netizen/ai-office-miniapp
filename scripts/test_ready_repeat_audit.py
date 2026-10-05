#!/usr/bin/env python3
"""Самоперевірка аудиту повторів на синтетичному експорті: класи READY за часом, а не за порядком запису; нуль порівнянь = не перевірено."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ready_repeat_audit as A  # noqa: E402

PC = ["id", "ts", "sid", "ct", "entry", "sl", "tp1", "tp2", "tp3", "rejected", "msg_id", "risk_pct", "rr_net", "tags", "align", "bias", "phase_sigma", "btc_1h", "btc_4h", "n_evidence", "unsupported", "vt", "mode"]
EC = ["id", "ts", "type", "sid", "level", "price", "msg_id", "touched_ts", "sent_ts", "confirmed_ts", "scenario_id", "outcome", "result"]
RC = ["id", "ts", "sid", "confirmed_ts", "rejected", "outcome", "ttr_sec", "mfe_pct", "mae_pct", "filled", "reached"]


def plan(i, sym, ct, sl="0.99", tags="[\"a\"]"):
    return [i, "2026-10-04T00:00:00+00:00", f"SCN|{sym}|LONG|H1|h{i}", str(ct), "1.0", sl, "1.05", None, None, "false", str(9000 + i), "1.0", "2", tags, None, None, None, None, None, 1, None, str(ct + 86400), None]


def res(i, sym, ct, out, ttr):
    return [i, "2026-10-04T00:00:00+00:00", f"SCN|{sym}|LONG|H1|h{i}", str(ct), "false", out, str(ttr), "0.1", "0.2", "true", "[]"]


def run(plans, results, events=()):
    d = {"plan_cols": PC, "plans": plans, "event_cols": EC, "events": list(events), "result_cols": RC, "results": results, "atr_cols": [], "atr": []}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(d, f)
    out = subprocess.run([sys.executable, str(ROOT / "scripts/ready_repeat_audit.py"), "--events", f.name], capture_output=True, text=True)
    os.unlink(f.name)
    return out


def main() -> int:
    t0 = 1_790_000_000
    # A: перша (id1) → SL відомий до ct другої (id2) = «після SL»; id3 видана за 60 с після id2 = «пачка»
    pl = [plan(1, "AAAUSDT", t0), plan(2, "AAAUSDT", t0 + 3 * 3600), plan(3, "AAAUSDT", t0 + 3 * 3600 + 60),
          # B: перша ще не вирішена на момент другої (SL після) → «попередня ще не вирішена»
          plan(4, "BBBUSDT", t0), plan(5, "BBBUSDT", t0 + 3600)]
    rs = [res(1, "AAAUSDT", t0, "STOP", 1800), res(2, "AAAUSDT", t0 + 3 * 3600, "TP1", 600), res(3, "AAAUSDT", t0 + 3 * 3600 + 60, "STOP", 900),
          res(4, "BBBUSDT", t0, "STOP", 7200), res(5, "BBBUSDT", t0 + 3600, "STOP", 600)]
    # старі плани: now = max ct, тому фікс. горизонт 12 год не рахується; важливий лише розподіл класів
    out = run(pl, rs)
    assert out.returncode == 0, out.stderr
    txt = out.stdout
    rows = {l.split("|")[1].strip(): l for l in txt.splitlines() if l.startswith("| ") and "результат" not in l and "---" not in l}
    assert "| після SL | 1 |" in txt, txt
    assert "| пачка (<5 хв після попередньої) | 1 |" in txt, txt
    assert "| попередня ще не вирішена | 1 |" in txt, txt
    assert "| перша | 2 |" in txt, txt
    # те саме sid із rejected=true не змішується з результатами READY
    rs2 = rs + [[9, "x", "SCN|AAAUSDT|LONG|H1|h1", str(t0), "true", "TP1", "100", "1", "0", "true", "[]"]]
    t2 = run(pl, rs2).stdout
    assert "для ВІДХИЛЕНИХ" in t2 and "5 для READY" in t2, t2
    # нуль результатів = «не перевірено», не 0%
    t3 = run(pl, []).stdout
    assert "немає даних (не перевірено)" in t3, t3
    # однакові плани за 10 с, різні sid: літеральний дубль
    pl4 = [plan(1, "CCCUSDT", t0), plan(2, "CCCUSDT", t0 + 10)]
    t4 = run(pl4, []).stdout
    assert "Літеральні дублі READY" in t4 and "1 груп" in t4, t4
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

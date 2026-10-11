#!/usr/bin/env python3
"""Дослідження історії старих планів Лева/Office (вересень–жовтень) на свічках Binance-архіву: результат за свічками, ознаки ТІЛЬКИ з даних до рішення,
train/test за часом, Bonferroni. Нічого не пише в БД/Render/Telegram. Усе, що не перевірено, — UNKNOWN/INSUFFICIENT.
Використання: history_study.py out.json [sym1,sym2...]  (за замовчуванням — усі символи з фікстур)."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
FIX = ROOT / "fixtures" / "learning"


def load_plans():
    """Нормалізація двох джерел до {src,sid,sym,dir,tf,entry,sl,tp1,ts,valid,rej,tracker_out}. Нічого не видаляємо — непридатні лишаються з причиною."""
    out = []
    for r in json.load(open(FIX / "lev_history_2026-10.json"))["items"]:
        out.append({"src": "LEV_PLAN", "sid": r["sid"], "sym": r["sym"], "dir": r["dir"], "tf": r.get("tf"), "entry": r.get("entry"), "sl": r.get("sl"), "tp1": r.get("tp1"),
                    "ts": r.get("conf"), "valid": r.get("valid"), "rej": bool(r.get("rej")), "tracker_out": r.get("tracker_out")})
    for r in json.load(open(FIX / "lev_september_2026-09.json"))["items"]:
        ts = datetime.fromisoformat(r["ts"]).timestamp() if r.get("ts") else None
        lo, hi = r.get("lo"), r.get("hi")
        long_ = r["dir"] == "LONG"
        out.append({"src": "SEP_IDEA", "sid": r["sid"], "sym": r["sym"], "dir": r["dir"], "tf": "IDEA", "entry": (hi if long_ else lo) if lo and hi else None, "sl": r.get("sl"),
                    "tp1": r.get("tp1"), "ts": ts, "valid": ts + 86400 if ts else None, "rej": False, "tracker_out": r.get("out")})
    return out


def usable(p):
    if not all(p.get(k) for k in ("sym", "dir", "entry", "sl", "tp1", "ts", "valid")):
        return "NO_LEVELS"
    e, sl, tp = float(p["entry"]), float(p["sl"]), float(p["tp1"])
    if p["dir"] == "LONG" and not (sl < e < tp) or p["dir"] == "SHORT" and not (tp < e < sl):
        return "BAD_GEOMETRY"
    return "OK"


def dedup(plans):
    """Одна ідея = (символ, напрям, 6-годинне вікно); перша за часом. Оригінали не змінюються — лише позначка dup."""
    seen, res = {}, []
    for p in sorted(plans, key=lambda x: x["ts"] or 0):
        key = (p["sym"], p["dir"], int(p["ts"] // 21600))
        p["dup"] = key in seen
        seen.setdefault(key, p["sid"])
        res.append(p)
    return res


def candles_list(a, t0, t1):
    i0, i1 = int(np.searchsorted(a["t"], t0 - 900)), int(np.searchsorted(a["t"], t1 + 900))
    return [{"ts": float(a["t"][k]), "high": float(a["h"][k]), "low": float(a["l"][k])} for k in range(i0, min(i1, len(a["t"])))]


def main():
    from office2.learning import costs as C
    from office2.learning import feature_study as FS
    from office2.learning import history_features as HF
    import binance_vision_fetch as BV
    import office_signal_track as T

    plans = load_plans()
    inv = Counter()
    for p in plans:
        p["use"] = usable(p)
        inv[(p["src"], p["use"])] += 1
    ok = dedup([p for p in plans if p["use"] == "OK"])
    syms = sorted({p["sym"] for p in ok})
    if len(sys.argv) > 2 and sys.argv[2].strip():
        want = set(sys.argv[2].upper().split(","))
        syms = [s for s in syms if s in want]
    d_end = date.today()
    d0 = date(2026, 8, 20)
    btc = BV.fetch("BTCUSDT", "15m", d0, d_end - timedelta(days=1))
    rows, nodata, val = [], [], Counter()
    cover = defaultdict(lambda: Counter())
    for s in syms:
        try:
            a = BV.fetch(s, "15m", d0, d_end - timedelta(days=1))
            d1 = BV.fetch(s, "1d", d0 - timedelta(days=40), d_end - timedelta(days=1))
        except Exception as exc:  # noqa: BLE001
            print(f"[skip] {s}: {exc}")
            a, d1 = {}, {}
        for p in [x for x in ok if x["sym"] == s]:
            day = datetime.fromtimestamp(p["ts"], timezone.utc).date().isoformat()
            if not a:
                nodata.append(p["sid"])
                cover[day]["NO_CANDLES"] += 1
                continue
            plan = {"direction": p["dir"], "entry": p["entry"], "sl": p["sl"], "tp1": p["tp1"], "confirmed_ts": p["ts"], "valid_until_ts": p["valid"]}
            res = T.simulate(plan, candles_list(a, p["ts"], p["valid"] + 3 * 86400), now_ts=float(a["t"][-1]) + 900)
            st = res["status"]
            if p["src"] == "LEV_PLAN" and p.get("tracker_out"):
                val[(p["tracker_out"], st)] += 1
            cover[day][st] += 1
            if p["dup"]:
                continue
            if st not in ("STOP", "TP1", "TP2", "TP3"):
                continue                       # не заповнено / ще йде / тайм-аут: у вибірку результатів не входить
            e, sl, tp1 = float(p["entry"]), float(p["sl"]), float(p["tp1"])
            stop_pct = abs(e - sl) / e * 100.0
            cr = C.cost_r(stop_pct)
            if st == "STOP" and "TP1" not in res["reached"]:
                rr, tp, slh = -1.0 - cr, False, True
            else:
                rr, tp, slh = abs(tp1 - e) / abs(e - sl) - cr, True, False       # модель A: уся позиція на TP1 (стоп після TP1 = TP1 досягнуто)
            f = HF.extract(p, a, d1 or None, btc or None)
            rows.append({"ts": p["ts"], "r": round(rr, 4), "tp": tp, "sl": slh, "f": f, "sym": s, "src": p["src"]})
    rows.sort(key=lambda r: r["ts"])
    out = {"generated": datetime.now(timezone.utc).isoformat(), "inventory": {f"{k[0]}|{k[1]}": v for k, v in sorted(inv.items())},
           "plans_total": len(plans), "usable": len(ok), "dedup_unique": sum(1 for p in ok if not p["dup"]), "symbols": len(syms), "no_candles": len(nodata),
           "tracker_vs_candles": {f"{k[0]}→{k[1]}": v for k, v in sorted(val.items())},
           "coverage_by_day": {d: dict(c) for d, c in sorted(cover.items())}, "rows_n": len(rows)}
    for name, sel in (("ALL", rows), ("LEV_PLAN", [r for r in rows if r["src"] == "LEV_PLAN"]), ("SEP_IDEA", [r for r in rows if r["src"] == "SEP_IDEA"])):
        out[f"study_{name}"] = FS.study_rows(sel, HF.FEATURES) if sel else {"status": "INSUFFICIENT", "n": 0}
    out["per_symbol_stops"] = sorted(({"sym": s, "n": sum(1 for r in rows if r["sym"] == s), "sl": sum(1 for r in rows if r["sym"] == s and r["sl"]),
                                       "sum_r": round(sum(r["r"] for r in rows if r["sym"] == s), 2)} for s in {r["sym"] for r in rows}), key=lambda x: x["sum_r"])[:40]
    json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k not in ("coverage_by_day", "study_ALL", "study_LEV_PLAN", "study_SEP_IDEA")}, ensure_ascii=False, indent=1))
    for name in ("ALL", "LEV_PLAN", "SEP_IDEA"):
        st = out[f"study_{name}"]
        print(f"\n== {name}: status={st.get('status')} n={st.get('n')} mean_r={st.get('overall_mean_r')} win={st.get('overall_win')} cells={st.get('cells_tested')}")
        for c in st.get("stable", []):
            print("  STABLE", c["feature"], c["value"], "n", c["n"], "mean", c["mean_r"], "train", c["train_mean"], "test", c["test_mean"], c["status"])
        print("  oos_filter:", json.dumps(st.get("oos_filter"), ensure_ascii=False, default=str)[:600])


if __name__ == "__main__":
    main()

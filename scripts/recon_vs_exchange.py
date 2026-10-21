#!/usr/bin/env python3
"""Звірка супроводу Office2 із біржею. Незалежний трекер (інша реалізація, ніж office_signal_track) перераховує ENTRY/TP1-3/SL/EXPIRED кожного доставленого READY за СИРИМИ
1-хв свічками Binance Futures (data.binance.vision) і порівнює з тим, що записано в production (office_events SCENARIO_MILESTONE; знімок у docs/office2/recon/).
Правила (ті самі, що задокументовані в тестах супроводу, не нові): вхід — перша хвилина ≥ confirmed_ts і < valid_until, діапазон якої містить ціну входу; після входу (включно з тією ж хвилиною) SL перед ціллю в одній хвилині;
TP — wick; після SL або TP3 сценарій завершено; немає входу до valid_until → EXPIRED. Лише читання; нічого не пише в production.
Використання: python scripts/recon_vs_exchange.py plans.json milestones.json out.json"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def track(plan, t, h, l):
    """plan = (sid, sym, dir, entry, sl, tp1, tp2, tp3, confirmed, valid_until, msg). Повертає {level: minute_open_ts}."""
    sid, sym, d, entry, sl, tp1, tp2, tp3, conf, valid = plan[:10]
    long_ = d == "LONG"
    tps = [x for x in (tp1, tp2, tp3)]
    out = {}
    filled = None
    for i in range(len(t)):
        ti = float(t[i])
        if ti < conf:
            continue
        if filled is None:
            if ti >= valid:
                out["EXPIRED"] = valid
                return out
            if l[i] <= entry <= h[i]:
                filled = ti
                out["ENTRY"] = ti
            else:
                continue
        hit_sl = (l[i] <= sl) if long_ else (h[i] >= sl)
        if hit_sl:
            out["SL"] = ti
            return out
        for k, tp in enumerate(tps, 1):
            lv = f"TP{k}"
            if tp is None or lv in out:
                continue
            if (h[i] >= tp) if long_ else (l[i] <= tp):
                out[lv] = ti
        if "TP3" in out or (tps[2] is None and "TP2" in out):
            return out
    if filled is None and "EXPIRED" not in out and float(t[-1]) >= valid:
        out["EXPIRED"] = valid
    return out


def main(pf, mf, outf):
    import binance_vision_fetch as BV

    plans = json.loads(Path(pf).read_text())
    ms = json.loads(Path(mf).read_text())
    db = defaultdict(dict)
    for sid, lv, touched, sent, msg, src in ms:
        db[sid].setdefault(lv, []).append({"touched": float(touched), "sent": float(sent), "msg": msg, "src": src})
    by_sym = defaultdict(list)
    for p in plans:
        by_sym[p[1]].append(p)
    today = datetime.now(timezone.utc).date()
    rows, lat = [], []
    for sym, ps in sorted(by_sym.items()):
        t0 = min(p[8] for p in ps)
        d0 = datetime.fromtimestamp(t0, timezone.utc).date()
        a = BV.fetch(sym, "1m", d0, today)
        if not a:
            for p in ps:
                rows.append({"sid": p[0], "sym": sym, "error": "немає архіву 1m"})
            continue
        t, h, l = a["t"], a["h"], a["l"]
        data_end = float(t[-1]) + 60
        for p in ps:
            calc = track(p, t, h, l)
            rec = db.get(p[0], {})
            row = {"sid": p[0], "sym": sym, "dir": p[2], "data_end": data_end, "calc": calc, "db": {k: [x["touched"] for x in v] for k, v in rec.items()}, "issues": []}
            for lv, ts in calc.items():
                if lv == "EXPIRED":
                    continue
                got = rec.get(lv)
                if not got:
                    if ts < data_end - 3600:
                        row["issues"].append(f"MISSING_IN_DB {lv} true={int(ts)}")
                    continue
                if len(got) > 1:
                    row["issues"].append(f"DUPLICATE_IN_DB {lv} x{len(got)}")
                g = got[0]
                diff = ts - g["touched"]          # >0: у БД раніше (грубий бар), <0: у БД ПІЗНІШЕ за істинний дотик
                if diff < -60 or diff > 360:
                    row["issues"].append(f"TIME_MISMATCH {lv} true={int(ts)} db={int(g['touched'])} diff={int(diff)}")
                if g["msg"]:
                    lat.append({"sid": p[0], "lv": lv, "src": g["src"], "lat_max": g["sent"] - ts, "lat_min": g["sent"] - ts - 60})
            for lv, got in rec.items():
                if lv in ("EXPIRED",):
                    continue
                if lv not in calc and got[0]["touched"] < data_end - 3600:
                    row["issues"].append(f"EXTRA_IN_DB {lv} db={int(got[0]['touched'])} (біржа цього рівня не підтверджує)")
            rows.append(row)
    # інваріант без біржі: після SL / останнього TP подій бути не може (ENTRY не рахуємо)
    post = []
    pl = {p_[0]: p_ for p_ in plans}
    for sid, lvs in db.items():
        flat = sorted((x["sent"], lv, x["msg"], x["src"]) for lv, xs in lvs.items() for x in xs)
        term = None
        for sent, lv, msg, src in flat:
            if term and lv != "ENTRY":
                post.append({"sid": sid, "level": lv, "msg": msg, "src": src, "after": term})
            if term is None and (lv in ("SL", "TP3") or (lv == "TP2" and sid in pl and pl[sid][7] is None)):
                term = lv
    v = sorted(x["lat_max"] for x in lat)
    n = len(v)
    summ = {"plans": len(rows), "events_compared": n, "lat_max_p50": v[n // 2] if n else None, "lat_max_p90": v[int(n * .9)] if n else None, "lat_max_p95": v[int(n * .95)] if n else None, "lat_max_max": v[-1] if n else None,
            "over_120s": sum(1 for x in v if x > 120), "over_300s": sum(1 for x in v if x > 300),
            "issues": sum(len(r.get("issues", [])) for r in rows), "plans_with_issues": sum(1 for r in rows if r.get("issues")), "post_terminal_events": len(post)}
    Path(outf).write_text(json.dumps({"summary": summ, "rows": rows, "latency": lat, "post_terminal": post}, ensure_ascii=False, indent=1))
    print(json.dumps(summ, ensure_ascii=False, indent=1))
    for x in post:
        print("POST_TERMINAL", x["sid"], x["level"], "msg", x["msg"], x["src"], "після", x["after"])
    for r in rows:
        for i in r.get("issues", []):
            print(r["sid"], r["sym"], i)
        if r.get("error"):
            print(r["sid"], r["error"])


if __name__ == "__main__":
    main(*sys.argv[1:4])

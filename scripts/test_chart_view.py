#!/usr/bin/env python3
"""Telegram-графік READY: головний ТФ H1/H4 з передісторією + збільшена вставка M15, ТФ підписано, зона входу виділена, цілі не стискають свічки, жодних майбутніх свічок.
Реальні дані Binance Futures (FIL №3, BTC №4, SEI №7 від 14.10.2026): scripts/fixtures/chart_view_real_2026-10-14.json."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import office_ready_card as C  # noqa: E402
from office2 import chart_view as CV  # noqa: E402

bad = 0


def check(name, ok, info=""):
    global bad
    print(("OK   " if ok else "FAIL ") + name + ("" if ok else f" :: {info}"))
    bad += 0 if ok else 1


FX = json.loads((Path(__file__).parent / "fixtures" / "chart_view_real_2026-10-14.json").read_text(encoding="utf-8"))
iso = lambda t: datetime.fromtimestamp(float(t), tz=timezone.utc).isoformat()  # noqa: E731
rows = lambda a: [{"ts": iso(r[0]), "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": 1.0} for r in a]  # noqa: E731


def arr(a):
    return {"t": np.array([r[0] for r in a], float), "o": np.array([r[1] for r in a]), "h": np.array([r[2] for r in a]), "l": np.array([r[3] for r in a]), "c": np.array([r[4] for r in a]), "v": np.ones(len(a))}


def ctx_of(case):
    m15 = case["m15"]
    first = m15[0][0]
    pre = [r[:5] for r in case["h1_pre"] if r[0] + 3600 <= first + 1e-6]
    by = {}
    for r in m15:
        by.setdefault(r[0] // 3600 * 3600, []).append(r)
    full = [[hs, rs[0][1], max(x[2] for x in rs), min(x[3] for x in rs), rs[-1][4]] for hs, rs in sorted(by.items()) if len(rs) == 4]
    return {"m15": arr(m15), "h1": arr(pre + full)}


def th_of(key, case):
    th = {"event": {"ts": case["ev_ts"], "extreme": case["ev_extreme"], "level": {"p": case["ev_level"], "kind": case["ev_kind"]} if case["ev_level"] else None,
                    "src": "SWEEP" if case["ev_kind"] != "ORIGIN" else "ORIGIN", "prior": {"bars": 12}}, "break": {"ts": case["brk_ts"], "level": case["brk_level"]}, "level": {"p": case["ev_level"]} if case["ev_level"] else {}}
    if key == "BTC":
        th["event"]["origin"] = {"zone": [83605.19, 84340.2], "impulse": {"origin_ts": 1791784800}}
    return th


os.makedirs("/tmp/chart_view_test", exist_ok=True)
for key in ("FIL", "BTC", "SEI"):
    case, now = FX[key], float(FX[key]["created"])
    ctx, th, d = ctx_of(case), th_of(key, FX[key]), case["dir"]
    view = CV.choose(th, now)
    check(f"{key}: головний ТФ H1, вікно ≥3 доби історії (не механічно: за довжиною структури), 40–140 свічок", view["tf"] == "H1" and CV.MIN_BARS <= view["bars"] <= CV.MAX_BARS and view["window_sec"] >= 3 * 86400, view)
    vr = CV.build_rows(ctx, view, now)
    last_close = max(datetime.fromisoformat(r["ts"]).timestamp() + 3600 for r in vr if not r.get("forming")) if any(not r.get("forming") for r in vr) else 0
    check(f"{key}: жодних майбутніх свічок — повні бари закриті ≤ часу READY, свічка, що формується, зібрана лише із закритих M15", last_close <= now + 1e-6 and (not vr[-1].get("forming") or vr[-1]["close"] == case["m15"][-1][4]), (last_close, now))
    mk = CV.marks(th, rows(case["m15"]), d)
    kinds = [m["kind"] for m in mk]
    check(f"{key}: структурні позначки — лише підтверджені даними ({kinds})", all(k in ("sweep", "break", "origin") for k in kinds) and (("break" in kinds) or key == "SEI"), kinds)
    if "break" in kinds:
        b = next(m for m in mk if m["kind"] == "break")
        sw = [r for r in case["m15"] if r[0] == b["t0"]]
        check(f"{key}: зламаний свінг знайдено в реальних свічках (екстремум = рівню)", bool(sw) and abs((sw[0][2] if d == "LONG" else sw[0][3]) - b["price"]) < abs(b["price"]) * 1e-6, b)
    ins = CV.inset_view(th, rows(case["m15"]), d, now)
    check(f"{key}: вставка M15 32–64 свічки", ins is not None and 32 <= ins["bars"] <= 64 and ins["label"] == "M15")
    tp = [x[1] for x in case["tp"]]
    path = f"/tmp/chart_view_test/{key}.png"
    r = C.render(symbol=case["sym"], direction=d, candles=vr, entry=case["entry"], zone=case["zone"], sl=case["sl"], tp1=tp[0], tp2=tp[1], tp3=tp[2], ready_price=case["entry"], key_level=None, path=path,
                 evidence=mk, max_bars=view["bars"], tf_label=view["tf"], story=CV.story(th, case["zone"], case["entry"], lambda x: C._num(x, case["sym"])), inset=dict(ins, marks=mk), height_px=635)
    from PIL import Image

    im = Image.open(path)
    check(f"{key}: картка 1000×1230 PNG, ТФ H1 підписано, вставка M15 намальована без збоїв, підписи не втрачені", r["ok"] and im.size == (1000, 1230) and r["drawn"]["tf"] == "H1" and not any(str(x).startswith("inset:") for x in r["drawn"]["labels_skipped"]), r.get("reason") or r["drawn"]["labels_skipped"])
    old = C.render(symbol=case["sym"], direction=d, candles=rows(case["m15"]), entry=case["entry"], zone=case["zone"], sl=case["sl"], tp1=tp[0], tp2=tp[1], tp3=tp[2], ready_price=case["entry"], key_level=None, path=f"/tmp/chart_view_test/{key}_old.png")
    check(f"{key}: стара картка (без нових параметрів) малюється як раніше", old["ok"] and Image.open(f"/tmp/chart_view_test/{key}_old.png").size == (1000, 1230) and old["drawn"]["tf"] is None)

# далекі цілі не стискають свічки: TP2/TP3 на краю зі стрілкою, а не «розтягнення осі»
case = FX["FIL"]
far = C.render(symbol="FILUSDT", direction="LONG", candles=rows(case["m15"]), entry=case["entry"], zone=case["zone"], sl=case["sl"], tp1=1.1931, tp2=1.60, tp3=2.4, ready_price=case["entry"], key_level=None,
               path="/tmp/chart_view_test/far.png", tf_label="M15", max_bars=96)
check("далекі TP2/TP3: показані стрілкою біля краю, свічки не стиснуті (нова картка)", far["ok"] and far["drawn"]["tp2_edge"] and far["drawn"]["tp3_edge"], far.get("drawn"))
check("довга структура (10 діб) → H4, а не H1", CV.choose({"event": {"ts": 1791941400 - 10 * 86400, "src": "SWEEP"}}, 1791941400.0)["tf"] == "H4")
print("ALL OK" if not bad else f"FAILED {bad}")
sys.exit(1 if bad else 0)

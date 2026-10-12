#!/usr/bin/env python3
"""Дослідження якості торгових результатів AI Office на НЕЗАЛЕЖНИХ свічках Binance Futures (data.binance.vision, 1m/15m/1d). Лише читання.

Вхід: scripts/fixtures/paper_rows_*.json (вибірка office2_paper_position з production). Для кожної угоди:
  1) незалежний перерахунок результату по 1m-свічках (перевірка paper-рушія);
  2) контекст на момент сигналу БЕЗ майбутнього (BTC 1h/4h/24h, монета 4h/24h, H4/D1-тренд);
  3) контрфактуальні варіанти на ТИХ САМИХ угодах: беззбитковість після +1R, часткова фіксація на TP1, ширший SL, дзеркальний напрям,
     затримка входу 1/3/5/15 хв; випадкова нульова модель (та сама геометрія SL/TP у випадкові моменти того ж символу й напрямку);
  4) кластерний bootstrap (угоди одного 15-хв бару корельовані — рахуються як одна спостережена одиниця).
Правила з джерел НЕ змінюються; усе — shadow-аналітика. Фактичні результати не підміняються гіпотетичними: окремі колонки."""
from __future__ import annotations

import csv
import io
import json
import random
import statistics
import sys
import time
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import binance_vision_fetch as BV  # noqa: E402
from office2.learning import costs as COSTS  # noqa: E402

COST = COSTS.cost_pct() / 100.0          # частка ціни за коло (0,15 %)
HORIZON_MIN = 48 * 60
NULL_SAMPLES = 40
SEED = 20261012


# ----------------------------------------------------------------------------- дані
def _get(url, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ai-office-quality/1.0"}), timeout=40) as r:
                return r.read()
        except urllib.error.HTTPError as e:  # noqa: PERF203
            if e.code == 404:
                return None
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.5 * (k + 1))
    return None


def fapi_1m(sym, t0, t1):
    out = []
    cur = int(t0 * 1000)
    while cur < t1 * 1000:
        raw = _get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1m&startTime={cur}&limit=1500")
        if not raw:
            break
        js = json.loads(raw)
        if not js:
            break
        out += [(k[0] / 1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in js]
        cur = int(js[-1][0]) + 60000
        if len(js) < 1500:
            break
    return out


def load_1m(sym, d0, d1):
    """1m з добових архівів [d0,d1]; для днів без архіву — fapi (може бути недоступний із регіону раннера — тоді покриття неповне, це видно у звіті)."""
    rows, missing = [], []
    for k in range((d1 - d0).days + 1):
        d = d0 + timedelta(days=k)
        raw = _get(f"{BV.BASE}/daily/klines/{sym}/1m/{sym}-1m-{d.isoformat()}.zip")
        if raw:
            z = zipfile.ZipFile(io.BytesIO(raw))
            for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8")):
                if row and row[0].strip().isdigit():
                    t = float(row[0])
                    t = t / 1e6 if t > 1e14 else t / 1e3
                    rows.append((t, float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])))
        else:
            missing.append(d)
    if missing:
        t0 = datetime(missing[0].year, missing[0].month, missing[0].day, tzinfo=timezone.utc).timestamp()
        got = fapi_1m(sym, t0, time.time())
        rows += got
    rows = sorted({r[0]: r for r in rows}.values())
    if not rows:
        return None
    a = np.array(rows)
    return {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "missing_days": [m.isoformat() for m in missing]}


def ema(x, n):
    k = 2.0 / (n + 1.0)
    e = x[0]
    for v in x[1:]:
        e = v * k + e * (1 - k)
    return e


def context(sym, btc15, a15, d1, ts0, direction):
    """Ознаки лише з ЗАКРИТИХ барів до ts0 (без майбутнього)."""
    def upto(a, w):
        m = a["t"] + w <= ts0
        return {k: v[m] for k, v in a.items() if k in ("t", "o", "h", "l", "c")}
    out = {}
    b = upto(btc15, 900)
    c = upto(a15, 900)
    if len(b["c"]) >= 100 and len(c["c"]) >= 100:
        r = lambda arr, n: (arr[-1] / arr[-1 - n] - 1.0) * 100.0  # noqa: E731
        out.update(btc_1h=r(b["c"], 4), btc_4h=r(b["c"], 16), btc_24h=r(b["c"], 96), coin_4h=r(c["c"], 16), coin_24h=r(c["c"], 96))
        n4 = len(c["c"]) // 16
        h4 = c["c"][len(c["c"]) - n4 * 16:].reshape(n4, 16)[:, -1]
        out["h4_trend"] = 1 if h4[-1] > ema(h4[-30:], 20) else -1
        nb = len(b["c"]) // 16
        hb = b["c"][len(b["c"]) - nb * 16:].reshape(nb, 16)[:, -1]
        out["btc_h4_trend"] = 1 if hb[-1] > ema(hb[-30:], 20) else -1
    dd = upto(d1, 86400)
    if len(dd["c"]) >= 12:
        out["d1_trend"] = 1 if dd["c"][-1] > float(np.mean(dd["c"][-10:])) else -1
    sg = 1 if direction == "LONG" else -1
    out["dir"] = sg
    for k in ("h4_trend", "d1_trend", "btc_h4_trend"):
        if k in out:
            out[k + "_al"] = "with" if out[k] == sg else "against"
    if "btc_24h" in out:
        out["btc24_al"] = "with" if (out["btc_24h"] > 0) == (sg > 0) else "against"
        out["btc4_al"] = "with" if (out["btc_4h"] > 0) == (sg > 0) else "against"
    return out


# ----------------------------------------------------------------------------- симуляція
def simulate(bars, i0, direction, entry, sl, tp1, tp2=None, be_at_r=None, partial=None, horizon=HORIZON_MIN):
    """Один прохід 1m-барів з i0. SL першим, якщо SL і TP у одному барі. Повертає dict(R, out, mfe, mae, bars). R — після витрат COST (від ризику)."""
    sg = 1.0 if direction == "LONG" else -1.0
    risk = abs(entry - sl)
    if risk <= 0:
        return None
    risk_frac = risk / entry
    cost_r = COST / risk_frac
    h, l, c = bars["h"], bars["l"], bars["c"]
    n = min(len(c), i0 + horizon)
    cur_sl, be_on, took, realized = sl, False, 0.0, 0.0
    mfe = mae = 0.0
    for i in range(i0, n):
        hi, lo = h[i], l[i]
        fav = ((hi if sg > 0 else lo) - entry) * sg / risk
        adv = (entry - (lo if sg > 0 else hi)) * sg / risk
        # спочатку стоп (консервативно)
        if (lo <= cur_sl) if sg > 0 else (hi >= cur_sl):
            r_stop = (cur_sl - entry) * sg / risk
            tot = realized + (1.0 - took) * r_stop
            mae = max(mae, adv)
            return {"R": tot - cost_r, "out": "BE" if be_on and abs(r_stop) < 1e-9 else ("SL" if r_stop < 0 else "SL+"), "mfe": mfe, "mae": mae, "bars": i - i0 + 1, "i_exit": i}
        mfe, mae = max(mfe, fav), max(mae, adv)
        if partial is not None and took == 0.0 and ((hi >= tp1) if sg > 0 else (lo <= tp1)):
            realized += partial * (tp1 - entry) * sg / risk
            took = partial
            cur_sl = entry
            be_on = True
            if tp2 is None:
                tp2 = entry + sg * 2.0 * abs(tp1 - entry)
            continue
        tgt = tp2 if (partial is not None and took > 0 and tp2 is not None) else tp1
        if (hi >= tgt) if sg > 0 else (lo <= tgt):
            r_t = (tgt - entry) * sg / risk
            return {"R": realized + (1.0 - took) * r_t - cost_r, "out": "TP", "mfe": mfe, "mae": mae, "bars": i - i0 + 1, "i_exit": i}
        if be_at_r is not None and not be_on and fav >= be_at_r:
            cur_sl, be_on = entry, True
    last = c[n - 1]
    r_mtm = (last - entry) * sg / risk
    return {"R": realized + (1.0 - took) * r_mtm - cost_r, "out": "OPEN", "mfe": mfe, "mae": mae, "bars": n - i0, "i_exit": n - 1}


def boot(vals_by_cluster, B=2000, rng=None):
    rng = rng or random.Random(SEED)
    cl = list(vals_by_cluster.values())
    if len(cl) < 3:
        return None
    ms = []
    for _ in range(B):
        s = [rng.choice(cl) for _ in cl]
        tot = sum(sum(x) for x in s)
        cnt = sum(len(x) for x in s)
        ms.append(tot / cnt if cnt else 0.0)
    ms.sort()
    return ms[int(0.025 * B)], ms[int(0.975 * B)]


def summ(items, key="R", label=""):
    """items: list of dict(R, out, cl)."""
    done = [x for x in items if x.get("out") != "OPEN" and x.get(key) is not None]
    allx = [x for x in items if x.get(key) is not None]
    if not allx:
        return f"{label:<34} n=0"
    rs = [x[key] for x in allx]
    wins = sum(1 for x in done if x[key] > 0)
    cls = defaultdict(list)
    for x in allx:
        cls[x["cl"]].append(x[key])
    ci = boot(cls)
    cis = f" CI[{ci[0]:+.2f};{ci[1]:+.2f}]" if ci else ""
    return f"{label:<34} n={len(allx):<3} кластерів={len(cls):<3} закр.={len(done):<3} win={100.0 * wins / max(1, len(done)):4.0f}%  E[R]={statistics.mean(rs):+.3f}  ΣR={sum(rs):+.1f}{cis}"


# ----------------------------------------------------------------------------- основна логіка
def main(fixture, out_json):
    fx = json.loads(Path(fixture).read_text())
    cols = fx["cols"]
    rows = [dict(zip(cols, r)) for r in fx["rows"]]
    rows = [r for r in rows if r.get("fill_ts")]
    syms = sorted({r["symbol"] for r in rows} | {"BTCUSDT"})
    t_min = min(r["generated_ts"] for r in rows)
    d0 = datetime.fromtimestamp(t_min, timezone.utc).date()
    d1 = datetime.now(timezone.utc).date()
    print(f"[study] {len(rows)} угод, {len(syms)} символів, 1m {d0}..{d1}", flush=True)
    data, ctx_src = {}, {}
    for s in syms:
        m1 = load_1m(s, d0, d1)
        a15 = BV.fetch(s, "15m", d0 - timedelta(days=12), d1)
        dd = BV.fetch(s, "1d", d0 - timedelta(days=40), d1)
        data[s] = m1
        ctx_src[s] = (a15, dd)
    cover = {s: (None if not data[s] else (datetime.fromtimestamp(data[s]["t"][0], timezone.utc).strftime("%d.%m %H:%M"), datetime.fromtimestamp(data[s]["t"][-1], timezone.utc).strftime("%d.%m %H:%M"), data[s]["missing_days"])) for s in syms}
    print("[study] покриття 1m:", json.dumps({k: v for k, v in list(cover.items())[:4]}, ensure_ascii=False), "…", flush=True)
    btc15, _ = ctx_src["BTCUSDT"]

    trades, rng = [], random.Random(SEED)
    for r in rows:
        s = r["symbol"]
        m1 = data.get(s)
        if not m1:
            continue
        sg = 1.0 if r["direction"] == "LONG" else -1.0
        i0 = int(np.searchsorted(m1["t"], r["fill_ts"] - 1))
        if i0 >= len(m1["t"]) - 2:
            continue
        entry = r["fill_price"]
        sl, tp1, tp2 = r["sl"], r["tp1"], r.get("tp2")
        risk = abs(entry - sl)
        dirn = r["direction"]
        cl = r["generated_ts"]
        base = simulate(m1, i0, dirn, entry, sl, tp1)
        if not base:
            continue
        t = {"sid": r["scenario_id"], "sym": s, "dir": dirn, "kind": r["kind"], "scope": r["scope"], "cl": cl, "ts": r["generated_ts"], "paper_R": r.get("r_a"), "paper_out": r.get("close_reason"),
             "risk_pct": risk / entry * 100.0, "tp1_r": abs(tp1 - entry) / risk, "slip_r": ((entry - r["plan_entry"]) * sg / risk) * -1.0}
        t.update({f"b_{k}": v for k, v in base.items()})
        t["R"], t["out"] = base["R"], base["out"]
        a15, dd = ctx_src[s]
        if a15 and dd and btc15:
            t["ctx"] = context(s, btc15, a15, dd, r["generated_ts"], dirn)
        # після SL: чи дійшла ціна до TP1 пізніше (збір ліквідності), наскільки далі проти
        if base["out"] == "SL":
            j = base["i_exit"] + 1
            k = min(len(m1["t"]), j + 24 * 60)
            if j < len(m1["t"]):
                seg_h, seg_l = m1["h"][j:k], m1["l"][j:k]
                t["after_sl_tp1"] = bool((seg_h.max() >= tp1) if sg > 0 else (seg_l.min() <= tp1))
                t["after_sl_cov_min"] = int(k - j)
        # варіанти
        v = {}
        v["BE@1R"] = simulate(m1, i0, dirn, entry, sl, tp1, be_at_r=1.0)
        v["BE@0.5R"] = simulate(m1, i0, dirn, entry, sl, tp1, be_at_r=0.5)
        t2 = tp2 if tp2 else None
        v["50%TP1+BE→TP2"] = simulate(m1, i0, dirn, entry, sl, tp1, tp2=t2, partial=0.5)
        v["SL×1.5"] = simulate(m1, i0, dirn, entry, entry - sg * 1.5 * risk, tp1)
        v["SL×2"] = simulate(m1, i0, dirn, entry, entry - sg * 2.0 * risk, tp1)
        v["дзеркало"] = simulate(m1, i0, "SHORT" if dirn == "LONG" else "LONG", entry, entry + sg * risk, entry - sg * abs(tp1 - entry))
        for dm in (1, 3, 5, 15):
            j = i0 + dm
            if j < len(m1["t"]) - 2:
                e2 = float(m1["o"][j])
                inside = (e2 > sl and e2 < tp1) if sg > 0 else (e2 < sl and e2 > tp1)
                v[f"затримка {dm}хв"] = simulate(m1, j, dirn, e2, sl, tp1) if inside else None
        for k_, x in v.items():
            if x:
                t[f"v_{k_}"] = x["R"]
                t[f"o_{k_}"] = x["out"]
        # нульова модель: та сама геометрія у випадкові моменти (без перетину з реальним входом ±30 хв)
        sl_f, tp_f = risk / entry, abs(tp1 - entry) / entry
        lo_i, hi_i = 0, len(m1["t"]) - 60
        nulls = []
        tries = 0
        while len(nulls) < NULL_SAMPLES and tries < 400 and hi_i > lo_i:
            tries += 1
            j = rng.randrange(lo_i, hi_i)
            if abs(j - i0) < 30:
                continue
            e2 = float(m1["o"][j])
            nulls.append(simulate(m1, j, dirn, e2, e2 * (1 - sg * sl_f), e2 * (1 + sg * tp_f), horizon=HORIZON_MIN))
        nulls = [x for x in nulls if x]
        if nulls:
            t["null_R"] = statistics.mean(x["R"] for x in nulls)
            t["null_win"] = sum(1 for x in nulls if x["R"] > 0) / len(nulls)
        trades.append(t)

    L = []
    P = L.append
    P("# Дослідження якості торгових результатів (незалежний перерахунок на 1m Binance Futures)")
    P(f"Вибірка: {len(trades)} угод із paper-таблиці production (10–12.10.2026), витрати кола {COST * 100:.2f} % (office2.learning.costs), SL першим у одному барі, горизонт {HORIZON_MIN // 60} год.")
    nk = len({t['cl'] for t in trades})
    P(f"Незалежних спостережень (кластери за барами сигналу): {nk} — угоди одного бару корельовані (альти рухаються разом).")
    miss = {s: v[2] for s, v in cover.items() if v and v[2]}
    if miss:
        P(f"Дні без архіву (докачано fapi, якщо доступний): {json.dumps({k: v for k, v in list(miss.items())[:3]})} …")
    P("")
    # 1) валідація paper-рушія
    comp = [t for t in trades if t["paper_out"] in ("SL", "TP1") and t["b_out"] in ("SL", "TP")]
    agree = sum(1 for t in comp if (t["paper_out"] == "SL") == (t["b_out"] == "SL"))
    P(f"## 1. Незалежна перевірка paper-рушія\nЗбіг SL/TP із нашим перерахунком на 1m: {agree}/{len(comp)}.")
    dis = [t for t in comp if (t["paper_out"] == "SL") != (t["b_out"] == "SL")]
    for t in dis[:8]:
        P(f"  розбіжність: {t['sym']} {t['dir']} {datetime.fromtimestamp(t['ts'], timezone.utc):%d.%m %H:%M} paper={t['paper_out']} replay={t['b_out']}")
    P("")
    # 2) базова статистика
    P("## 2. Базова статистика (перерахунок, SL/TP1 як у paper; E[R] після витрат)")
    for lab, fl in (("усі", lambda t: True), ("CONTROL (радар, миттєвий вхід)", lambda t: t["scope"] == "CONTROL"), ("доставлені (LIVE+BACKFILL)", lambda t: t["scope"] in ("LIVE", "BACKFILL")),
                    ("LONG", lambda t: t["dir"] == "LONG"), ("SHORT", lambda t: t["dir"] == "SHORT")):
        P(summ([t for t in trades if fl(t)], "R", lab))
    nul = [{"R": t["null_R"], "out": "X", "cl": t["cl"]} for t in trades if "null_R" in t]
    P(summ(nul, "R", "нульова модель (випадковий час)"))
    for d in ("LONG", "SHORT"):
        P(summ([{"R": t["null_R"], "out": "X", "cl": t["cl"]} for t in trades if "null_R" in t and t["dir"] == d], "R", f"  нуль {d}"))
    P("")
    # 3) що сталось з SL
    sls = [t for t in trades if t["b_out"] == "SL"]
    P(f"## 3. Анатомія SL ({len(sls)} стопів)")
    bucket = defaultdict(int)
    for t in sls:
        if t["b_mfe"] >= 1.0:
            bucket["був ≥ +1R (BE-кандидат)"] += 1
        elif t["b_mfe"] >= 0.5:
            bucket["був +0,5…1R"] += 1
        else:
            bucket["майже одразу проти (<0,5R)"] += 1
    for k, v in sorted(bucket.items(), key=lambda kv: -kv[1]):
        P(f"  {k}: {v} ({100.0 * v / len(sls):.0f}%)")
    aft = [t for t in sls if "after_sl_tp1" in t]
    if aft:
        P(f"  після SL ціна пізніше (≤24 год) все ж дійшла до TP1: {sum(t['after_sl_tp1'] for t in aft)}/{len(aft)} — ознака збору ліквідності/стопу в шумі")
    P(f"  медіана часу до SL: {statistics.median(t['b_bars'] for t in sls):.0f} хв; медіана ризику {statistics.median(t['risk_pct'] for t in sls):.2f}% ціни; частка витрат у R на SL: {statistics.median((-t['R'] - 1.0) for t in sls):.2f}R")
    P(f"  TP1-відстань: медіана {statistics.median(t['tp1_r'] for t in trades):.2f}R; проковзання входу (мед.) {statistics.median(t['slip_r'] for t in trades):+.3f}R проти плану (додатне = гірше)")
    P("")
    # 4) контекст
    P("## 4. Контекст на момент сигналу (без майбутнього)")
    for key, lab in (("btc24_al", "напрям vs BTC 24h"), ("btc4_al", "напрям vs BTC 4h"), ("h4_trend_al", "vs H4-тренд монети (ціна>EMA20 H4)"), ("d1_trend_al", "vs D1-тренд монети (ціна>середнє 10 днів)"), ("btc_h4_trend_al", "vs H4-тренд BTC")):
        for val in ("with", "against"):
            P(summ([t for t in trades if t.get("ctx", {}).get(key) == val], "R", f"{lab}: {val}"))
    P("")
    for key, lab in (("btc24_al", "BTC24h"), ("h4_trend_al", "H4")):
        for d in ("LONG", "SHORT"):
            for val in ("with", "against"):
                P(summ([t for t in trades if t["dir"] == d and t.get("ctx", {}).get(key) == val], "R", f"{d} / {lab} {val}"))
    P("")
    # 5) варіанти
    P("## 5. Контрфактуальні варіанти на тих самих угодах (shadow, НЕ факт)")
    names = ["BE@1R", "BE@0.5R", "50%TP1+BE→TP2", "SL×1.5", "SL×2", "дзеркало", "затримка 1хв", "затримка 3хв", "затримка 5хв", "затримка 15хв"]
    P(summ([{"R": t["R"], "out": t["out"], "cl": t["cl"]} for t in trades], "R", "база (SL/TP1)"))
    for nme in names:
        P(summ([{"R": t["v_" + nme], "out": t.get("o_" + nme, "X"), "cl": t["cl"]} for t in trades if "v_" + nme in t], "R", nme))
    P("")
    # 6) сесії (UTC, гіпотеза меж)
    def sess(ts):
        h = datetime.fromtimestamp(ts, timezone.utc).hour
        return "ASIA 00–07" if h < 7 else ("LONDON 07–12" if h < 12 else ("NY 12–21" if h < 21 else "OFF 21–24"))
    P("## 6. Сесії (UTC; межі — ГІПОТЕЗА, як у replay)")
    for s_ in ("ASIA 00–07", "LONDON 07–12", "NY 12–21", "OFF 21–24"):
        P(summ([t for t in trades if sess(t["ts"]) == s_], "R", s_))
    P("")
    # 7) по угодах
    P("## 7. Угоди (скорочено)")
    P("час UTC | символ напр | kind/scope | paper→replay | R | MFE/MAE | ризик% | TP1,R | BTC24h% / coin24h% | H4/D1/BTC-H4 vs напрям | після SL→TP1")
    for t in sorted(trades, key=lambda x: x["ts"]):
        c = t.get("ctx", {})
        P(f"{datetime.fromtimestamp(t['ts'], timezone.utc):%d.%m %H:%M} | {t['sym']} {t['dir']} | {t['kind']}/{t['scope']} | {t['paper_out']}→{t['b_out']} | {t['R']:+.2f} | {t['b_mfe']:.2f}/{t['b_mae']:.2f} | {t['risk_pct']:.2f} | {t['tp1_r']:.2f} | "
          f"{c.get('btc_24h', float('nan')):+.2f}/{c.get('coin_24h', float('nan')):+.2f} | {c.get('h4_trend_al', '-')}/{c.get('d1_trend_al', '-')}/{c.get('btc_h4_trend_al', '-')} | {t.get('after_sl_tp1', '-')}")
    text = "\n".join(L)
    print(text)
    Path(out_json).write_text(json.dumps({"trades": trades, "report": text, "coverage": {k: v for k, v in cover.items()}}, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "quality_study.json")

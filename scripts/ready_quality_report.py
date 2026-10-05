#!/usr/bin/env python3
"""Якість READY: що систематично відрізняє TP1-first від SL-first. Вхід: датасет планів з БД + результати строгого пересчету (ready_replay_strict.py).
Лише опис: жодних нових правил/порогів. Кожна ознака показується з N, часткою, 95% інтервалом Вілсона і окремо для 1-ї та 2-ї половини періоду (train/test) —
ознака, що поводиться по-різному в половинах, нестабільна. Немає даних = не перевірено (NO_DATA рахуємо окремо, не як програш/виграш).

Використання: python scripts/ready_quality_report.py --plans data/research/ready_plans_2026-10-01_04.json --results /tmp/ready_strict.json [--md out.md]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# Ручний список назв, схожих на акції/ETF/сировину (за тікером; НЕ доведений, лише для зрізу «крипто/не-крипто»)
TRADFI = {"MSTR", "NVDA", "SPCX", "META", "COIN", "TSLA", "RKLB", "BABA", "CRCL", "AAOI", "AXTI", "HOOD", "QCOM", "BMNR", "MUU", "XAU", "NATGAS", "NBIS", "AAPL", "ORCL", "ARM", "DELL",
          "INTW", "TSM", "SQQQ", "SOXS", "SOXL", "IBM", "NOK", "INTC", "MRNA", "OPENAI", "ACN", "SKHY", "SAMSUNG", "AMZN", "HIMS", "CXMT", "CHIP", "MEGA", "ZHONGJI", "NIKE"}


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def f(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def quart(vals: List[float]) -> List[float]:
    s = sorted(vals)
    if not s:
        return []
    return [s[int(len(s) * q)] for q in (0.25, 0.5, 0.75)]


def bucketer(edges: List[float], labels: List[str]) -> Callable[[Optional[float]], str]:
    def b(x: Optional[float]) -> str:
        if x is None:
            return "н/д"
        for e, lab in zip(edges, labels):
            if x < e:
                return lab
        return labels[-1]
    return b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", required=True)
    ap.add_argument("--results", required=True)
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    plans = {p["mid"]: p for p in json.load(open(a.plans))}
    data = json.load(open(a.results))
    res = {r["mid"]: r for r in data["results"]}
    L: List[str] = []
    P = L.append
    P("# Якість READY: строгий пересчет по 1m-свічках (Binance USDT-M архів)\n")
    P(f"Плани: {len(plans)}; символів: {data.get('symbols')}; згенеровано {data.get('generated')} UTC.\n")
    cls = Counter()
    rows: List[Dict[str, Any]] = []
    for mid, p in plans.items():
        r = res.get(mid)
        if not r:
            cls["немає результату"] += 1
            continue
        ct = float(p["ct"])
        e, sl, tp1 = float(p["entry"]), float(p["sl"]), float(p["tp1"])
        risk = abs(e - sl) / e * 100.0
        tp1d = abs(tp1 - e) / e * 100.0
        long_ = p["direction"].upper() != "SHORT"
        sgn = 1.0 if long_ else -1.0
        st = r["status"]
        if st == "NO_DATA":
            k = "NO_DATA"
        elif st == "NOT_FILLED":
            k = "NOT_FILLED"
        elif r.get("first") == "TP1":
            k = "TP1_first"
        elif r.get("first") == "SL":
            k = "SL_first_tie" if r.get("tie") else "SL_first"
        elif r.get("entry_at"):
            k = "ACTIVE_no_TP1_no_SL"
        else:
            k = "PENDING_not_entered"
        cls[k] += 1
        hr = datetime.fromtimestamp(ct, tz=timezone.utc).hour
        rows.append({"mid": mid, "k": k, "ct": ct, "sym": p["symbol"].replace("USDT", ""), "dir": "LONG" if long_ else "SHORT", "risk": risk, "tp1d": tp1d, "rr1": tp1d / risk if risk else None,
                     "hr": hr, "sess": "Азія 00–08" if hr < 8 else "Лондон 08–13" if hr < 13 else "NY 13–21" if hr < 21 else "пізній 21–24",
                     "btc30": f(r.get("btc_30m")), "btc4h": f(r.get("btc_4h")), "c30": f(r.get("coin_30m")), "c4h": f(r.get("coin_4h")), "slatr": f(r.get("sl_atr15")),
                     "atrp": f(r.get("atr15_pct")), "sgn": sgn, "tradfi": p["symbol"].replace("USDT", "") in TRADFI, "tie": bool(r.get("tie")),
                     "ctx_align": p.get("ctx_align"), "ctx_bias": p.get("ctx_bias"), "tags": p.get("confirm_tags"), "expgap": f(p.get("th_exp_gap_min")), "th_age": f(p.get("th_age_min")), "sim": p.get("sim_outcome"), "sim_t": (ct + float(p["sim_ttr"])) if p.get("sim_ttr") not in (None, "") else None, "th_state": p.get("th_state"), "regime": p.get("regime"),
                     "nzsrc": len([x for x in str(p.get("zone_src") or "").split(",") if x.strip()]), "th_nver": f(p.get("th_nver")), "mfe": f(r.get("mfe")), "mae": f(r.get("mae")),
                     "ttr": (f(r.get("result_at")) - ct) if r.get("result_at") else None, "tp2": p.get("tp2") is not None,
                     "t_sl": f((r.get("at") or {}).get("SL")), "t_tp1": f((r.get("at") or {}).get("TP1")), "t_entry": f((r.get("at") or {}).get("ENTRY")), "data_end": f(r.get("data_end")), "status": st, "entry_f": e, "sl_f": sl, "tp1_f": tp1})
    P("## Класи (строгий пересчет)\n")
    P("| Клас | N |\n|---|---|")
    for k, v in sorted(cls.items(), key=lambda x: -x[1]):
        P(f"| {k} | {v} |")
    br = ba = bq = None
    sa: List[float] = []
    rr_: List[float] = []
    dec = [r for r in rows if r["k"] in ("TP1_first", "SL_first", "SL_first_tie")]
    n = len(dec)
    tp = sum(1 for r in dec if r["k"] == "TP1_first")
    lo, hi = wilson(tp, n)
    P(f"\n**Вирішені (TP1 або SL відбулось): {n}; TP1-first {tp} ({tp / n * 100:.1f}%, 95% ІВ {lo * 100:.1f}–{hi * 100:.1f}%); SL-first {n - tp}; з них «нічия в одну хвилину» (стоп за правилом lifecycle) {sum(1 for r in dec if r['k'] == 'SL_first_tie')}.**" if n else "\nНемає вирішених результатів — НЕ ПЕРЕВІРЕНО.")
    P("\n_Це частка TP1-first серед вирішених, а не офіційний WR: активні, невиконані й NO_DATA не входять. Стоп після TP1 тут рахується як TP1-first (як у lifecycle)._\n")
    if not n:
        out = "\n".join(L)
        print(out)
        return 1
    ts = sorted(r["ct"] for r in dec)
    mid_t = ts[len(ts) // 2]

    def table(title: str, key: Callable[[Dict[str, Any]], str]) -> None:
        P(f"\n### {title}\n")
        P("| Група | N | TP1-first | 95% ІВ | 1-ша половина | 2-га половина |\n|---|---|---|---|---|---|")
        g: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in dec:
            g[key(r)].append(r)
        for name in sorted(g):
            xs = g[name]
            k_ = sum(1 for r in xs if r["k"] == "TP1_first")
            l_, h_ = wilson(k_, len(xs))
            a1 = [r for r in xs if r["ct"] < mid_t]
            a2 = [r for r in xs if r["ct"] >= mid_t]

            def share(z: List[Dict[str, Any]]) -> str:
                return f"{sum(1 for r in z if r['k'] == 'TP1_first') / len(z) * 100:.0f}% (N={len(z)})" if z else "—"
            P(f"| {name} | {len(xs)} | {k_ / len(xs) * 100:.1f}% | {l_ * 100:.0f}–{h_ * 100:.0f}% | {share(a1)} | {share(a2)} |")

    table("Напрям", lambda r: r["dir"])
    table("Тип інструмента (ручний список тікерів, наближено)", lambda r: "акції/ETF/сировина" if r["tradfi"] else "крипто")
    table("Сесія UTC", lambda r: r["sess"])
    qr = quart([r["risk"] for r in dec])
    br = bucketer(qr, [f"ризик < {qr[0]:.2f}%", f"{qr[0]:.2f}–{qr[1]:.2f}%", f"{qr[1]:.2f}–{qr[2]:.2f}%", f"≥ {qr[2]:.2f}%"]) if qr else None
    if br:
        table("Відстань до стопу (%, квартилі вибірки)", lambda r: br(r["risk"]))
    sa = [r["slatr"] for r in dec if r["slatr"] is not None]
    if sa:
        qa = quart(sa)
        ba = bucketer(qa, [f"SL < {qa[0]:.2f} ATR15", f"{qa[0]:.2f}–{qa[1]:.2f}", f"{qa[1]:.2f}–{qa[2]:.2f}", f"≥ {qa[2]:.2f}"])
        table("Стоп у ATR(15m) (квартилі вибірки)", lambda r: ba(r["slatr"]))
    rr_ = [r["rr1"] for r in dec if r["rr1"]]
    if rr_:
        qq = quart(rr_)
        bq = bucketer(qq, [f"TP1/ризик < {qq[0]:.1f}", f"{qq[0]:.1f}–{qq[1]:.1f}", f"{qq[1]:.1f}–{qq[2]:.1f}", f"≥ {qq[2]:.1f}"])
        table("Відстань до TP1 / відстань до стопу (квартилі)", lambda r: bq(r["rr1"]))
    table("BTC за 30 хв до READY відносно напряму (за/проти)", lambda r: "н/д" if r["btc30"] is None else ("за напрямом" if r["btc30"] * r["sgn"] > 0.05 else "проти напряму" if r["btc30"] * r["sgn"] < -0.05 else "нейтрально ±0,05%"))
    table("BTC за 4 год до READY відносно напряму", lambda r: "н/д" if r["btc4h"] is None else ("за напрямом" if r["btc4h"] * r["sgn"] > 0.3 else "проти напряму" if r["btc4h"] * r["sgn"] < -0.3 else "нейтрально ±0,3%"))

    def thesis_fresh(r: Dict[str, Any]) -> str:
        if r["expgap"] is None:
            return "н/д"
        return "прострочена (READY після expires_at)" if r["expgap"] > 0 else "свіжа"

    def chase(r: Dict[str, Any]) -> str:
        if r["c30"] is None or not r["atrp"]:
            return "н/д"
        m = r["c30"] * r["sgn"] / r["atrp"]   # рух монети за 30 хв У БІК угоди в одиницях ATR15 %
        return "вже рушила у бік угоди ≥1 ATR15 за 30 хв" if m >= 1 else "рух у бік угоди 0–1 ATR15" if m >= 0 else "30 хв проти угоди (відкат)"
    table("Перед READY: рух монети за 30 хв відносно ATR15", chase)
    cnt = Counter(round(r["ct"] / 60) for r in rows)
    table("Пачка READY (скільки планів видано в ту ж хвилину)", lambda r: "1" if cnt[round(r["ct"] / 60)] == 1 else "2–3" if cnt[round(r["ct"] / 60)] <= 3 else "4+")
    last: Dict[str, float] = {}
    rep: Dict[str, bool] = {}
    for r in sorted(rows, key=lambda x: x["ct"]):
        key = r["sym"] + r["dir"]
        rep[r["mid"]] = key in last and r["ct"] - last[key] < 86400
        last[key] = r["ct"]
    table("Повтор: той самий символ і напрям вже були видані за останні 24 год", lambda r: "повтор" if rep.get(r["mid"]) else "перший")
    table("Є TP2", lambda r: "є" if r["tp2"] else "немає")
    table("Теза на момент READY: свіжа / прострочена", thesis_fresh)
    table("Стан тези", lambda r: str(r["th_state"] or "н/д"))
    table("Режим (thesis)", lambda r: str(r["regime"] or "н/д"))
    table("Скільки джерел зони (zone_src)", lambda r: "н/д" if r["nzsrc"] == 0 else "1" if r["nzsrc"] == 1 else "2" if r["nzsrc"] == 2 else "3+")
    # час до результату
    for k in ("TP1_first", "SL_first"):
        v = sorted(r["ttr"] for r in dec if (r["k"] == k or (k == "SL_first" and r["k"] == "SL_first_tie")) and r["ttr"])
        if v:
            P(f"\nЧас від READY до результату ({k}): p25 {v[len(v) // 4] / 60:.0f} хв, p50 {v[len(v) // 2] / 60:.0f} хв, p75 {v[3 * len(v) // 4] / 60:.0f} хв (N={len(v)}).")
    mf = sorted(r["mfe"] for r in dec if r["k"] != "TP1_first" and r["mfe"] is not None)
    if mf:
        P(f"\nSL-first: MFE до стопу p50 {mf[len(mf) // 2]:.2f}% (скільки ціна встигла піти в бік угоди перед стопом).")
    # ФІКСОВАНИЙ ГОРИЗОНТ без цензурування: знаменник = усі плани з даними до ct+H (активні без TP1/SL лишаються в знаменнику як «нічого»)
    def hz_class(r: Dict[str, Any], H: float) -> Optional[str]:
        if r["status"] == "NO_DATA" or r["data_end"] is None or r["data_end"] < r["ct"] + H:
            return None
        ev = []
        if r["t_sl"] is not None and r["t_sl"] <= r["ct"] + H:
            ev.append((r["t_sl"], "SL"))
        if r["t_tp1"] is not None and r["t_tp1"] <= r["ct"] + H:
            ev.append((r["t_tp1"], "TP1"))
        if not ev:
            return "нічого за горизонт"
        ev.sort()
        return "TP1 першим" if ev[0][1] == "TP1" else "SL першим"

    for H_h in (3, 6, 12, 24):
        H = H_h * 3600.0
        el = [(r, hz_class(r, H)) for r in rows]
        el = [(r, c) for r, c in el if c]
        n_ = len(el)
        if not n_:
            P(f"\n### Горизонт {H_h} год: немає планів з повними даними — НЕ ПЕРЕВІРЕНО\n")
            continue
        cn = Counter(c for _r, c in el)
        P(f"\n## Фіксований горизонт {H_h} год (плани з даними до ct+{H_h}h: N={n_})\n")
        P("| Клас | N | частка | 95% ІВ |\n|---|---|---|---|")
        for c in ("TP1 першим", "SL першим", "нічого за горизонт"):
            l_, h_ = wilson(cn.get(c, 0), n_)
            P(f"| {c} | {cn.get(c, 0)} | {cn.get(c, 0) / n_ * 100:.1f}% | {l_ * 100:.0f}–{h_ * 100:.0f}% |")

        def hz_table(title: str, key: Callable[[Dict[str, Any]], str], _el=el, _H=H_h) -> None:
            P(f"\n#### {title} (горизонт {_H} год)\n")
            P("| Група | N | TP1 першим | SL першим | нічого | 1-ша пол. TP1/SL | 2-га пол. TP1/SL |\n|---|---|---|---|---|---|---|")
            g2: Dict[str, List[Tuple[Dict[str, Any], str]]] = defaultdict(list)
            for r_, c_ in _el:
                g2[key(r_)].append((r_, c_))
            tmid = sorted(r_["ct"] for r_, _ in _el)[len(_el) // 2]
            for name in sorted(g2):
                xs = g2[name]
                nn = len(xs)
                t1 = sum(1 for _, c_ in xs if c_ == "TP1 першим")
                sl_ = sum(1 for _, c_ in xs if c_ == "SL першим")
                a1 = [c_ for r_, c_ in xs if r_["ct"] < tmid]
                a2 = [c_ for r_, c_ in xs if r_["ct"] >= tmid]

                def hs(z: List[str]) -> str:
                    return f"{sum(1 for c_ in z if c_ == 'TP1 першим')}/{sum(1 for c_ in z if c_ == 'SL першим')} (N={len(z)})" if z else "—"
                P(f"| {name} | {nn} | {t1 / nn * 100:.0f}% | {sl_ / nn * 100:.0f}% | {(nn - t1 - sl_) / nn * 100:.0f}% | {hs(a1)} | {hs(a2)} |")

        if H_h in (6, 24):
            hz_table("Напрям", lambda r: r["dir"])
            if br:
                hz_table("Відстань до стопу (%)", lambda r: br(r["risk"]))
            if sa:
                hz_table("Стоп у ATR(15m)", lambda r: ba(r["slatr"]))
            if rr_:
                hz_table("TP1 / стоп", lambda r: bq(r["rr1"]))
            hz_table("BTC за 4 год до READY відносно напряму", lambda r: "н/д" if r["btc4h"] is None else ("за напрямом" if r["btc4h"] * r["sgn"] > 0.3 else "проти напряму" if r["btc4h"] * r["sgn"] < -0.3 else "нейтрально ±0,3%"))
            hz_table("Сесія UTC", lambda r: r["sess"])
            hz_table("Теза: свіжа / прострочена", thesis_fresh)
            hz_table("Режим (thesis)", lambda r: str(r["regime"] or "н/д"))
            hz_table("Скільки джерел зони", lambda r: "н/д" if r["nzsrc"] == 0 else "1" if r["nzsrc"] == 1 else "2" if r["nzsrc"] == 2 else "3+")
            hz_table("Тип інструмента", lambda r: "акції/ETF/сировина" if r["tradfi"] else "крипто")

    # ГОЛОВНА МЕТРИКА: надлишок над геометричною базою = факт TP1-first − середнє r/(r+t); ІВ — кластерний бутстреп за symbol+direction (READY не незалежні)
    import random

    H24e = 24 * 3600.0
    res24 = []
    for r in rows:
        c = hz_class(r, H24e)
        if c in ("TP1 першим", "SL першим"):
            d_ = abs(r["entry_f"] - r["sl_f"])
            t_ = abs(r["tp1_f"] - r["entry_f"])
            res24.append((r, 1.0 if c == "TP1 першим" else 0.0, d_ / (d_ + t_) if (d_ + t_) else 0.0))

    def excess(xs: List[Tuple[Dict[str, Any], float, float]]) -> Tuple[float, float, float]:
        n_ = len(xs)
        a_ = sum(x[1] for x in xs) / n_
        b_ = sum(x[2] for x in xs) / n_
        return a_, b_, a_ - b_

    def cluster_ci(xs: List[Tuple[Dict[str, Any], float, float]], B: int = 300) -> Tuple[float, float]:
        cl: Dict[str, List[Tuple[Dict[str, Any], float, float]]] = defaultdict(list)
        for x in xs:
            cl[x[0]["sym"] + x[0]["dir"]].append(x)
        keys = list(cl)
        if len(keys) < 5:
            return float("nan"), float("nan")
        rnd = random.Random(7)
        vals = []
        for _ in range(B):
            samp = [x for k in (rnd.choice(keys) for _ in keys) for x in cl[k]]
            vals.append(excess(samp)[2])
        vals.sort()
        return vals[int(B * 0.025)], vals[int(B * 0.975)]

    P("\n## Надлишок над геометричною базою (строгий 1m, горизонт 24 год; кластерний бутстреп за symbol+direction)\n")
    if len(res24) < 30:
        P("Недостатньо вирішених планів — НЕ ПЕРЕВІРЕНО.\n")
    else:
        nclu = len({x[0]["sym"] + x[0]["dir"] for x in res24})
        a_, b_, e_ = excess(res24)
        lo_, hi_ = cluster_ci(res24)
        P(f"Вирішених планів: {len(res24)}, кластерів symbol+direction: {nclu} (ефективна вибірка ближча до числа кластерів, ніж до числа планів). "
          f"Факт TP1-first {a_ * 100:.1f}%, база {b_ * 100:.1f}%, надлишок {e_ * 100:+.1f} п.п. (кластерний 95% ІВ {lo_ * 100:+.1f}…{hi_ * 100:+.1f}).\n")
        tmid = sorted(x[0]["ct"] for x in res24)[len(res24) // 2]

        def ex_table(title: str, key: Callable[[Dict[str, Any]], str], by_dir: bool = False) -> None:
            P(f"\n### {title}\n")
            P("| Група | N | факт | база | надлишок (кластер. ІВ) | 1-ша пол. | 2-га пол. |" + (" LONG надл. (N) | SHORT надл. (N) |" if by_dir else "") + "\n|---|---|---|---|---|---|---|" + ("---|---|" if by_dir else ""))
            g: Dict[str, List[Tuple[Dict[str, Any], float, float]]] = defaultdict(list)
            for x in res24:
                g[key(x[0])].append(x)
            for name in sorted(g):
                xs = g[name]
                if len(xs) < 10:
                    P(f"| {name} | {len(xs)} | замало (<10) | | | | |" + (" | |" if by_dir else ""))
                    continue
                a2, b2, e2 = excess(xs)
                l2, h2 = cluster_ci(xs)
                h1 = [x for x in xs if x[0]["ct"] < tmid]
                h2s = [x for x in xs if x[0]["ct"] >= tmid]
                f1 = f"{excess(h1)[2] * 100:+.1f} (N={len(h1)})" if len(h1) >= 10 else "—"
                f2 = f"{excess(h2s)[2] * 100:+.1f} (N={len(h2s)})" if len(h2s) >= 10 else "—"
                ci = "—" if l2 != l2 else f"{l2 * 100:+.1f}…{h2 * 100:+.1f}"
                line = f"| {name} | {len(xs)} | {a2 * 100:.1f}% | {b2 * 100:.1f}% | {e2 * 100:+.1f} ({ci}) | {f1} | {f2} |"
                if by_dir:
                    for dn in ("LONG", "SHORT"):
                        ds = [x for x in xs if x[0]["dir"] == dn]
                        line += f" {excess(ds)[2] * 100:+.1f} (N={len(ds)}) |" if len(ds) >= 10 else " — |"
                P(line)

        ex_table("Напрям", lambda r: r["dir"])
        ex_table("BTC за 4 год до READY відносно напряму", lambda r: "н/д" if r["btc4h"] is None else ("за напрямом" if r["btc4h"] * r["sgn"] > 0.3 else "проти напряму" if r["btc4h"] * r["sgn"] < -0.3 else "нейтрально"), by_dir=True)
        ex_table("BTC за 30 хв до READY відносно напряму", lambda r: "н/д" if r["btc30"] is None else ("за напрямом" if r["btc30"] * r["sgn"] > 0.05 else "проти напряму" if r["btc30"] * r["sgn"] < -0.05 else "нейтрально"), by_dir=True)
        ex_table("Сесія UTC", lambda r: r["sess"], by_dir=True)
        ex_table("Джерел зони (zone_src)", lambda r: "н/д" if r["nzsrc"] == 0 else "1" if r["nzsrc"] == 1 else "2" if r["nzsrc"] == 2 else "3+", by_dir=True)
        ex_table("Режим (thesis)", lambda r: str(r["regime"] or "н/д"), by_dir=True)
        ex_table("Стан тези", lambda r: str(r["th_state"] or "н/д"))
        ex_table("Теза: свіжа / прострочена", thesis_fresh, by_dir=True)
        ex_table("Вік тези на момент READY (хв)", lambda r: "н/д" if r["th_age"] is None else "<60" if r["th_age"] < 60 else "60–240" if r["th_age"] < 240 else "240–720" if r["th_age"] < 720 else "≥720")
        ex_table("Рух монети за 30 хв до READY (в ATR15, у бік угоди)", chase, by_dir=True)
        ex_table("Стоп у ATR15", lambda r: "н/д" if r["slatr"] is None else "<1,5" if r["slatr"] < 1.5 else "1,5–2,5" if r["slatr"] < 2.5 else "2,5–4" if r["slatr"] < 4 else "≥4", by_dir=True)
        ex_table("Стоп %", lambda r: "<0,7" if r["risk"] < 0.7 else "0,7–1,2" if r["risk"] < 1.2 else "1,2–2" if r["risk"] < 2 else "2–3" if r["risk"] < 3 else "≥3", by_dir=True)
        ex_table("TP1% (відстань до цілі)", lambda r: "<3,5" if r["tp1d"] < 3.5 else "3,5–5" if r["tp1d"] < 5 else "5–8" if r["tp1d"] < 8 else "≥8")
        ex_table("RR до TP1", lambda r: "н/д" if not r["rr1"] else "≤1,5" if r["rr1"] <= 1.5 else "1,5–3" if r["rr1"] <= 3 else "3–5" if r["rr1"] <= 5 else "5–10" if r["rr1"] <= 10 else ">10")
        ex_table("Повтор тієї ж пари за 24 год", lambda r: "повтор" if rep.get(r["mid"]) else "перша")
        ex_table("Розмір пачки (READY за ту ж хвилину)", lambda r: "1" if cnt[round(r["ct"] / 60)] == 1 else "2–3" if cnt[round(r["ct"] / 60)] <= 3 else "4+")
        ex_table("Тип інструмента", lambda r: "акції/ETF/сировина" if r["tradfi"] else "крипто")
        ex_table("ctx.alignment (лише плани з gate)", lambda r: str(r["ctx_align"] or "н/д"))

    # КОНТРОЛЬ СИМУЛЯТОРА: ті самі плани за строгим 1m і за офіційним 15m (SIGNAL_RESULT) — чи не створює різниця механіка 15m
    P("\n## Контроль симулятора: строгий 1m проти офіційного 15m на ТИХ САМИХ планах (горизонт 24 год)\n")
    H24 = 24 * 3600.0
    both = []
    for r in rows:
        c = hz_class(r, H24)
        if c is None or not r["sim"]:
            continue
        both.append((r, c))
    if not both:
        P("Немає планів з обома результатами — НЕ ПЕРЕВІРЕНО.\n")
    else:
        def off(r: Dict[str, Any]) -> str:
            if r["sim"] == "STOP":
                return "SL"
            if r["sim"] in ("TP1", "TP2", "TP3"):
                return "TP"
            return "інше"
        m: Dict[Tuple[str, str], int] = Counter()
        for r, c in both:
            m[(c, off(r))] += 1
        P(f"Планів з обома результатами: {len(both)}.\n")
        P("| 1m: що першим | офіційно SL | офіційно TP | офіційно інше (таймаут/не виконано/без результату) |\n|---|---|---|---|")
        for c in ("TP1 першим", "SL першим", "нічого за горизонт"):
            P(f"| {c} | {m[(c, 'SL')]} | {m[(c, 'TP')]} | {m[(c, 'інше')]} |")
        k1 = sum(1 for r, c in both if c == "TP1 першим")
        s1 = sum(1 for r, c in both if c == "SL першим")
        k2 = sum(1 for r, c in both if off(r) == "TP" and (r["sim_t"] or 1e18) <= r["ct"] + H24)
        s2 = sum(1 for r, c in both if off(r) == "SL" and (r["sim_t"] or 1e18) <= r["ct"] + H24)
        rw = sum(abs(float(r["entry_f"]) - float(r["sl_f"])) / (abs(float(r["entry_f"]) - float(r["sl_f"])) + abs(float(r["tp1_f"]) - float(r["entry_f"]))) for r, _ in both) / len(both) if all("entry_f" in r for r, _ in both) else None
        P(f"\nСтрогий 1m: TP1 {k1}, SL {s1} → {k1 / max(1, k1 + s1) * 100:.1f}% TP1-first. Офіційний 15m (ті самі плани): TP {k2}, SL {s2} → {k2 / max(1, k2 + s2) * 100:.1f}% TP-first."
          + (f" Геометрична база: {rw * 100:.1f}%." if rw is not None else ""))
        # де розходяться: 1m каже TP1 першим, офіційний — SL: той самий 15m-бар?
        same_bar = other = 0
        for r, c in both:
            if c == "TP1 першим" and off(r) == "SL" and r["t_tp1"] is not None and r["sim_t"] is not None:
                if abs(r["sim_t"] - r["t_tp1"]) <= 900:
                    same_bar += 1
                else:
                    other += 1
        P(f"\nПлани, де 1m = TP1 першим, а офіційний = SL: у межах 15 хв від TP1 (імовірно один 15m-бар: стоп за правилом «стоп раніше цілі») {same_bar}, пізніше/інакше {other}.")
        # вхід: різниця моменту входу
        ent_diff = [(r["t_entry"] - r["ct"]) / 60 for r, c in both if r["t_entry"] is not None]
        if ent_diff:
            ent_diff.sort()
            P(f"Момент входу за 1m після READY: p25 {ent_diff[len(ent_diff) // 4]:.0f} хв, p50 {ent_diff[len(ent_diff) // 2]:.0f} хв, p75 {ent_diff[3 * len(ent_diff) // 4]:.0f} хв (N={len(ent_diff)}).")
        pre = sum(1 for r, c in both if r["t_entry"] is None)
        P(f"Планів без входу за 1m: {pre} (не мають результату в строгому replay).\n")

    # gate-ознаки лише там, де вони збережені
    g = [r for r in dec if r["ctx_align"] or r["tags"]]
    P(f"\n### Ознаки gate (зберігаються лише для планів 4 жовтня): N={len(g)} — замало для висновків\n")
    if g:
        table_rows = defaultdict(lambda: [0, 0])
        for r in g:
            table_rows[str(r["ctx_align"])][1] += 1
            table_rows[str(r["ctx_align"])][0] += r["k"] == "TP1_first"
        P("| ctx.alignment | TP1-first | N |\n|---|---|---|")
        for k, (a_, b_) in sorted(table_rows.items()):
            P(f"| {k} | {a_} | {b_} |")
    out = "\n".join(L)
    print(out)
    if a.md:
        open(a.md, "w").write(out + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

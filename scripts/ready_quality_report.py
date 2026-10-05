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
                     "ctx_align": p.get("ctx_align"), "ctx_bias": p.get("ctx_bias"), "tags": p.get("confirm_tags"), "expgap": f(p.get("th_exp_gap_min")), "th_state": p.get("th_state"), "regime": p.get("regime"),
                     "nzsrc": len([x for x in str(p.get("zone_src") or "").split(",") if x.strip()]), "th_nver": f(p.get("th_nver")), "mfe": f(r.get("mfe")), "mae": f(r.get("mae")),
                     "ttr": (f(r.get("result_at")) - ct) if r.get("result_at") else None, "tp2": p.get("tp2") is not None,
                     "t_sl": f((r.get("at") or {}).get("SL")), "t_tp1": f((r.get("at") or {}).get("TP1")), "t_entry": f((r.get("at") or {}).get("ENTRY")), "data_end": f(r.get("data_end")), "status": st})
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

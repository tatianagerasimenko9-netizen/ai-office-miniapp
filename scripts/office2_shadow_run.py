#!/usr/bin/env python3
"""Office 2.0 shadow-replay на довгій історії архіву Binance (research-only; production не торкається).

python scripts/office2_shadow_run.py --d0 2026-08-01 --d1 2026-10-03 --cache /tmp/o2cache --md /tmp/office2.md [--symbols BTCUSDT,ETHUSDT,...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from office2 import data as D  # noqa: E402
from office2 import evaluate as E  # noqa: E402
from office2 import pipeline as P  # noqa: E402
from office2 import risk as R  # noqa: E402
from office2 import scenarios as SC  # noqa: E402

DEFAULT_SYMBOLS = ("BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT DOGEUSDT ADAUSDT AVAXUSDT LINKUSDT DOTUSDT LTCUSDT BCHUSDT TRXUSDT ATOMUSDT NEARUSDT APTUSDT ARBUSDT OPUSDT SUIUSDT INJUSDT "
                   "AAVEUSDT UNIUSDT ETCUSDT FILUSDT HBARUSDT ICPUSDT TIAUSDT SEIUSDT 1000PEPEUSDT 1000SHIBUSDT FETUSDT RUNEUSDT ALGOUSDT MKRUSDT LDOUSDT WLDUSDT ONDOUSDT JUPUSDT ENAUSDT TAOUSDT").split()


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--d0", required=True)
    ap.add_argument("--d1", required=True)
    ap.add_argument("--cache", default="/tmp/o2cache")
    ap.add_argument("--md", default="")
    ap.add_argument("--json", default="")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--k-buf", type=float, default=0.5)
    ap.add_argument("--open-test", action="store_true", help="сценарні таблиці з колонкою test (лише ПІСЛЯ фіксації гіпотез у HYPOTHESES.md)")
    ap.add_argument("--mode", choices=("explore", "final"), default="explore",
                    help="explore: hold-out символи НЕ завантажуються; final: ЛИШЕ hold-out символи, одна перевірка зафіксованої версії")
    a = ap.parse_args()
    all_syms = [s for s in (a.symbols.split(",") if a.symbols else DEFAULT_SYMBOLS) if s]
    syms = [s for s in all_syms if (E.is_holdout(s) == (a.mode == "final")) or s == "BTCUSDT"]   # BTC потрібен для S2 в обох режимах
    p = P.Params(k_buf=a.k_buf)
    d0, d1 = _dt(a.d0), _dt(a.d1)
    cache = Path(a.cache)
    t0 = time.time()
    btc_m1, miss = D.load_symbol("BTCUSDT", d0, d1, cache, a.offline)
    if btc_m1 is None:
        print("BTCUSDT: немає даних — зупинка (BTC потрібен для S2)")
        return 1
    btc_ctx = P.build_context(btc_m1)
    rows: List[dict] = []
    ctrl: List[dict] = []
    skipped: Dict[str, int] = {}
    stats: Dict[str, int] = {}
    mir: List[dict] = []
    sc_rows: List[dict] = []
    behav: List[dict] = []
    sc_stats: Dict[str, int] = {}
    for i, sym in enumerate(syms):
        m1, missing = (btc_m1, miss) if sym == "BTCUSDT" else D.load_symbol(sym, d0, d1, cache, a.offline)
        if m1 is None or len(m1["t"]) < 3 * 1440:
            skipped[sym] = len(missing)
            continue
        ctx = btc_ctx if sym == "BTCUSDT" else P.build_context(m1)
        c = P.candidates(sym, ctx, btc_ctx, p, stats)
        rows.extend(E.evaluate(c, {sym: ctx}, p))
        scr = SC.scenario_candidates(sym, ctx, btc_ctx, p, sc_stats)
        sc_rows.extend(E.evaluate(scr["cands"], {sym: ctx}, p))
        behav.extend(scr["behav"])
        mir.extend(E.evaluate([E.mirror(x) for x in c if x["trigger"] == "reclaim" and x["reg4"] * (1 if x["dir"] == "LONG" else -1) < 0], {sym: ctx}, p))
        ctrl.extend(E.evaluate(E.random_control({sym: ctx}, 40, p), {sym: ctx}, p))
        print(f"[{i + 1}/{len(syms)}] {sym}: бар 1m {len(m1['t'])}, кандидатів {len(c)}, пропущених днів {len(missing)}, {time.time() - t0:.0f} с", flush=True)
    L: List[str] = [f"# Baseline Office 2.0 v0 — shadow-replay ({a.mode}): {a.d0} … {a.d1} UTC", "",
                    "> **Baseline v0, не фінальна реалізація.** H4/D1, BTC 4 год, sweep+reclaim, CHoCH, taker-дельта, буфер 0,5·ATR15, RR ≥1,5, поріг BTC ±0,3% — дослідницькі гіпотези, а не затверджені правила. "
                    "Слабкий результат v0 не означає, що Office 2.0 «не працює»: OI, funding, ліквідації, DOM, GEX, дивергенції, Pattern Engine, session H/L, PMH/PML, structural reset, прив'язка до тези ще не реалізовані.",
                    f"> Режим **{a.mode}**: " + ("hold-out символи НЕ використовуються (train/test за часом на решті символів)." if a.mode == "explore" else "лише hold-out символи, зафіксована версія, одноразова перевірка."), "",
                    f"Символів із даними: {len({r['symbol'] for r in rows})} (пропущено: {len(skipped)}); кандидатів із повним горизонтом 24 год: {len(rows)}; сіднійний контроль: {len(ctrl)}.",
                    f"Параметри (задані заздалегідь, не підбиралися): K_BUF={p.k_buf}·ATR15, MIN_RR={p.min_rr}, max TP {p.max_tp_r}R, CHoCH ≤{p.choch_bars} барів. Комісія кола 0,10% (R чистий = R − 0,10%/ризик%).",
                    "Метрика: **надлишок = факт TP-first − геометрична база r/(r+t)** (кластерний бутстреп за symbol+день). Train = перші 60% діб, test = решта, test×hold-out = test на ≈1/3 символів, не використаних у дизайні.", ""]
    base_rows = [r for r in rows if r["trigger"] == "reclaim"]
    full = [r for r in base_rows if r["htf_ok"] and r["btc_ok"] and r["flow_ok"]]
    pf_full = R.simulate_portfolio([dict(x, lvl_key=(x["symbol"], x["dir"], round(x["lvl_p"], 6))) for x in full]) if full else None
    sp = E.split(full) if full else {"train": [], "test": []}
    L.append("### Воронка (тригер reclaim): де відсіюються сценарії\n")
    L.append("| Крок | Кількість |\n|---|---|")
    for k, lab in (("events", "sweep+reclaim подій на M15 (етапи 3–5)"), ("no_atr", "  відсіяно: немає ATR"), ("reclaim_no_entry_bar", "  відсіяно: немає 1m-бару входу"),
                   ("reclaim_risk_out_of_range", "  відсіяно: ризик поза 0,15–6%"), ("reclaim_no_target", "  відсіяно: немає цілі з RR ≥1,5"), ("reclaim_target_too_far", "  відсіяно: ціль далі 8R"),
                   ("reclaim_candidate", "КАНДИДАТІВ (структурний SL + ціль-ліквідність)")):
        L.append(f"| {lab} | {stats.get(k, 0)} |")
    L.append(f"| …із них з повним горизонтом 24 год (оцінено) | {len(base_rows)} |")
    for lab, f in (("  пройшли S1 HTF", lambda r: r["htf_ok"]), ("  …і S2 BTC", lambda r: r["htf_ok"] and r["btc_ok"]), ("  …і S7 потік (= READY2 v0 до Risk Manager)", lambda r: r["htf_ok"] and r["btc_ok"] and r["flow_ok"])):
        L.append(f"| {lab} | {sum(1 for r in base_rows if f(r))} |")
    L.append(f"| READY2 v0 після Risk Manager | {len(pf_full['accepted']) if pf_full else 0} |")
    L.append(f"| CHoCH-тригер: знайдено / не знайдено за ≤8 барів | {stats.get('choch_trigger', 0)} / {stats.get('choch_absent', 0)} |")
    L.append("")
    L.append("### Підсумок READY2 v0 (простими цифрами; train/test за часом)\n")
    L.append("| Набір | READY2 | TP1-first | SL-first | таймаут | база r/(r+t) | надлишок п.п. | середній R після комісій |\n|---|---|---|---|---|---|---|---|")
    for lab, rr in (("усі (train+test)", full), ("train", sp["train"]), ("test", sp["test"])):
        if not rr:
            L.append(f"| {lab} | 0 | — | — | — | — | — | — |")
            continue
        sm = E.summarize(rr)
        tp = sum(1 for r in rr if r["outcome"] == "TP")
        sl = sum(1 for r in rr if r["outcome"] == "SL")
        L.append(f"| {lab} | {len(rr)} | {tp} | {sl} | {len(rr) - tp - sl} | {E.fmt(sm['base'])}% | {E.fmt(sm['excess'], signed=True)} | {sm['mean_r']:+.3f} |")
    L.append("")
    L += E.table("Сіднійний контроль (випадковий вхід, SL 2·ATR15, TP 3·ATR15): очікуваний надлишок ≈ 0", [("випадкові входи", ctrl)])
    L += E.table("Абляція етапів Office 2.0 (кожен етап має довести надлишок, не лише існувати)", E.ablation(rows))
    # преддекларовані гіпотези (docs/office2/HYPOTHESES.md, зафіксовані до перегляду test): одна оцінка, train і test поруч
    sg = lambda r: 1 if r["dir"] == "LONG" else -1
    L += E.table("Преддекларовані гіпотези H1–H3 (HYPOTHESES.md; вердикт незалежно від знаку)", [
        ("H1: фейд sweep лише ПО тренду H4", [r for r in base_rows if r["reg4"] * sg(r) > 0]),
        ("H1b: H1 + BTC не проти", [r for r in base_rows if r["reg4"] * sg(r) > 0 and r["btc_ok"]]),
        ("H2 (data-mined): глибина sweep 0,3–1 ATR15", [r for r in base_rows if 0.3 <= r["depth_atr"] < 1.0]),
        ("H3: дзеркальна угода (в напрямку пробою) проти тренду H4", mir)])
    # діагностика ЛИШЕ на train (щоб зрозуміти механіку; не для вибору параметрів/порогів; test не використовується)
    trn = E.split(base_rows)["train"]
    L.append("\n### Діагностика на TRAIN (базові кандидати; механіка, не вибір правил)\n")
    L.append("| Зріз | Група | N | факт | база | надлишок п.п. (кластерний 95% ІВ) |\n|---|---|---|---|---|---|")
    def dg(title: str, key) -> None:
        g: Dict[str, List[dict]] = {}
        for r in trn:
            g.setdefault(str(key(r)), []).append(r)
        for name in sorted(g):
            rr = g[name]
            if len(rr) < 40:
                continue
            sm = E.summarize(rr)
            ci = "—" if sm["lo"] != sm["lo"] else f"{E.fmt(sm['lo'], signed=True)}…{E.fmt(sm['hi'], signed=True)}"
            L.append(f"| {title} | {name} | {sm['n_res']} | {E.fmt(sm['hit'])}% | {E.fmt(sm['base'])}% | {E.fmt(sm['excess'], signed=True)} ({ci}) |")
    dg("напрям", lambda r: r["dir"])
    dg("тип рівня", lambda r: r["lvl_kind"])
    dg("H4 режим відносно угоди", lambda r: "за трендом" if r["reg4"] * (1 if r["dir"] == "LONG" else -1) > 0 else "проти тренду" if r["reg4"] * (1 if r["dir"] == "LONG" else -1) < 0 else "діапазон")
    dg("глибина sweep, ATR15", lambda r: "<0,3" if r["depth_atr"] < 0.3 else "0,3–1" if r["depth_atr"] < 1 else "≥1")
    dg("ризик, %", lambda r: "<0,5" if r["risk_pct"] < 0.5 else "0,5–1" if r["risk_pct"] < 1 else "1–2" if r["risk_pct"] < 2 else "≥2")
    dg("RR до цілі", lambda r: "1,5–2,5" if r["rr"] < 2.5 else "2,5–4" if r["rr"] < 4 else "≥4")
    dg("година UTC", lambda r: "Азія 0–8" if int(r["t_entry"] % 86400 // 3600) < 8 else "Лондон 8–13" if int(r["t_entry"] % 86400 // 3600) < 13 else "NY 13–21" if int(r["t_entry"] % 86400 // 3600) < 21 else "пізня 21–24")
    # ===== СЦЕНАРНИЙ ШАР: що зробила ціна після зняття ліквідності (TRAIN; test лише з --open-test) =====
    cut = E.cut_day(rows + sc_rows)
    tr_only = not a.open_test
    L.append("\n## Сценарний шар: Office спершу визначає, що сталося з ціною, а вже потім вибирає вхід\n")
    L.append(f"> {'TRAIN-ONLY: test не відкривається, гіпотези ще не заморожені.' if tr_only else 'Test відкритий для зафіксованих гіпотез (HYPOTHESES.md).'} Метрика, яку показуємо завжди: **середній R після комісій** (математичне сподівання угоди), а не лише TP1-first.\n")
    L.append(f"Проколів рівнів: {sc_stats.get('pierces', 0)}; прийняттів (2 закриття за рівнем): {sc_stats.get('accept_events', 0)}; кандидатів CONT: {sc_stats.get('accept_candidate', 0)}, RETEST: {sc_stats.get('retest_candidate', 0)}.\n")
    # 1) поведінка після проколу: дрейф у бік пробою
    bt = [b for b in behav if b["day"] < cut] if tr_only and cut is not None else behav
    L.append("### Поведінка ціни після проколу рівня (TRAIN): куди пішла ціна після рішення, у ATR15 у БІК пробою (>0 = продовження, <0 = розворот)\n")
    L.append("| Поведінка | H4 відносно пробою | N | частка | середній рух +1 год | +4 год (95% ІВ) | частка >0 за 4 год |\n|---|---|---|---|---|---|---|")
    import random as _rnd

    def boot_mean(vals: List[tuple]) -> tuple:
        cl: Dict[tuple, List[float]] = {}
        for k, v in vals:
            cl.setdefault(k, []).append(v)
        keys = list(cl)
        if len(keys) < 8:
            return float("nan"), float("nan")
        rr = _rnd.Random(3)
        ms = []
        for _ in range(300):
            samp = [x for k in (rr.choice(keys) for _ in keys) for x in cl[k]]
            ms.append(sum(samp) / len(samp))
        ms.sort()
        return ms[7], ms[292]

    tot = len(bt)
    for beh in ("A", "B1", "ACCEPT", "TRAP"):
        for rel in ("за трендом пробою", "проти тренду пробою", "діапазон"):
            g = [b for b in bt if b["behavior"] == beh and b["rel"] == rel]
            if len(g) < 40:
                continue
            f1 = [b["fwd1h_atr"] for b in g if b["fwd1h_atr"] is not None]
            f4 = [((b["symbol"], b["day"]), b["fwd4h_atr"]) for b in g if b["fwd4h_atr"] is not None]
            lo, hi = boot_mean(f4)
            m4 = sum(v for _, v in f4) / len(f4)
            L.append(f"| {beh} | {rel} | {len(g)} | {len(g) / max(1, tot) * 100:.0f}% | {sum(f1) / len(f1):+.2f} | {m4:+.2f} ({lo:+.2f}…{hi:+.2f}) | {sum(1 for _, v in f4 if v > 0) / len(f4) * 100:.0f}% |")
    L.append("\nA = wick-reclaim; B1 = reclaim після 1 закриття за рівнем; ACCEPT = 2 закриття за рівнем; TRAP = прийняття з поверненням на 3-му барі (знаємо лише постфактум, у рішенні не використовується).\n")
    # 2) сценарії
    sg = lambda r: 1 if r["dir"] == "LONG" else -1
    allc = rows + sc_rows
    scen_groups = [
        ("REVERSAL: reclaim + CHoCH (підтверджена зміна структури)", [r for r in rows if r["trigger"] == "choch"]),
        ("RANGE: reclaim на краю діапазону H4 (reg4 = 0)", [r for r in rows if r["trigger"] == "reclaim" and r["reg4"] == 0]),
        ("REVERSAL без підтвердження, ПО тренду H4 (інформаційно)", [r for r in rows if r["trigger"] == "reclaim" and r["reg4"] * sg(r) > 0]),
        ("REVERSAL без підтвердження, ПРОТИ тренду H4 (інформаційно)", [r for r in rows if r["trigger"] == "reclaim" and r["reg4"] * sg(r) < 0]),
        ("CONTINUATION: прийняття за рівнем у бік тренду H4", [r for r in sc_rows if r["trigger"] == "accept" and r["reg4"] * sg(r) > 0]),
        ("ПРИЙНЯТТЯ без підтримки HTF (проти тренду / діапазон) — інформаційно", [r for r in sc_rows if r["trigger"] == "accept" and r["reg4"] * sg(r) <= 0]),
        ("BREAKOUT+RETEST: прийняття → ретест рівня → вхід у бік пробою", [r for r in sc_rows if r["trigger"] == "retest"]),
        ("  …з них у бік тренду H4", [r for r in sc_rows if r["trigger"] == "retest" and r["reg4"] * sg(r) > 0]),
    ]
    L += E.table("Сценарії (Office спершу визначає ситуацію): N → TP1-first → SL-first → таймаут → база → надлишок → середній R після комісій", scen_groups, train_only=tr_only, cut_day=cut)
    L.append("\nNO TRADE: події, що не склалися в жоден сценарій (немає цілі RR ≥1,5, ризик поза межами, або поведінка не з переліку); у воронці — окремі лічильники.\n")
    # 3) розрізи по сценаріях
    def rel_h4(r: dict) -> str:
        v = r["reg4"] * sg(r)
        return "за трендом H4" if v > 0 else "проти тренду H4" if v < 0 else "діапазон H4"

    def rel_btc(r: dict) -> str:
        if r["btc4"] is None:
            return "н/д"
        v = r["btc4"] * sg(r)
        return "BTC за" if v > 0.3 else "BTC проти" if v < -0.3 else "BTC нейтрально"

    for name, g in scen_groups[:2] + scen_groups[4:5] + scen_groups[6:7]:
        if not g:
            continue
        for lab, key in (("напрям", lambda r: r["dir"]), ("H4", rel_h4), ("BTC 4 год", rel_btc), ("тип рівня", lambda r: r["lvl_kind"])):
            sub: Dict[str, List[dict]] = {}
            for r in g:
                sub.setdefault(key(r), []).append(r)
            groups = [(f"{lab}: {k}", v) for k, v in sorted(sub.items()) if len(v) >= 40]
            if groups:
                L += E.table(f"{name} — розріз «{lab}»", groups, train_only=tr_only, cut_day=cut)
    # ===== ЗАФІКСОВАНІ ГІПОТЕЗИ HS1–HS3 (HYPOTHESES.md, раунд 2): друкуються ЛИШЕ з --open-test =====
    if a.open_test:
        L.append("\n## Зафіксовані гіпотези раунду 2 (HS1–HS3): train і test поруч — test відкрито один раз\n")
        wt = lambda r: r["reg4"] * sg(r) > 0
        hs1a = [r for r in rows if r["trigger"] == "choch" and wt(r)]
        hs1b = [r for r in sc_rows if r["trigger"] == "retest" and wt(r)]
        hs1c = hs1a + hs1b + [r for r in sc_rows if r["trigger"] == "accept" and wt(r)]
        L += E.table("HS1: сценарії лише по тренду H4", [("HS1a: REVERSAL (CHoCH) по тренду H4", hs1a), ("HS1b: BREAKOUT+RETEST по тренду H4", hs1b), ("HS1c: об'єднання (HS1a ∪ HS1b ∪ CONTINUATION по тренду)", hs1c)])
        allsc = [r for r in rows if r["trigger"] in ("choch", "reclaim")] + sc_rows
        aligned = [r for r in allsc if wt(r)]
        rest = [r for r in allsc if not wt(r)]
        L.append("\n### HS2: різниця середнього R після комісій «по тренду H4» − «решта» (усі сценарні входи)\n")
        L.append("| Набір | N по тренду | N решта | R по тренду | R решта | різниця (кластерний 95% ІВ) |\n|---|---|---|---|---|---|")
        for lab, f in (("train", lambda r: r["day"] < cut), ("test", lambda r: r["day"] >= cut)):
            x = [r for r in aligned if f(r)]
            y = [r for r in rest if f(r)]
            pt, lo, hi = E.diff_ci(x, y)
            L.append(f"| {lab} | {len(x)} | {len(y)} | {E._mean_r(x):+.3f} | {E._mean_r(y):+.3f} | {pt:+.3f} ({lo:+.3f}…{hi:+.3f}) |")
        L.append("\n### HS3: дрейф +4 год (ATR15) у бік пробою при проколі ПО тренду H4 (поведінка A або ACCEPT)\n")
        L.append("| Набір | N | середній рух +4 год (кластерний 95% ІВ) | частка >0 |\n|---|---|---|---|")
        for lab, f in (("train", lambda b: b["day"] < cut), ("test", lambda b: b["day"] >= cut)):
            g = [((b["symbol"], b["day"]), b["fwd4h_atr"]) for b in behav if f(b) and b["rel"] == "за трендом пробою" and b["behavior"] in ("A", "ACCEPT") and b["fwd4h_atr"] is not None]
            if g:
                lo, hi = boot_mean(g)
                L.append(f"| {lab} | {len(g)} | {sum(v for _, v in g) / len(g):+.2f} ({lo:+.2f}…{hi:+.2f}) | {sum(1 for _, v in g if v > 0) / len(g) * 100:.0f}% |")
    # портфель
    L.append("\n### Risk Manager (портфель): фіксований $-ризик, структурний SL, портфельні ліміти\n")
    for name, sel in (("БАЗА", [r for r in rows if r["trigger"] == "reclaim"]),
                      ("БАЗА + S1 + S2 + S7", [r for r in rows if r["trigger"] == "reclaim" and r["htf_ok"] and r["btc_ok"] and r["flow_ok"]]),
                      ("CHoCH + S1 + S2 + S7", [r for r in rows if r["trigger"] == "choch" and r["htf_ok"] and r["btc_ok"] and r["flow_ok"]])):
        if not sel:
            L.append(f"- {name}: немає кандидатів")
            continue
        pf = R.simulate_portfolio([dict(x, lvl_key=(x["symbol"], x["dir"], round(x["lvl_p"], 6))) for x in sel])
        L.append(f"- {name}: кандидатів {len(sel)} → прийнято {len(pf['accepted'])}, відхилено {sum(pf['rejected'].values())} {pf['rejected']}; сума {pf['total_r']:+.1f} R, макс. просадка {pf['max_dd_r']:.1f} R, найгірший день {pf['worst_day_r']:+.1f} R.")
    if a.md:
        Path(a.md).write_text("\n".join(L) + "\n")
    if a.json:
        Path(a.json).write_text(json.dumps({"rows": rows}, default=float))
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

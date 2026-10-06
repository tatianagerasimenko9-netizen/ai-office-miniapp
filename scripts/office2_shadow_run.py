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
from office2 import probe as PR  # noqa: E402
from office2 import narrative as NR  # noqa: E402

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
    ap.add_argument("--legacy-test", action="store_true", help="старі розділи (сценарний шар, HS1–HS3, HD1/HD2): відкрити test. Раунд 2 уже відкрито; HD1 призупинено власницею — НЕ вмикати")
    ap.add_argument("--open-test", action="store_true", help="test для класу IMPULSE→COMPRESSION→BREAKOUT (HN-A/HN-A2/HN-B, matched) — лише ПІСЛЯ фіксації гіпотез у HYPOTHESES.md")
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
    obs_all: List[dict] = []
    nrows: List[dict] = []
    nctrl: List[dict] = []
    nstats: Dict[str, int] = {}
    nev: List[dict] = []
    npairs: List[dict] = []
    npstruct: List[dict] = []
    nevc: List[dict] = []
    p48 = P.Params(horizon_sec=48 * 3600)
    for i, sym in enumerate(syms):
        m1, missing = (btc_m1, miss) if sym == "BTCUSDT" else D.load_symbol(sym, d0, d1, cache, a.offline)
        if m1 is None or len(m1["t"]) < 3 * 1440:
            skipped[sym] = len(missing)
            continue
        ctx = btc_ctx if sym == "BTCUSDT" else P.build_context(m1)
        c = P.candidates(sym, ctx, btc_ctx, p, stats)
        rows.extend(E.evaluate(c, {sym: ctx}, p))
        obs_all.extend(PR.build_observations(sym, ctx, btc_ctx, p))
        nrows.extend(E.evaluate(NR.candidates(sym, ctx, btc_ctx, NR.NParams(), nstats), {sym: ctx}, p48))
        nctrl.extend(E.evaluate(NR.generic_controls(sym, ctx, 25), {sym: ctx}, p48))
        nev.extend(NR.event_outcomes(sym, ctx, btc_ctx, NR.NParams(), nstats))
        nevc.extend(NR.event_controls(sym, ctx, 40))
        _pr = NR.matched_pairs(sym, ctx, btc_ctx, NR.NParams(), nstats)
        npairs.extend(_pr)
        _pday = {r["pair"]: r["day"] for r in _pr}
        for _x in E.evaluate([r["cand"] for r in _pr if r["rr15"]], {sym: ctx}, p48):
            _x["day"] = _pday[_x["pair"]]
            npstruct.append(_x)
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
    tr_leg = not a.legacy_test      # старі розділи (сценарний шар, HS1–HS3, probe HD1) — test лишається закритим, якщо не --legacy-test
    L.append("\n## Сценарний шар: Office спершу визначає, що сталося з ціною, а вже потім вибирає вхід\n")
    L.append(f"> {'TRAIN-ONLY: test не відкривається, гіпотези ще не заморожені.' if tr_leg else 'Test відкритий для зафіксованих гіпотез (HYPOTHESES.md).'} Метрика, яку показуємо завжди: **середній R після комісій** (математичне сподівання угоди), а не лише TP1-first.\n")
    L.append(f"Проколів рівнів: {sc_stats.get('pierces', 0)}; прийняттів (2 закриття за рівнем): {sc_stats.get('accept_events', 0)}; кандидатів CONT: {sc_stats.get('accept_candidate', 0)}, RETEST: {sc_stats.get('retest_candidate', 0)}.\n")
    # 1) поведінка після проколу: дрейф у бік пробою
    bt = [b for b in behav if b["day"] < cut] if tr_leg and cut is not None else behav
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
    L += E.table("Сценарії (Office спершу визначає ситуацію): N → TP1-first → SL-first → таймаут → база → надлишок → середній R після комісій", scen_groups, train_only=tr_leg, cut_day=cut)
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
                L += E.table(f"{name} — розріз «{lab}»", groups, train_only=tr_leg, cut_day=cut)
    # ===== ЗАФІКСОВАНІ ГІПОТЕЗИ HS1–HS3 (HYPOTHESES.md, раунд 2): друкуються ЛИШЕ з --open-test =====
    if a.legacy_test:
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
    # ===== SETUP NARRATIVE: IMPULSE → COMPRESSION → BREAKOUT (H1; TRAIN; test лише з --open-test) =====
    L.append("\n## Setup narrative: IMPULSE → COMPRESSION → BREAKOUT (H1, LONG і SHORT; дослідницьке визначення, не оптимізоване)\n")
    L.append(f"> {'TRAIN-ONLY: test не відкривається.' if tr_only else 'Test відкритий для зафіксованих гіпотез.'} Outcome: структурна угода (SL = мінімум корекції − 0,5 ATR_H1; TP = хай імпульсу; RR ≥1,5; ризик 0,3–10%; горизонт 48 год).\n")
    L.append(f"Воронка: імпульсів ≥3 ATR: {nstats.get('impulses', 0)}; з пробоєм похилої після стиснення: {nstats.get('breakouts', 0)}; після дедуплікації (1 пробій = 1 подія): {nstats.get('breakouts_dedup', 0)}; "
             f"без пробою: {nstats.get('no_breakout', 0)}; кандидатів «пробій»: {nstats.get('break_candidate', 0)} (немає простору до хая: {nstats.get('break_no_room', 0)}, ризик поза межами: {nstats.get('break_risk_out', 0)}); "
             f"«прийняття»: {nstats.get('accept_candidate', 0)} (немає прийняття: {nstats.get('accept_missing', 0)}).\n")
    cutn = E.cut_day(nrows + nctrl)
    brk = [r for r in nrows if r["trigger"] == "break"]
    acc = [r for r in nrows if r["trigger"] == "accept"]
    L += E.table("Клас IMPULSE→COMPRESSION→BREAKOUT: N → TP1-first → SL-first → таймаут → база → надлишок → середній R після комісій → MFE/MAE", [
        ("вхід на пробої (закриття H1 над похилою)", brk), ("вхід на прийнятті (наступне закриття над лінією)", acc),
        ("  пробій: LONG", [r for r in brk if r["dir"] == "LONG"]), ("  пробій: SHORT", [r for r in brk if r["dir"] == "SHORT"]),
        ("  пробій: блок утримався (мін. корекції ≥ origin −0,3 ATR)", [r for r in brk if r["feat"]["block_held"] > 0.5]),
        ("  пробій: блок НЕ утримався", [r for r in brk if r["feat"]["block_held"] <= 0.5]),
        ("КОНТРОЛЬ: загальний структурний вхід у випадкові години (без імпульсу/стиснення/пробою)", nctrl)], train_only=tr_only, cut_day=cutn)
    trb = [r for r in brk if cutn is None or r["day"] < cutn] if tr_only else brk
    trb = [r for r in trb if r["outcome"] in ("TP", "SL")]
    if len(trb) >= 60:
        L.append("\n### TRAIN: чим ДО входу відрізняються хороші й погані екземпляри (AUC проти TP-before-SL; Spearman із MFE, MAE (R, 48 год) і net R) — діагностика, не правила\n")
        L.append("| Ознака | AUC→TP | ρ MFE | ρ MAE | ρ net R |\n|---|---|---|---|---|")
        import numpy as _np
        for k in sorted(trb[0]["feat"].keys()):
            x = _np.array([r["feat"][k] for r in trb], dtype=float)
            if x.std() == 0:
                continue
            y = _np.array([1.0 if r["outcome"] == "TP" else 0.0 for r in trb])
            L.append(f"| {k} | {PR.auc(x, y):.3f} | {PR._fmt(PR.spearman(x, _np.array([r['mfe_full_r'] for r in trb])), 2)} | {PR._fmt(PR.spearman(x, _np.array([r['mae_full_r'] for r in trb])), 2)} | {PR._fmt(PR.spearman(x, _np.array([r['r_net'] for r in trb])), 2)} |")
        L.append(f"\nN={len(trb)} (TP/SL); ознак ≈20 — випадково «значущі» значення очікувані; рішення лише за замороженою гіпотезою на test.\n")
    # ===== ПИТАННЯ A (послідовність має цінність?) vs B (чи добра конструкція SL/TP/RR?): усі події пробою, без фільтра RR =====
    L.append("\n### A/B: усі дедупліковані події пробою — рух після входу НЕЗАЛЕЖНО від RR до старого хая (діагностика outcome; параметри детектора не змінювались)\n")
    L.append("A: чи має сама послідовність IMPULSE→COMPRESSION→BREAKOUT прогнозну цінність (порівняння з контролем: випадкові години, той самий тип структурного SL). B: чи хороша поточна конструкція SL/TP/RR (група RR≥1,5 проти RR<1,5). "
             "Вхід = відкриття 1m після закриття пробійного H1; R = відстань до структурного SL (мін. корекції −0,5 ATR_H1); MFE/MAE не обрізані TP/SL; медіани.\n")
    cute = E.cut_day(nev + nevc)
    def _sel(rs):
        return [r for r in rs if r["day"] < cute] if (tr_only and cute is not None) else rs
    import numpy as _np2
    def _row(name, rs):
        n = len(rs)
        if n == 0:
            return f"| {name} | 0 | — |"
        md = lambda k: float(_np2.median([r[k] for r in rs]))
        cl = len({(r["symbol"], r["day"]) for r in rs})
        mfe = " / ".join(f"{md(f'mfe_r_{h}'):.2f}·{md(f'mae_r_{h}'):.2f}" for h in NR.HORIZONS_H)
        sh = lambda f: f"{sum(1 for r in rs if f(r)) / n * 100:.0f}%"
        return (f"| {name} | {n} ({cl}) | {mfe} | {sh(lambda r: r['mfe_r_48'] >= 1)} / {sh(lambda r: r['mfe_r_48'] >= 2)} | {md('mfe_to_inval_r'):.2f} | "
                f"{sh(lambda r: r['inval_min'] is not None)} | {sh(lambda r: r['back_below_min'] is not None and r['back_below_min'] <= 240)} | "
                f"{sh(lambda r: r['high_min'] is not None)} / {sh(lambda r: r['high_before_inval'])} | {md('t_mfe_min'):.0f} / {md('t_mae_min'):.0f} |")
    L.append("| Група | N (кластерів) | MFE·MAE у R, медіана: 1 год / 4 / 12 / 24 / 48 | MFE48 ≥1R / ≥2R | медіана макс. руху до інвалідації, R | інвалідація ≤48 год | повернення під рівень пробою ≤4 год | досяг хая імпульсу / до інвалідації | час до MFE / MAE, хв (мед.) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    ev_t = _sel(nev)
    for name, rs in (("УСІ події пробою", ev_t), ("  RR до хая < 1,5 (відсіялись би)", [r for r in ev_t if not r["rr15"]]), ("  RR до хая ≥ 1,5 (стали б угодами)", [r for r in ev_t if r["rr15"]]),
                     ("  усі LONG", [r for r in ev_t if r["dir"] == "LONG"]), ("  усі SHORT", [r for r in ev_t if r["dir"] == "SHORT"]),
                     ("КОНТРОЛЬ: випадкові години, випадковий напрям", _sel(nevc))):
        L.append(_row(name, rs))
    L.append("\n### EXPLORATORY (не преддекларована): що першим після входу — +k·R чи −1R (структурний SL)? Це outcome, не feature. Порядок руху, а не лише MFE/MAE. Стоп у ту саму хвилину — раніше.\n")
    L.append("| Група | N | +0,5R раніше −1R (випадкове блукання: 67%) | +1R раніше −1R (50%) | +1,5R раніше −1R (40%) | +2R раніше −1R (33%) | жодного за 48 год (при +1R) |")
    L.append("|---|---|---|---|---|---|---|")
    for name, rs in (("УСІ події пробою", ev_t), ("  RR до хая < 1,5", [r for r in ev_t if not r["rr15"]]), ("  RR до хая ≥ 1,5", [r for r in ev_t if r["rr15"]]),
                     ("  LONG", [r for r in ev_t if r["dir"] == "LONG"]), ("  SHORT", [r for r in ev_t if r["dir"] == "SHORT"]), ("КОНТРОЛЬ", _sel(nevc))):
        n = len(rs)
        if n == 0:
            L.append(f"| {name} | 0 |  |  |  |  |  |")
            continue
        cells = []
        for kr in NR.ORDER_K:
            gk = [((r["symbol"], r["day"]), 1.0 if r[f"order_{kr}"] == "up" else 0.0) for r in rs]
            lo, hi = boot_mean(gk)
            cells.append(f"{sum(v for _, v in gk) / n * 100:.0f}% ({lo * 100:.0f}…{hi * 100:.0f})")
        none1 = sum(1 for r in rs if r["order_1.0"] == "none") / n * 100
        L.append(f"| {name} | {n} | " + " | ".join(cells) + f" | {none1:.0f}% |")
    L.append("\nУ дужках кластерний 95% ІВ (symbol+день). Ніяких порогів не підбирається; потрібно лише порівняти «події» з «контролем» і з випадковим блуканням.\n")
    L.append(f"\nВоронка діагностики: подій {nstats.get('ev_n', 0)}; без 1m-входу {nstats.get('ev_no_entry', 0)}; без outcome (ризик ≤0 або <1 год даних) {nstats.get('ev_no_outcome', 0)}. Ризик% подій (медіана): "
             f"{(_np2.median([r['risk_pct'] for r in ev_t]) if ev_t else float('nan')):.2f}%; контроль: {(_np2.median([r['risk_pct'] for r in _sel(nevc)]) if _sel(nevc) else float('nan')):.2f}%.\n")
    def boot_diff(x: List[tuple], y: List[tuple]) -> tuple:
        cx: Dict[tuple, List[float]] = {}
        cy: Dict[tuple, List[float]] = {}
        for k, v in x:
            cx.setdefault(k, []).append(v)
        for k, v in y:
            cy.setdefault(k, []).append(v)
        kx, ky = list(cx), list(cy)
        if len(kx) < 8 or len(ky) < 8:
            return float("nan"), float("nan"), float("nan")
        m = lambda c, ks, rr: (lambda smp: sum(smp) / len(smp))([v for k in (rr.choice(ks) for _ in ks) for v in c[k]])
        rr = _rnd.Random(17)
        ds = sorted(m(cx, kx, rr) - m(cy, ky, rr) for _ in range(500))
        mean_x = sum(v for vs in cx.values() for v in vs) / sum(len(vs) for vs in cx.values())
        mean_y = sum(v for vs in cy.values() for v in vs) / sum(len(vs) for vs in cy.values())
        return mean_x - mean_y, ds[12], ds[487]


    # ===== EXPLORATORY: MATCHED-IMPULSE CONTROL (правило matching зафіксовано до test; HYPOTHESES.md, поправка 5) =====
    L.append("\n### EXPLORATORY: matched-impulse control — чи додає COMPRESSION→BREAKOUT інформацію понад уже наявний імпульс?\n")
    L.append("Контроль для кожної події: той самий символ і напрям, стан «після імпульсу» (корекція 8–60 барів, ретрейс 25–90%, хай імпульсу не перевищено), але БЕЗ завершеного пробою (±3 бари від подій виключені). "
             "Жорстко: та сама сесія UTC і той самий H4/D1 режим відносно напряму; caliper: імпульс 0,7–1,3×, ATR_H1/ціна 0,7–1,43×; відстань = |Δімпульсу| + |ln Δволатильності| + (BTC-кошик ±0,3% не збігся → 1). Один контроль на подію, без повторів. Показано ПАРИ.\n")
    cutp = E.cut_day([r for r in npairs]) if npairs else None
    pr_t = [r for r in npairs if (r["day"] < cutp)] if (tr_only and cutp is not None) else npairs
    pe = {r["pair"]: r for r in pr_t if r["kind"] == "event"}
    pc = {r["pair"]: r for r in pr_t if r["kind"] == "matched"}
    ids = sorted(set(pe) & set(pc))
    L.append(f"Пар: {len(ids)}; подій без пари (немає контролю в caliper): {nstats.get('pair_unmatched', 0)} (за всю вибірку, включно з test-частиною лічильника).\n")
    if ids:
        L.append("| Метрика | подія | matched-контроль | різниця по парах (кластерний 95% ІВ) |\n|---|---|---|---|")
        for name, fn in (("+0,5R раніше −1R", lambda r: 1.0 if r["order_0.5"] == "up" else 0.0), ("+1R раніше −1R", lambda r: 1.0 if r["order_1.0"] == "up" else 0.0),
                         ("+1,5R раніше −1R", lambda r: 1.0 if r["order_1.5"] == "up" else 0.0), ("+2R раніше −1R", lambda r: 1.0 if r["order_2.0"] == "up" else 0.0),
                         ("MFE48, R (середнє)", lambda r: r["mfe_r_48"]), ("MAE48, R (середнє)", lambda r: r["mae_r_48"]), ("MFE48−MAE48, R", lambda r: r["mfe_r_48"] - r["mae_r_48"])):
            dd = [((pe[i]["symbol"], pe[i]["day"]), fn(pe[i]) - fn(pc[i])) for i in ids]
            lo, hi = boot_mean(dd)
            mx = sum(fn(pe[i]) for i in ids) / len(ids)
            my = sum(fn(pc[i]) for i in ids) / len(ids)
            pct = name.startswith("+")
            f = (lambda v: f"{v * 100:.0f}%") if pct else (lambda v: f"{v:+.2f}")
            fd = (lambda v: f"{v * 100:+.0f} п.п.") if pct else (lambda v: f"{v:+.2f}")
            L.append(f"| {name} | {f(mx)} | {f(my)} | {fd(mx - my)} ({fd(lo)}…{fd(hi)}) |")
        md = sorted(pe[i]["match_d"] for i in ids)
        L.append(f"\nЯкість matching: медіана відстані {md[len(md) // 2]:.2f}; медіана ризику% події {sorted(pe[i]['risk_pct'] for i in ids)[len(ids) // 2]:.2f}% / контролю {sorted(pc[i]['risk_pct'] for i in ids)[len(ids) // 2]:.2f}%.\n")
        idset = set(ids)
        sx = [(( r["symbol"], r["day"]), r["r_net"]) for r in npstruct if r["pair"] in idset and r["trigger"] == "pair_event" and (cutp is None or not tr_only or r["day"] < cutp)]
        sy = [((r["symbol"], r["day"]), r["r_net"]) for r in npstruct if r["pair"] in idset and r["trigger"] == "pair_matched" and (cutp is None or not tr_only or r["day"] < cutp)]
        if sx and sy:
            d, lo, hi = boot_diff(sx, sy)
            L.append(f"\nСтруктурна угода (SL під корекцією, TP хай імпульсу, RR ≥1,5; фільтр застосовується до кожної сторони окремо): подія N={len(sx)} R {sum(v for _, v in sx) / len(sx):+.3f}; matched N={len(sy)} R {sum(v for _, v in sy) / len(sy):+.3f}; різниця {d:+.3f} ({lo:+.3f}…{hi:+.3f}).\n")
    L.append("")
    # ===== ЗАФІКСОВАНІ ГІПОТЕЗИ HN-A / HN-A2 / HN-B (HYPOTHESES.md, раунд 3, поправки 2–3): лише з --open-test =====
    if a.open_test:
        L.append("\n## Зафіксовані гіпотези класу IMPULSE→COMPRESSION→BREAKOUT (HN-A, HN-A2, HN-B): train і test поруч — test відкрито один раз\n")

        cl = lambda r: (r["symbol"], r["day"])
        cutx = E.cut_day(nev + nevc)
        L.append("| ID | набір | події: N | контроль: N | подія | контроль | різниця (кластерний 95% ІВ) |\n|---|---|---|---|---|---|---|")
        for lab, f in (("train", lambda r: r["day"] < cutx), ("test", lambda r: r["day"] >= cutx)):
            ev_s = [r for r in nev if f(r)]
            ct_s = [r for r in nevc if f(r)]
            for hid, fn, name in (("HN-A", lambda r: r["mfe_r_48"] - r["mae_r_48"], "середнє MFE48−MAE48, R"),
                                  ("HN-A2", lambda r: 1.0 if r["order_1.0"] == "up" else 0.0, "частка «+1R раніше −1R»")):
                x = [(cl(r), fn(r)) for r in ev_s]
                y = [(cl(r), fn(r)) for r in ct_s]
                d, lo, hi = boot_diff(x, y)
                mx = sum(v for _, v in x) / max(len(x), 1)
                my = sum(v for _, v in y) / max(len(y), 1)
                L.append(f"| {hid}: {name} | {lab} | {len(x)} | {len(y)} | {mx:+.3f} | {my:+.3f} | {d:+.3f} ({lo:+.3f}…{hi:+.3f}) |")
        L.append("\n### HN-B: структурна угода (SL під корекцією, TP хай імпульсу, RR≥1,5), середній R після комісій; для контексту — «загальний структурний вхід»\n")
        L.append("| набір | вхід на пробої: N | R (кластерний 95% ІВ) | контроль: N | R | різниця «пробій − контроль» (ІВ) |\n|---|---|---|---|---|---|")
        for lab, f in (("train", lambda r: r["day"] < cutn), ("test", lambda r: r["day"] >= cutn)):
            x = [(cl(r), r["r_net"]) for r in brk if f(r) and r["outcome"] is not None]
            y = [(cl(r), r["r_net"]) for r in nctrl if f(r) and r["outcome"] is not None]
            lo1, hi1 = boot_mean(x)
            d, lo, hi = boot_diff(x, y)
            L.append(f"| {lab} | {len(x)} | {sum(v for _, v in x) / max(len(x), 1):+.3f} ({lo1:+.3f}…{hi1:+.3f}) | {len(y)} | {sum(v for _, v in y) / max(len(y), 1):+.3f} | {d:+.3f} ({lo:+.3f}…{hi:+.3f}) |")
        L.append("\nHN-B формально: R>0 з ІВ, що виключає 0. Різниця з контролем показана, бо на train «загальний структурний вхід» сам дав R>0 (дрейф періоду) — без контролю HN-B не відрізняє сетап від дрейфу.\n")
    L += PR.report(obs_all, cut, a.legacy_test)
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

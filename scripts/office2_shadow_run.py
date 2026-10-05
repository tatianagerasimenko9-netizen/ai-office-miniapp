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
    a = ap.parse_args()
    syms = [s for s in (a.symbols.split(",") if a.symbols else DEFAULT_SYMBOLS) if s]
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
    for i, sym in enumerate(syms):
        m1, missing = (btc_m1, miss) if sym == "BTCUSDT" else D.load_symbol(sym, d0, d1, cache, a.offline)
        if m1 is None or len(m1["t"]) < 3 * 1440:
            skipped[sym] = len(missing)
            continue
        ctx = btc_ctx if sym == "BTCUSDT" else P.build_context(m1)
        c = P.candidates(sym, ctx, btc_ctx, p)
        rows.extend(E.evaluate(c, {sym: ctx}, p))
        ctrl.extend(E.evaluate(E.random_control({sym: ctx}, 40, p), {sym: ctx}, p))
        print(f"[{i + 1}/{len(syms)}] {sym}: бар 1m {len(m1['t'])}, кандидатів {len(c)}, пропущених днів {len(missing)}, {time.time() - t0:.0f} с", flush=True)
    L: List[str] = [f"# Office 2.0 shadow-replay: {a.d0} … {a.d1} UTC", "",
                    f"Символів із даними: {len({r['symbol'] for r in rows})} (пропущено: {len(skipped)}); кандидатів із повним горизонтом 24 год: {len(rows)}; сіднійний контроль: {len(ctrl)}.",
                    f"Параметри (задані заздалегідь, не підбиралися): K_BUF={p.k_buf}·ATR15, MIN_RR={p.min_rr}, max TP {p.max_tp_r}R, CHoCH ≤{p.choch_bars} барів. Комісія кола 0,10% (R чистий = R − 0,10%/ризик%).",
                    "Метрика: **надлишок = факт TP-first − геометрична база r/(r+t)** (кластерний бутстреп за symbol+день). Train = перші 60% діб, test = решта, test×hold-out = test на ≈1/3 символів, не використаних у дизайні.", ""]
    L += E.table("Сіднійний контроль (випадковий вхід, SL 2·ATR15, TP 3·ATR15): очікуваний надлишок ≈ 0", [("випадкові входи", ctrl)])
    L += E.table("Абляція етапів Office 2.0 (кожен етап має довести надлишок, не лише існувати)", E.ablation(rows))
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

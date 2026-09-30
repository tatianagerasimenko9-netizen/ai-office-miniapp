"""CLI: звірка Pine-еталону з продакшн-детекторами на ТИХ САМИХ свічках (без TradingView CSV).
  python3 scripts/compare_pine_python.py              # синтетичні свічки
  python3 scripts/compare_pine_python.py --csv f.csv  # свої: ts,open,high,low,close,volume"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import office_pine_parity as pp  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--win", type=int, default=100, help="скільки барів бачить продакшн-детектор")
    a = ap.parse_args()
    bars = pp.load_csv(a.csv) if a.csv else pp.synthetic()
    print(f"свічок: {len(bars)} · джерело: {a.csv or 'синтетичні (seed=7)'} · вікно продакшн-детектора: {a.win}\n")
    pine, stats = pp.compare(bars, win=a.win)
    pp.print_report(stats)
    print()
    for k, (py, pn) in pp.compare_levels(bars, pine).items():
        d = "—" if py is None or pn is None else f"{abs(py - pn):.6g}"
        print(f"{k:62s} Python={py} Pine={pn} Δ={d}")


if __name__ == "__main__":
    main()

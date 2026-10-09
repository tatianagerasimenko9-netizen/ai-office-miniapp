#!/usr/bin/env python3
"""Time-frozen replay Brain v2.1 vs SMC на РЕАЛЬНИХ біржових OHLCV (npz із scripts/smc_real_convert.py). Експлоративно: не доказ прибутковості, малі вибірки, спрощений вихід.
Використання: python scripts/smc_real_replay.py <каталог npz> <вихідний json> [ім'я1,ім'я2,...] [warmup_bars]"""
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2.smc import replay as RP  # noqa: E402


def load(path):
    z = np.load(path)
    arrs = {}
    for tf in ("m15", "h4", "d1", "w1"):
        arrs[tf] = {k: z[f"{tf}_{k}"] for k in ("t", "o", "h", "l", "c", "v", "tbv")}
    arrs["mn"] = None
    return arrs


def run_one(args):
    path, warm = args
    name = Path(path).stem
    arrs = load(path)
    m15 = arrs["m15"]
    ends = m15["t"] + 900
    t_from = float(ends[min(warm, len(ends) - 1)])
    t_to = float(ends[-1])
    t0 = time.time()
    r = RP.replay_arrays(name, arrs, t_from, t_to)
    r["elapsed_total_s"] = round(time.time() - t0, 1)
    return r


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    names = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[3] else [p.stem for p in sorted(src.glob("*.npz"))]
    warm = int(sys.argv[4]) if len(sys.argv) > 4 else 140
    from multiprocessing import Pool

    jobs = [(str(src / f"{n}.npz"), warm) for n in names]
    with Pool(min(len(jobs), 4)) as pool:
        runs = pool.map(run_one, jobs)
    summ = RP.summarize(runs)
    out.write_text(json.dumps({"summary": summ, "runs": [{k: v for k, v in r.items()} for r in runs]}, ensure_ascii=False, default=float, indent=1))
    print(json.dumps(summ, ensure_ascii=False, indent=1, default=float))


if __name__ == "__main__":
    main()

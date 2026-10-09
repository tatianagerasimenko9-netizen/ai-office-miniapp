#!/usr/bin/env python3
"""Конвертація feather з публічного тест-набору freqtrade (реальні біржові OHLCV) у npz для офлайн-replay. Потрібні pandas+pyarrow (не входять до CI).
Дані — ДОДАТКОВЕ інтернет-джерело, окреме від методики SM Trader; ліцензію набору не змінюємо і в репозиторій не копіюємо.
Використання: python scripts/smc_real_convert.py <каталог tests/testdata> <каталог виходу>"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CASES = {"BTC_USDT-5m.feather": "BTCUSDT_2025", "XRP_USDT-5m.feather": "XRPUSDT_2025", "futures/XRP_USDT_USDT-5m-futures.feather": "XRPUSDT_FUT_2021", "UNITTEST_BTC-5m.feather": "UNITTEST_BTC_2018",
         "ETH_BTC-5m.feather": "ETHBTC_2018", "LTC_BTC-5m.feather": "LTCBTC_2018", "ADA_BTC-5m.feather": "ADABTC_2018", "XMR_BTC-5m.feather": "XMRBTC_2018", "DASH_BTC-5m.feather": "DASHBTC_2018"}


def to_arr(df, width):
    t = (df["date"].astype("int64") // 10**9).to_numpy().astype(float)          # epoch секунди (UTC)
    t = np.where(t > 4e10, t / 1e3, t) if False else t
    g = np.floor(t / width).astype(np.int64)
    first = np.r_[True, np.diff(g) != 0]
    st = np.flatnonzero(first)
    en = np.r_[st[1:] - 1, len(g) - 1]
    o, h, l, c, v = (df[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close", "volume"))
    return {"t": (g[st] * width).astype(float), "o": o[st], "h": np.maximum.reduceat(h, st), "l": np.minimum.reduceat(l, st), "c": c[en], "v": np.add.reduceat(v, st), "tbv": np.zeros(len(st))}


def main(src, dst):
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for f, name in CASES.items():
        p = Path(src) / f
        if not p.exists():
            print("немає", p)
            continue
        df = pd.read_feather(p).dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
        ts = pd.to_datetime(df["date"], utc=True)
        df["date"] = ts.dt.tz_convert("UTC").dt.tz_localize(None)
        df["date"] = df["date"].astype("datetime64[ns]")
        out = {}
        for tf, w in (("m15", 900), ("h4", 14400), ("d1", 86400), ("w1", 604800)):
            a = to_arr(df, w)
            for k, v in a.items():
                out[f"{tf}_{k}"] = v
        np.savez_compressed(dst / f"{name}.npz", **out)
        print(name, len(df), "5m →", len(out["m15_t"]), "M15,", df["date"].iloc[0], "…", df["date"].iloc[-1])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

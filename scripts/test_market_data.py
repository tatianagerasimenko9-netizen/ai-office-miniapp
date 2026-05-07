from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from office_market_data import (  # noqa: E402
    fetch_btc_candles,
    fetch_liquidations_proxy,
    fetch_open_interest,
)


def main() -> None:
    print("=== market data test ===")

    print("\n[1] BTC candles 1d")
    print(fetch_btc_candles("1d", 3))

    print("\n[2] BTC candles 4h")
    print(fetch_btc_candles("4h", 3))

    print("\n[3] Open interest BTCUSDT")
    print(fetch_open_interest("BTCUSDT"))

    print("\n[4] Liquidations proxy BTCUSDT")
    print(fetch_liquidations_proxy("BTCUSDT"))


if __name__ == "__main__":
    main()

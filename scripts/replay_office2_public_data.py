#!/usr/bin/env python3
"""Read-only real-data replay через публічний candle API production Mini App.

Не запускає READY, Telegram чи ордери. Останній forming-бар відкидається,
джерело/якість і часовий діапазон записуються у звіт.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office2.smc import replay as RP  # noqa: E402


TF = {"m15": "M15", "h4": "H4", "d1": "D1", "w1": "W1"}


def _get(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "AI-Office-readonly-replay/1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310 - endpoint задає оператор
        return json.loads(response.read().decode("utf-8"))


def fetch_arrays(base_url: str, symbol: str, limit: int = 500) -> tuple[Dict[str, Optional[Dict[str, np.ndarray]]], Dict[str, Any]]:
    arrays: Dict[str, Optional[Dict[str, np.ndarray]]] = {}
    provenance: Dict[str, Any] = {}
    for key, tf in TF.items():
        query = urllib.parse.urlencode({"symbol": symbol, "tf": tf, "limit": limit})
        payload = _get(f"{base_url.rstrip('/')}/api/v2/candles?{query}")
        rows = [r for r in payload.get("candles") or [] if not r.get("forming")]
        if payload.get("data_status") != "DATA_OK" or payload.get("fixture") or not rows:
            raise RuntimeError(f"{symbol} {tf}: real DATA_OK bars unavailable")
        arrays[key] = {
            "t": np.asarray([float(r["time"]) for r in rows], dtype=float),
            "o": np.asarray([float(r["open"]) for r in rows], dtype=float),
            "h": np.asarray([float(r["high"]) for r in rows], dtype=float),
            "l": np.asarray([float(r["low"]) for r in rows], dtype=float),
            "c": np.asarray([float(r["close"]) for r in rows], dtype=float),
            "v": np.asarray([float(r.get("volume") or 0.0) for r in rows], dtype=float),
            "tbv": np.full(len(rows), np.nan, dtype=float),
        }
        provenance[key] = {"source": payload.get("source"), "data_status": payload.get("data_status"), "bars": len(rows),
                           "first_open_utc": int(rows[0]["time"]), "last_open_utc": int(rows[-1]["time"]), "forming_dropped": True}
    arrays["mn"] = None
    return arrays, provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://ai-office-miniapp.onrender.com")
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,LTCUSDT,ONDOUSDT")
    parser.add_argument("--days", type=int, default=1, choices=(1, 2))
    parser.add_argument("--fee-rt-pct", type=float, default=RP.DEFAULT_FEE_RT_PCT)
    parser.add_argument("--slippage-rt-bps", type=float, default=RP.DEFAULT_SLIPPAGE_RT_BPS)
    parser.add_argument("--entry-delay-sec", type=float, default=RP.DEFAULT_ENTRY_DELAY_SEC)
    parser.add_argument("--ttl-sec", type=float, default=RP.DEFAULT_ENTRY_TTL_SEC)
    parser.add_argument("--output", default="/opt/cursor/artifacts/office2-real-replay.json")
    args = parser.parse_args()

    symbols = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    btc, btc_provenance = fetch_arrays(args.base_url, "BTCUSDT")
    runs = []
    provenance: Dict[str, Any] = {"BTCUSDT": btc_provenance}
    for symbol in symbols:
        arrs, source = (btc, btc_provenance) if symbol == "BTCUSDT" else fetch_arrays(args.base_url, symbol)
        provenance[symbol] = source
        m15 = arrs["m15"]
        assert m15 is not None
        last_closed = float(m15["t"][-1] + 900)
        decision_end = last_closed - RP.HORIZON_BARS * 900
        runs.append(RP.replay_arrays(
            symbol, arrs, decision_end - args.days * 86400, decision_end, btc=btc["m15"],
            fee_rt_pct=args.fee_rt_pct, slippage_rt_bps=args.slippage_rt_bps,
            entry_delay_sec=args.entry_delay_sec, entry_ttl_sec=args.ttl_sec,
        ))
    report = RP.summarize(runs)
    report["provenance"] = {"endpoint": args.base_url, "readonly": True, "symbols": provenance}
    report["window"] = {"days": args.days, "outcome_horizon_bars": RP.HORIZON_BARS, "m15_limit": 500}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

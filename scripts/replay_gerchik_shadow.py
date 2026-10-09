#!/usr/bin/env python3
"""Read-only real closed-OHLCV replay Brain + SMC + Gerchik shadow."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office2 import features as F  # noqa: E402
from office2.integration import gerchik_replay as RP  # noqa: E402

TF = {"m15": ("M15", "15m", 900), "h4": ("H4", "4h", 14400), "d1": ("D1", "1d", 86400)}
DEFAULT_SYMBOLS = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,LINKUSDT,LTCUSDT,BCHUSDT,TRXUSDT,AVAXUSDT,ONDOUSDT"


def _get(url: str, timeout: float = 30.0) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "AI-Office-Gerchik-shadow-replay/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-selected read-only endpoint
        return json.loads(response.read().decode("utf-8"))


def fetch_arrays(base_url: str, symbol: str, limit: int = 500) -> tuple[Dict[str, Optional[Dict[str, np.ndarray]]], Dict[str, Any]]:
    arrays: Dict[str, Optional[Dict[str, np.ndarray]]] = {}
    provenance: Dict[str, Any] = {}
    for key, (tf, expected_tf, width) in TF.items():
        query = urllib.parse.urlencode({"symbol": symbol, "tf": tf, "limit": limit})
        payload = _get(f"{base_url.rstrip('/')}/api/v2/candles?{query}")
        rows = [row for row in payload.get("candles") or [] if not row.get("forming")]
        if payload.get("data_status") != "DATA_OK" or payload.get("fixture") or payload.get("tf") != expected_tf or not rows:
            raise RuntimeError(f"{symbol} {tf}: real DATA_OK closed bars unavailable")
        times = np.asarray([float(row["time"]) for row in rows], dtype=float)
        gaps = int(np.sum(np.diff(times) != width))
        arrays[key] = {
            "t": times,
            "o": np.asarray([float(row["open"]) for row in rows], dtype=float),
            "h": np.asarray([float(row["high"]) for row in rows], dtype=float),
            "l": np.asarray([float(row["low"]) for row in rows], dtype=float),
            "c": np.asarray([float(row["close"]) for row in rows], dtype=float),
            "v": np.asarray([float(row.get("volume") or 0.0) for row in rows], dtype=float),
            "tbv": np.full(len(rows), np.nan, dtype=float),
        }
        provenance[key] = {
            "source": payload.get("source"),
            "data_status": payload.get("data_status"),
            "bars": len(rows),
            "first_open_utc": int(times[0]),
            "last_open_utc": int(times[-1]),
            "forming_dropped": True,
            "timestamp_gaps": gaps,
        }
    arrays["w1"] = F.resample(arrays["d1"], 7 * F.DAY, offset=F.WEEK_OFFSET)
    arrays["mn"] = None
    provenance["w1"] = {
        "source": "derived_from_closed_d1",
        "data_status": "DATA_OK",
        "bars": len(arrays["w1"]["t"]),
        "first_open_utc": int(arrays["w1"]["t"][0]),
        "last_open_utc": int(arrays["w1"]["t"][-1]),
        "forming_dropped": True,
        "timestamp_gaps": 0,
    }
    return arrays, provenance


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://ai-office-miniapp.onrender.com")
    parser.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    parser.add_argument("--days", type=int, default=2, choices=(1, 2))
    parser.add_argument("--fee-rt-pct", type=float, default=RP.FEE_RT_PCT)
    parser.add_argument("--slippage-rt-bps", type=float, default=RP.SLIPPAGE_RT_BPS)
    parser.add_argument("--entry-delay-sec", type=float, default=RP.ENTRY_DELAY_SEC)
    parser.add_argument("--ttl-sec", type=float, default=RP.ENTRY_TTL_SEC)
    parser.add_argument("--output", default="/opt/cursor/artifacts/gerchik-shadow-real-replay.json")
    args = parser.parse_args()

    symbols = [value.strip().upper() for value in args.symbols.split(",") if value.strip()]
    btc, btc_source = fetch_arrays(args.base_url, "BTCUSDT")
    runs = []
    provenance: Dict[str, Any] = {"BTCUSDT": btc_source}
    for symbol in symbols:
        arrays, source = (btc, btc_source) if symbol == "BTCUSDT" else fetch_arrays(args.base_url, symbol)
        provenance[symbol] = source
        m15 = arrays["m15"]
        assert m15 is not None
        last_closed = float(m15["t"][-1] + 900)
        decision_end = last_closed - RP.HORIZON_BARS * 900
        run = RP.replay_arrays(
            symbol,
            arrays,
            decision_end - args.days * F.DAY,
            decision_end,
            btc=btc["m15"],
            fee_rt_pct=args.fee_rt_pct,
            slippage_rt_bps=args.slippage_rt_bps,
            entry_delay_sec=args.entry_delay_sec,
            entry_ttl_sec=args.ttl_sec,
        )
        runs.append(run)
        print(f"{symbol}: bars={run['bars']} events={len(run['events'])} gerchik={run['gerchik_funnel']['detected']}", flush=True)
    report = RP.summarize(runs)
    try:
        code_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        code_revision = None
    report["code_revision"] = code_revision
    report["provenance"] = {"endpoint": args.base_url, "readonly": True, "symbols": provenance}
    report["window"] = {
        "days": args.days,
        "outcome_horizon_bars": RP.HORIZON_BARS,
        "m15_limit": 500,
        "symbols_requested": len(symbols),
        "symbols_completed": len(runs),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

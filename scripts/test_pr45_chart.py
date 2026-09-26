#!/usr/bin/env python3
"""PR45: PNG графіка SIGNAL_ENTRY (mplfinance) без LLM; =1000 депо."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_chart_png import DATA_UNAVAILABLE, chart_levels, render_signal_chart  # noqa: E402
from office_position_size import depo_usdt  # noqa: E402
from office_telegram_policy import EVENT_SIGNAL_ENTRY, may_send_proactive  # noqa: E402

ART = Path("/opt/cursor/artifacts")


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _synth(n: int = 40, start: float = 100.0) -> list:
    out = []
    t0 = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
    px = start
    for i in range(n):
        o = px
        h = o + 0.8
        l = o - 0.6
        cl = o + (0.25 if i % 3 else -0.15)
        px = cl
        out.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": cl,
                "volume": 12.0,
                "ts": (t0 + timedelta(minutes=15 * i)).isoformat(),
            }
        )
    return out


def main() -> int:
    empty = render_signal_chart(symbol="SOLUSDT", candles_m15=[], candles_h1=[])
    if empty.get("ok") or empty.get("data_status") != DATA_UNAVAILABLE:
        return _fail(f"empty candles must DATA_UNAVAILABLE, got {empty}")
    print("OK empty → DATA_UNAVAILABLE")

    few = render_signal_chart(symbol="SOLUSDT", candles_m15=_synth(3), candles_h1=_synth(2))
    if few.get("ok"):
        return _fail("too few candles must not draw")
    print("OK few candles → no PNG")

    lv = chart_levels(
        sl=97.2,
        tp1=102.5,
        tp2=104.0,
        tp3=106.0,
        entry_low=99.4,
        entry_high=100.1,
        sc_low=98.0,
        sc_high=101.5,
        sweep=97.8,
        asian_high=101.2,
        asian_low=98.6,
        mo=99.0,
        bucket_60=99.6,
        bucket_40=99.2,
    )
    art_dir = ART if ART.is_dir() else Path(tempfile.gettempdir())
    art_dir.mkdir(parents=True, exist_ok=True)
    out = art_dir / "pr45_signal_chart.png"
    drawn = render_signal_chart(
        symbol="SOLUSDT",
        candles_m15=_synth(64),
        candles_h1=_synth(32, start=99.5),
        levels=lv,
        direction="LONG",
        out_path=str(out),
    )
    if not drawn.get("ok"):
        return _fail(f"synth chart failed: {drawn}")
    if not os.path.isfile(drawn["path"]) or os.path.getsize(drawn["path"]) < 1000:
        return _fail(f"PNG too small: {drawn}")
    print(f"OK PNG {drawn['path']} {os.path.getsize(drawn['path'])} bytes")

    src = Path(__file__).read_text(encoding="utf-8")
    chart_src = (ROOT / "office_chart_png.py").read_text(encoding="utf-8")
    if "openai" in chart_src.lower() or "anthropic" in chart_src.lower() or "llm" in chart_src.lower():
        # docstring mentions без LLM — allowed; runtime call not allowed
        if "anthropic" in chart_src.lower() or "messages.create" in chart_src:
            return _fail("chart must not call LLM")
    if not may_send_proactive(EVENT_SIGNAL_ENTRY):
        return _fail("SIGNAL_ENTRY must stay proactive-allowed")

    os.environ["OFFICE_DEPO_USDT"] = "=1000"
    d = depo_usdt()
    if d != 1000.0:
        return _fail(f"depo =1000 must parse as 1000, got {d}")
    print("OK OFFICE_DEPO_USDT=1000 with leading =")
    os.environ.pop("OFFICE_DEPO_USDT", None)
    return 0


if __name__ == "__main__":
    sys.exit(main())

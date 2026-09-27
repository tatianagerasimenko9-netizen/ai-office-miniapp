#!/usr/bin/env python3
"""DEMO/OFFLINE PNG Лева для затвердження дизайну. Не Live."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from office_chart_png import chart_levels, render_signal_chart  # noqa: E402
from office_desk_card import format_desk_card  # noqa: E402
from office_lev_authority import previous_to_new_link  # noqa: E402

ART = Path("/opt/cursor/artifacts")
ART.mkdir(parents=True, exist_ok=True)


def _bars(n: int, start: float, step: float, *, short: bool) -> list:
    out = []
    t0 = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
    px = start
    for i in range(n):
        drift = -step if short else step
        o = px
        c = px + drift * (0.4 if i % 3 else -0.2)
        h = max(o, c) + step * 0.6
        l = min(o, c) - step * 0.5
        out.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 10.0,
                "ts": (t0 + timedelta(minutes=15 * i)).isoformat(),
            }
        )
        px = c
    return out


def main() -> int:
    btc_link = previous_to_new_link(
        prev_direction="LONG",
        prev_status="HIT_SL",
        reason="ціна за стопом до входу",
        new_tf="H1",
        wait_for="відкат у зону і LTF",
        had_entry=False,
    )
    btc_txt = format_desk_card(
        symbol="BTCUSDT",
        direction="LONG",
        timeframe="H1",
        entry=84556.4,
        sl=84000.76,
        tp1=85564.25,
        tp2=86128.7,
        entry_low=84556.4,
        entry_high=84556.4,
        reentry=True,
        had_confirmed_entry=False,
        previous_link=btc_link,
        now_line="Зараз: поза угодою, чекаю відкат",
        confirm_wait="Чекаю відкат на M15",
        lev_note="DEMO/OFFLINE. Не Live. Не /position.",
        size={"size_usdt": 1522, "depo": 1000, "risk_pct": 0.01},
    )
    manta_txt = format_desk_card(
        symbol="MANTAUSDT",
        direction="SHORT",
        timeframe="M15",
        entry=0.070959,
        sl=0.072504,
        tp1=0.068619,
        entry_low=0.070471,
        entry_high=0.071447,
        now_line="Зараз: поза угодою, чекаю M5",
        confirm_wait="Чекаю на M5: реакція в зоні, не вхід",
        lev_note="DEMO/OFFLINE. Desk SHORT. Не /position.",
        grade="B",
        setup_type="DUMP",
        size={"size_usdt": 400, "depo": 1000, "risk_pct": 0.01},
    )
    btc_bars = _bars(48, 85120, 18, short=True)
    manta_bars = _bars(48, 0.07135, 0.000012, short=False)
    btc_png = render_signal_chart(
        symbol="BTCUSDT",
        candles_m15=btc_bars,
        candles_h1=btc_bars,
        direction="LONG",
        levels=chart_levels(
            sl=84000.76,
            tp1=85564.25,
            tp2=86128.7,
            entry_low=84556.4,
            entry_high=84556.4,
            last_price=btc_bars[-1]["close"],
            status="WATCHING · DEMO",
            footer="Чому: новий LONG після скасування до входу. Чого чекаю: відкат. "
            "Що скасує: закриття за SL. Що з попереднім: скасовано до входу. DEMO/OFFLINE.",
        ),
        out_path=str(ART / "lev-card-btc-long-watching-DEMO.png"),
    )
    manta_png = render_signal_chart(
        symbol="MANTAUSDT",
        candles_m15=manta_bars,
        candles_h1=manta_bars,
        direction="SHORT",
        levels=chart_levels(
            sl=0.072504,
            tp1=0.068619,
            entry_low=0.070471,
            entry_high=0.071447,
            last_price=manta_bars[-1]["close"],
            status="WATCHING · DEMO",
            footer="Чому: desk SHORT у зоні. Чого чекаю: M5 у зоні. "
            "Що скасує: закриття вище SL. Не /position. DEMO/OFFLINE.",
        ),
        out_path=str(ART / "lev-card-manta-short-watching-DEMO.png"),
    )
    (ART / "lev-card-btc-telegram-DEMO.txt").write_text(btc_txt, encoding="utf-8")
    (ART / "lev-card-manta-telegram-DEMO.txt").write_text(manta_txt, encoding="utf-8")
    print("BTC_PNG", btc_png)
    print("MANTA_PNG", manta_png)
    print("BTC_TXT\n", btc_txt)
    print("MANTA_TXT\n", manta_txt)
    if not btc_png.get("ok") or not manta_png.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

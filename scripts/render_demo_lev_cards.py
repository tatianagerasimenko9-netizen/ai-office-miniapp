#!/usr/bin/env python3
"""DEMO/OFFLINE PNG Лева для затвердження дизайну. Не Live. Не ринкова структура."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["OFFICE_DEPO_USDT"] = "1000"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from office_chart_png import chart_levels, render_signal_chart  # noqa: E402
from office_desk_card import _calc_entry_px, format_desk_card  # noqa: E402
from office_lev_authority import previous_to_new_link  # noqa: E402
from office_position_size import plan_position_size  # noqa: E402
from office_price_format import format_px  # noqa: E402

ART = Path("/opt/cursor/artifacts")
ART.mkdir(parents=True, exist_ok=True)


def _osc(n: int, mid: float, amp: float) -> list:
    """Коливання навколо mid — лише масштаб рівнів, не патерн."""
    out = []
    t0 = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
    for i in range(n):
        phase = (i % 7) - 3
        o = mid + amp * 0.15 * phase
        c = mid - amp * 0.12 * phase
        h = max(o, c) + amp * 0.35
        l = min(o, c) - amp * 0.35
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
    return out


def _edge_math(*, symbol: str, side: str, lo: float, hi: float, sl: float, tp1: float, depo: float = 1000.0) -> str:
    lines = [f"{symbol} {side} зона {format_px(lo, symbol)}–{format_px(hi, symbol)}"]
    for label, px in (("найгірший край", hi if side == "SHORT" else lo), ("протилежний край", lo if side == "SHORT" else hi)):
        sized = plan_position_size(entry=px, sl=sl, direction=side, depo=depo)
        stop_pct = sized.get("stop_pct")
        tp_pct = abs(tp1 - px) / abs(px) * 100.0
        lines.append(
            f"{label} {format_px(px, symbol)}: SL {stop_pct:.2f}% · TP1 {tp_pct:.2f}% · "
            f"обсяг {sized.get('size_usdt')} USDT · ризик {depo * float(sized.get('risk_pct') or 0.01):.0f}$ · ok={sized.get('ok')}"
        )
    calc = _calc_entry_px(direction=side, elo=lo, ehi=hi, entry=(lo + hi) / 2.0)
    lines.append(f"картка рахує від {format_px(calc, symbol)} (найгірший край, якщо зона ≥0.8%)")
    return "\n".join(lines)


def main() -> int:
    btc_link = previous_to_new_link(
        prev_direction="LONG",
        prev_status="HIT_SL",
        reason="ціна порушила рівень інвалідації сценарію",
        new_tf="H1",
        wait_for="відкат у зону і підтвердження на M15/M5",
        had_entry=False,
    )
    btc_txt = format_desk_card(
        symbol="BTCUSDT",
        direction="LONG",
        timeframe="H1",
        chart_tf="M15",
        entry=84556.4,
        sl=84000.76,
        tp1=85564.25,
        tp2=86128.7,
        entry_low=84556.4,
        entry_high=84556.4,
        reentry=True,
        had_confirmed_entry=False,
        previous_link=btc_link,
        confirm_wait="Чекаю відкату в зону 84 556.4 і підтвердження на M15/M5. Входу ще немає.",
        lev_note="DEMO/OFFLINE. Не Live. Не /position.",
        size={"size_usdt": 1522, "depo": 1000, "risk_pct": 0.01},
    )
    manta_lo, manta_hi = 0.070471, 0.071447
    manta_sl, manta_tp1 = 0.072504, 0.068619
    manta_calc = _calc_entry_px(direction="SHORT", elo=manta_lo, ehi=manta_hi, entry=0.070959)
    manta_sz = plan_position_size(entry=manta_calc, sl=manta_sl, direction="SHORT", depo=1000)
    manta_txt = format_desk_card(
        symbol="MANTAUSDT",
        direction="SHORT",
        timeframe="M15",
        chart_tf="M15",
        entry=0.070959,
        sl=manta_sl,
        tp1=manta_tp1,
        entry_low=manta_lo,
        entry_high=manta_hi,
        confirm_wait="Чекаю реакції M5 у зоні. Конкретну умову (SFP / BOS / закриття) Live не підтверджено — DATA_UNAVAILABLE. Входу ще немає.",
        lev_note="DEMO/OFFLINE. Desk SHORT. Не /position.",
        grade="B",
        setup_type="DUMP",
        size=manta_sz if manta_sz.get("ok") else None,
    )
    math_txt = _edge_math(
        symbol="MANTAUSDT",
        side="SHORT",
        lo=manta_lo,
        hi=manta_hi,
        sl=manta_sl,
        tp1=manta_tp1,
    )
    btc_bars = _osc(40, 84980, 220)
    manta_bars = _osc(40, 0.07096, 0.00038)
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
            scenario_tf="H1",
            chart_tf="M15",
            headline="BTCUSDT · LONG",
            wait_line="Чекаю відкату в зону. Входу ще немає.",
            prev_line="Попередній LONG скасовано до входу: ціна порушила рівень інвалідації сценарію.",
            why_line="Новий сценарій — окрема зона, підтвердження на M15/M5.",
            cancel_line="Що скасує: закриття за рівнем інвалідації.",
            calc_entry=84556.4,
            demo=True,
        ),
        out_path=str(ART / "lev_card_btc_h1_watching_v3b.png"),
    )
    manta_png = render_signal_chart(
        symbol="MANTAUSDT",
        candles_m15=manta_bars,
        candles_h1=manta_bars,
        direction="SHORT",
        levels=chart_levels(
            sl=manta_sl,
            tp1=manta_tp1,
            entry_low=manta_lo,
            entry_high=manta_hi,
            last_price=manta_bars[-1]["close"],
            status="WATCHING · DEMO",
            scenario_tf="M15",
            chart_tf="M15",
            headline="MANTAUSDT · SHORT",
            wait_line="Чекаю реакції M5 у зоні. Входу ще немає.",
            why_line="Зона 0.070471–0.071447 — місце спостереження, не дозвіл продавати.",
            cancel_line="Конкретну умову M5 Live не підтверджено (DATA_UNAVAILABLE).",
            calc_entry=manta_calc,
            demo=True,
        ),
        out_path=str(ART / "lev_card_manta_m15_watching_v3b.png"),
    )
    (ART / "lev_card_btc_telegram_v3b.txt").write_text(btc_txt, encoding="utf-8")
    (ART / "lev_card_manta_telegram_v3b.txt").write_text(manta_txt, encoding="utf-8")
    (ART / "lev_card_manta_zone_math_v3b.txt").write_text(math_txt, encoding="utf-8")
    print("BTC_PNG", btc_png)
    print("MANTA_PNG", manta_png)
    print("BTC_TXT\n", btc_txt)
    print("MANTA_TXT\n", manta_txt)
    print("MANTA_MATH\n", math_txt)
    if not btc_png.get("ok") or not manta_png.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

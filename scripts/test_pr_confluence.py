#!/usr/bin/env python3
"""Рушій збігів + універсальна картка: BTC/LONGXIA/AKE/BR, дедуп, PNG."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["OFFICE_DEPO_USDT"] = "1000"

from office_chart_png import chart_levels, render_signal_chart  # noqa: E402
from office_confluence import (  # noqa: E402
    cluster_zones,
    detect_ltf_confirms,
    evaluate_confluence,
    follow_setup,
    format_cancel_card,
    format_confirm_card,
    reset_live,
)
from office_desk_card import card_has_banned, format_desk_card, prepare_desk_send  # noqa: E402
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_signal_stats import MIN_GROUP, build_stats_report  # noqa: E402
from office_bridge import init_office_db, journal_close_trade, journal_open_office_signal  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402

ART = Path("/opt/cursor/artifacts")


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _c(o, h, l, cl, ts="", vol=10.0):
    return {"open": o, "high": h, "low": l, "close": cl, "volume": vol, "ts": ts}


def _cand(tag, lo, hi, tf="H1", label=""):
    return {"tag": tag, "lo": float(lo), "hi": float(hi), "tf": tf, "label": label or tag}


def _synth(n: int, start: float, step_min: int = 15) -> list:
    out = []
    t0 = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
    px = start
    for i in range(n):
        o = px
        h = o * 1.004
        l = o * 0.996
        cl = o * (1.001 if i % 3 else 0.999)
        px = cl
        out.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": cl,
                "volume": 12.0,
                "ts": (t0 + timedelta(minutes=step_min * i)).isoformat(),
            }
        )
    return out


def _range_then_break() -> list:
    """H1 боковик ~1% і закріплення вище — BREAK, не вхід."""
    t0 = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(16):
        o = 100.2 if i % 2 == 0 else 101.6
        rows.append(
            _c(
                o,
                101.8,
                100.05,
                101.1 if i % 2 else 100.4,
                (t0 + timedelta(hours=i)).isoformat(),
            )
        )
    rows.append(_c(101.9, 103.4, 101.7, 103.1, (t0 + timedelta(hours=16)).isoformat()))
    rows.append(_c(103.0, 103.6, 102.8, 103.4, (t0 + timedelta(hours=17)).isoformat()))
    return rows


def _br_cands():
    return [
        _cand("sc_ote", 0.922, 0.928, "M15", "сильна свічка M15"),
        _cand("ob", 0.922, 0.928, "H1", "OB H1"),
        _cand("fib_h4", 0.922, 0.928, "H4", "Фібо 0.705 H4"),
        _cand("sweep", 0.925, 0.928, "M15", "свіп хаю Азії"),
    ]


def _btc_cands():
    # Відкат ~83.2–83.8k, не поточні 84 870.
    return [
        _cand("sc_ote", 83200, 83800, "M15", "сильна свічка M15"),
        _cand("ob", 83150, 83750, "H1", "OB H1"),
        _cand("fib_h4", 83000, 83900, "H4", "Фібо 0.618–0.786 H4"),
        _cand("range_edge", 83680, 83820, "H1", "межа боковика"),
    ]


def _long_cands(lo=0.0324, hi=0.0329):
    return [
        _cand("sc_ote", lo, hi, "M15", "сильна свічка M15"),
        _cand("ob", lo * 0.999, hi * 1.001, "H1", "OB H1"),
        _cand("dw", lo, hi, "D1", "рівень D"),
    ]


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0 or SIGNAL_THRESHOLD != 85 or MIN_RR < 1.5:
        return _fail("atr/edge/rr frozen")

    reset_live()
    weak = evaluate_confluence(
        symbol="AAAUSDT",
        direction="SHORT",
        timeframe="M15",
        candidates=[_cand("sc_ote", 1.0, 1.01, "M15", "сильна свічка M15")],
        price=1.04,
    )
    if weak.get("send_card") or weak.get("reason") != "менше 2 збігів":
        return _fail(f"1 tag must db-only {weak}")
    print("OK <2 збігів → без картки")

    reset_live()
    grade_b = evaluate_confluence(
        symbol="BBBUSDT",
        direction="SHORT",
        timeframe="M15",
        candidates=[
            _cand("sc_ote", 1.00, 1.01, "M15", "сильна свічка M15"),
            _cand("ob", 1.002, 1.012, "H1", "OB H1"),
        ],
        price=1.03,
    )
    if not grade_b.get("send_card") or grade_b.get("grade") != "B":
        return _fail(f"2 tags → B {grade_b}")
    reset_live()
    grade_a = evaluate_confluence(
        symbol="CCCUSDT",
        direction="SHORT",
        timeframe="M15",
        candidates=_br_cands(),
        price=0.910,
    )
    if not grade_a.get("send_card") or grade_a.get("grade") != "A":
        return _fail(f"4 tags → A {grade_a}")
    print("OK сила B/A")

    reset_live()
    brk = evaluate_confluence(
        symbol="ETHUSDT",
        direction="LONG",
        timeframe="H1",
        candles_h1=_range_then_break(),
        candles_m15=_range_then_break(),
        price=103.4,
    )
    if brk.get("send_card") or not brk.get("is_range_break"):
        return _fail(f"range BREAK must not card {brk}")
    print("OK пробій ренджу — подія, не картка")

    reset_live()
    px_now = 84870.0
    sent = 0
    sent_prep = None
    for i in range(4):
        prep = prepare_desk_send(
            symbol="BTCUSDT",
            direction="SHORT",
            timeframe="H1",
            entry=px_now,
            sl=85900.0,
            tp1=80000.0,
            atr_h1=900.0,
            score=12,
            min_score=10,
            setup_type="РАДАР",
            price=px_now,
            candidates=_btc_cands(),
            now_ts=1_000_000.0 + i,
        )
        if prep.get("send"):
            sent += 1
            sent_prep = prep
    if sent != 1 or not sent_prep:
        return _fail(f"BTC 4 dupes → {sent} cards")
    e = float(sent_prep.get("entry") or 0)
    if abs(e - px_now) < 200:
        return _fail(f"BTC entry must be pullback zone not {px_now}, got {e}")
    if not (83000 <= e <= 84000):
        return _fail(f"BTC zone mid {e}")
    txt_btc = str(sent_prep.get("text") or "")
    if "84 870" in txt_btc:
        return _fail(f"BTC card has current px {txt_btc}")
    if "range" in txt_btc.lower():
        return _fail(f"BTC card has range {txt_btc}")
    print(f"OK BTC 4→1 картка, вхід {e:.0f} не 84870")

    reset_live()
    br_gate = prepare_desk_send(
        symbol="BRUSDT",
        direction="SHORT",
        timeframe="M15",
        entry=0.910,
        sl=0.940,
        tp1=0.896,
        tp2=0.890,
        atr_h1=0.012,
        score=12,
        min_score=10,
        setup_type="DUMP",
        price=0.910,
        candidates=_br_cands(),
    )
    if not br_gate.get("send"):
        return _fail(f"BR send {br_gate.get('reason')} {br_gate}")
    br_txt = format_desk_card(
        symbol="BRUSDT",
        direction="SHORT",
        timeframe="M15",
        entry=0.925,
        sl=0.940,
        tp1=0.901,
        tp2=0.890,
        setup_type="DUMP",
        grade="A",
        entry_low=0.922,
        entry_high=0.928,
        zone_line="сильна свічка M15 + OB H1 + Фібо 0.705 H4 + свіп хаю Азії",
        confirm_wait="Чекаю на M5: подвійна вершина або SFP у зоні",
        now_line="Зараз: поза угодою, чекаю відкат",
        size={"size_usdt": 625, "depo": 1000, "risk_pct": 0.01},
    )
    for bit in (
        "🔴 SHORT · BRUSDT · сценарій M15",
        "Шорт на відкаті · сила A",
        "🎯 Вхід · 0.922–0.928",
        "❌ Стоп · 0.94  (−1.6%)",
        "✅ TP1 · 0.901  (+2.6%)",
        "✅ TP2 · 0.89  (+3.8%)",
        "Структура: сильна свічка M15 + OB H1 + Фібо 0.705 H4 + свіп хаю Азії",
        "Чекаю на M5: подвійна вершина або SFP у зоні",
        "WATCHING · ВХОДУ НЕМАЄ",
        "План після підтвердження",
        "При TP1 — частина + стоп у беззбиток",
        "Плановий обсяг 625 USDT · ризик 10$",
    ):
        if bit not in br_txt:
            return _fail(f"BR missing {bit!r} in {br_txt}")
    if "range" in br_txt.lower() or card_has_banned(br_txt):
        return _fail(f"BR banned {br_txt}")
    print("OK BR SHORT картка")
    print(br_txt)

    reset_live()
    ake = prepare_desk_send(
        symbol="AKEUSDT",
        direction="LONG",
        timeframe="M15",
        entry=0.034,
        sl=0.0318,
        tp1=0.03475,
        tp2=0.03529,
        atr_h1=0.0008,
        score=12,
        min_score=10,
        setup_type="Відкат у сильну свічку",
        price=0.0335,
        candidates=_long_cands(0.0324, 0.0329),
    )
    if not ake.get("send"):
        return _fail(f"AKE {ake.get('reason')} {ake}")
    ake_txt = str(ake.get("text") or "")
    if "🟢 LONG · AKEUSDT · сценарій M15" not in ake_txt or "сила A" not in ake_txt:
        return _fail(ake_txt)
    if "🎯 Вхід · " not in ake_txt:
        return _fail(ake_txt)
    print("OK AKE LONG")

    reset_live()
    lx = prepare_desk_send(
        symbol="LONGXIAUSDT",
        direction="LONG",
        timeframe="M15",
        entry=0.12,
        sl=0.108,
        tp1=0.128,
        tp2=0.135,
        atr_h1=0.004,
        score=12,
        min_score=10,
        setup_type="PUMP",
        price=0.118,
        candidates=_long_cands(0.112, 0.118),
    )
    if not lx.get("send"):
        return _fail(f"LONGXIA {lx.get('reason')}")
    lx_txt = str(lx.get("text") or "")
    if "🟢 LONG · LONGXIAUSDT · сценарій M15" not in lx_txt or "Лонг на відкаті" not in lx_txt:
        return _fail(lx_txt)
    if "range" in lx_txt.lower():
        return _fail(lx_txt)
    print("OK LONGXIA LONG")

    conf_txt = format_confirm_card(
        symbol="BRUSDT",
        direction="SHORT",
        price=0.924,
        detail="подвійна вершина M5 + закриття нижче 0.922",
    )
    if conf_txt != "✅ BRUSDT SHORT · сценарій підтверджено (не /position) · 0.924\nПідтвердження: подвійна вершина M5 + закриття нижче 0.922":
        return _fail(f"confirm {conf_txt!r}")
    canc = format_cancel_card(symbol="BRUSDT", direction="SHORT", reason="ціна за стопом до входу")
    if "❌ BRUSDT SHORT · скасовано — ціна за стопом до входу" not in canc:
        return _fail(canc)
    print("OK confirm/cancel")

    # SFP SHORT у зоні 0.922–0.928
    ltf = [
        _c(0.920, 0.923, 0.918, 0.921),
        _c(0.921, 0.926, 0.920, 0.925),
        _c(0.925, 0.927, 0.923, 0.924),
        _c(0.924, 0.931, 0.921, 0.923),  # тінь вище зони, закриття всередині
    ]
    hits = detect_ltf_confirms(direction="SHORT", candles_ltf=ltf, zone_lo=0.922, zone_hi=0.928)
    if "sfp" not in hits:
        return _fail(f"sfp {hits}")
    fu = follow_setup(
        setup={
            "direction": "SHORT",
            "sl": 0.940,
            "zone_lo": 0.922,
            "zone_hi": 0.928,
            "ts": 1.0,
            "timeframe": "M15",
        },
        price=0.923,
        candles_ltf=ltf,
        now_ts=2.0,
    )
    if fu.get("action") != "confirm":
        return _fail(f"follow confirm {fu}")
    to = follow_setup(
        setup={
            "direction": "SHORT",
            "sl": 0.940,
            "zone_lo": 0.922,
            "zone_hi": 0.928,
            "ts": 1.0,
            "timeframe": "M15",
        },
        price=0.925,
        candles_ltf=ltf,
        now_ts=1.0 + 3 * 3600 + 10,
    )
    if to.get("action") != "cancel" or "таймаут" not in str(to.get("reason") or ""):
        return _fail(f"ttl {to}")
    sl_hit = follow_setup(
        setup={
            "direction": "SHORT",
            "sl": 0.930,
            "zone_lo": 0.922,
            "zone_hi": 0.928,
            "ts": 1.0,
            "timeframe": "M15",
        },
        price=0.935,
        candles_ltf=[_c(0.93, 0.936, 0.929, 0.935)],
        now_ts=10.0,
    )
    if sl_hit.get("action") != "cancel":
        return _fail(f"sl cancel {sl_hit}")
    print("OK follow confirm/timeout/SL")

    clus = cluster_zones(_btc_cands())
    if len(clus) != 1 or int(clus[0]["n"]) < 3:
        return _fail(f"cluster {clus}")

    art = ART if ART.is_dir() else Path(tempfile.gettempdir())
    art.mkdir(parents=True, exist_ok=True)
    (art / "confluence_br_short.txt").write_text(br_txt, encoding="utf-8")
    (art / "confluence_ake_long.txt").write_text(ake_txt, encoding="utf-8")
    (art / "confluence_longxia_long.txt").write_text(lx_txt, encoding="utf-8")
    (art / "confluence_btc_short.txt").write_text(txt_btc, encoding="utf-8")

    lv_s = chart_levels(
        sl=0.940,
        tp1=0.901,
        tp2=0.890,
        entry_low=0.922,
        entry_high=0.928,
        last_price=0.910,
        status="сила A",
    )
    png_s = art / "confluence_br_short.png"
    drawn_s = render_signal_chart(
        symbol="BRUSDT",
        candles_m15=_synth(40, 0.915),
        candles_h1=_synth(24, 0.92, 60),
        levels=lv_s,
        direction="SHORT",
        out_path=str(png_s),
    )
    lv_l = chart_levels(
        sl=0.0318,
        tp1=0.03475,
        tp2=0.03529,
        entry_low=0.0324,
        entry_high=0.0329,
        last_price=0.0335,
        status="сила A",
    )
    png_l = art / "confluence_ake_long.png"
    drawn_l = render_signal_chart(
        symbol="AKEUSDT",
        candles_m15=_synth(40, 0.033),
        candles_h1=_synth(24, 0.033, 60),
        levels=lv_l,
        direction="LONG",
        out_path=str(png_l),
    )
    if not drawn_s.get("ok") or not png_s.is_file() or png_s.stat().st_size < 64:
        return _fail(f"SHORT png {drawn_s}")
    if not drawn_l.get("ok") or not png_l.is_file() or png_l.stat().st_size < 64:
        return _fail(f"LONG png {drawn_l}")
    print(f"OK PNG SHORT {png_s} LONG {png_l}")

    fd, db = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_office_db(db)
        for i in range(MIN_GROUP):
            extra = {
                "confluence_tags": ["sc_ote", "ob", "fib_h4"],
                "confirm_tags": ["sfp", "double_top"],
                "grade": "A",
                "session": "ASIA",
                "mfe_pct": 4.0,
                "mae_pct": 0.4,
            }
            tid = journal_open_office_signal(
                db,
                signal_id=f"conf-{i}",
                symbol="BRUSDT",
                direction="SHORT",
                entry_price=0.925,
                stop_loss=0.940,
                take_profit=0.901,
                timeframe="M15",
                setup_note="DUMP",
                extra=extra,
            )
            journal_close_trade(db, trade_id=tid, outcome="WIN", exit_price=0.901, pnl_pct=2.6)
        stats = build_stats_report(db)
        msg = str(stats.get("message") or "")
        if "Збіги:" not in msg or "sc_ote+ob+fib_h4" not in msg:
            return _fail(f"stats confluence {msg}")
        if "sfp" not in msg:
            return _fail(f"stats confirm {msg}")
        print("OK /stats збіги")
    finally:
        try:
            os.unlink(db)
        except OSError:
            pass

    print("OK: test_pr_confluence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

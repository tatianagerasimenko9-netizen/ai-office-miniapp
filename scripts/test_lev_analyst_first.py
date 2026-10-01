#!/usr/bin/env python3
"""Лев-аналітик спочатку: індикатори не створюють ENTER. Історичний BTC-кейс a–ґ."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["OFFICE_DEPO_USDT"] = "1000"

from office_atr_policy import GERCHIK_TREND_ENTRY_BLOCK_PCT  # noqa: E402
from office_confluence import reset_live  # noqa: E402
from office_desk_card import format_desk_card, min_tp1_pct  # noqa: E402
from office_lev_verdict import (  # noqa: E402
    ACTION_SEND,
    ACTION_SKIP,
    ACTION_WAIT,
    ACTION_WATCHING,
    STANCE_CONFIRM,
    STANCE_CONTRADICT,
    STANCE_NEUTRAL,
    STANCE_NOT_CONNECTED,
    collect_indicator_stances,
    draft_lev_scenario,
    finalize_lev,
    indicator_stance,
    lev_cycle,
)
from office_market_data import SIGNAL_THRESHOLD  # noqa: E402
from office_pump_dump import evaluate_pump_dump  # noqa: E402
from office_radar import MIN_RR  # noqa: E402
from office_regression_channel import regression_channel  # noqa: E402
from office_zone_alert import ATR_DAY_USED_ENTRY_BLOCK_PCT  # noqa: E402

ART = Path("/opt/cursor/artifacts")


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def _cand(tag, lo, hi, tf="H1", label=""):
    return {"tag": tag, "lo": float(lo), "hi": float(hi), "tf": tf, "label": label or tag}


def _c(o, h, l, cl, vol=12.0):
    return {"open": o, "high": h, "low": l, "close": cl, "volume": vol}


def _btc_long_cands():
    # Відкат ~83.2–83.8k при споті ~84 870 — зона Лева, не chase.
    return [
        _cand("sc_ote", 83200, 83800, "M15", "сильна свічка M15"),
        _cand("ob", 83150, 83750, "H1", "OB H1"),
        _cand("fib_h4", 83000, 83900, "H4", "Фібо 0.618–0.786 H4"),
        _cand("breaker", 83300, 83650, "H1", "breaker H1"),
    ]


def _btc_short_cands_weak():
    return [_cand("ob", 85100, 85600, "H1", "OB H1")]


def _neutral_stances(lev_dir: str) -> dict:
    return {
        "pump_dump": indicator_stance(
            lev_direction=lev_dir, connected=True, signal=False, reason="немає PUMP/DUMP"
        ),
        "ict_hunter": indicator_stance(
            lev_direction=lev_dir, connected=True, signal=False, reason="нижче порога"
        ),
        "channel": indicator_stance(
            lev_direction=lev_dir, connected=False, signal=False, reason="NOT_CONNECTED"
        ),
        "pine_alerts": {
            "stance": STANCE_NOT_CONNECTED,
            "connected": False,
            "creates_enter": False,
            "reason": "немає історичних TradingView alerts",
        },
    }


def _bars_flat(n: int, px: float) -> list:
    rows = []
    for i in range(n):
        rows.append(_c(px, px * 1.001, px * 0.999, px, vol=10.0 + i))
    return rows


def main() -> int:
    if ATR_DAY_USED_ENTRY_BLOCK_PCT != 90.0:
        return _fail("ATR 90 змінено")
    if GERCHIK_TREND_ENTRY_BLOCK_PCT != 80.0:
        return _fail("ATR 80 змінено")
    if SIGNAL_THRESHOLD != 85:
        return _fail("Edge 85 змінено")
    if MIN_RR < 1.5:
        return _fail("MIN_RR змінено")
    if min_tp1_pct("BTCUSDT") != 1.2 or min_tp1_pct("SOLUSDT") != 3.0:
        return _fail("TP1-фільтри змінено")
    print("OK frozen ATR 80/90, Edge 85, MIN_RR 1.5, TP1 1.2/3")

    st = indicator_stance(
        lev_direction="LONG",
        indicator_direction="SHORT",
        connected=True,
        signal=True,
    )
    if st["stance"] != STANCE_CONTRADICT or st["creates_enter"]:
        return _fail(f"contradict {st}")
    st2 = indicator_stance(lev_direction="LONG", connected=False, signal=True, indicator_direction="LONG")
    if st2["stance"] != STANCE_NOT_CONNECTED or st2["creates_enter"]:
        return _fail(f"not connected {st2}")
    print("OK stance CONFIRM/CONTRADICT/NOT_CONNECTED, creates_enter=False")

    reset_live()
    ch = regression_channel(_bars_flat(20, 100.0))
    if ch.get("ok") or ch.get("signal") or ch.get("creates_enter"):
        return _fail(f"short channel must NOT_CONNECTED {ch}")
    print("OK канал без 100 барів — не сигнал")

    # Hunter/pump самі не відкривають ENTER.
    reset_live()
    empty_draft = {
        "send_card": False,
        "reason": "немає збігів",
        "direction": "LONG",
        "confluence": {"n": 0, "tags": []},
        "alternative": {"direction": "SHORT", "eligible": False},
        "entry": None,
        "sl": None,
        "tp1": None,
        "liquidity": {},
        "atr": {"gerchik_entry_blocked": False, "t0_entry_blocked": False},
        "rr": None,
    }
    hunt_fire = {
        "pump_dump": indicator_stance(
            lev_direction="LONG", connected=True, signal="PUMP", indicator_direction="LONG"
        ),
        "ict_hunter": indicator_stance(
            lev_direction="LONG", connected=True, signal=True, indicator_direction="LONG"
        ),
        "channel": indicator_stance(
            lev_direction="LONG", connected=True, signal=True, indicator_direction="LONG"
        ),
    }
    fin = finalize_lev(empty_draft, hunt_fire, hunter_only_enter=True)
    if fin.get("send") or fin.get("action") not in (ACTION_SKIP, ACTION_WATCHING):
        return _fail(f"three indicators must not ENTER {fin}")
    if fin.get("creates_enter_from_indicator"):
        return _fail("creates_enter_from_indicator")
    print("OK три індикатори збіглись без сетапу Лева → не ENTER")

    reset_live()
    draft = draft_lev_scenario(
        symbol="BTCUSDT",
        timeframe="H1",
        price=84870.0,
        atr_h1=900.0,
        day_used_pct=40.0,
        candidates_long=_btc_long_cands(),
        candidates_short=_btc_short_cands_weak(),
        market_context={
            "data_status": "PARTIAL",
            "btc": "спот 84870, зона відкату нижче",
            "note": "Nasdaq/DXY/золото/нафта не підключені — кореляцій не вигадую",
        },
    )
    if draft.get("direction") != "LONG" or not draft.get("send_card"):
        return _fail(f"Lev LONG expected {draft.get('direction')} {draft.get('reason')}")
    if not (83000 <= float(draft.get("entry") or 0) <= 84000):
        return _fail(f"Lev entry chase? {draft.get('entry')}")
    if float(draft.get("entry") or 0) == 84870.0:
        return _fail("вхід = спот")
    alt = draft.get("alternative") or {}
    if alt.get("direction") != "SHORT":
        return _fail(f"alt {alt}")
    sl_before = draft.get("sl")
    print(f"OK Lev draft LONG entry={draft.get('entry')} sl={sl_before} alt=SHORT")

    missing = {
        "pump_dump": indicator_stance(lev_direction="LONG", connected=False, signal=False),
        "ict_hunter": indicator_stance(lev_direction="LONG", connected=False, signal=False),
        "channel": indicator_stance(lev_direction="LONG", connected=False, signal=False),
        "pine_alerts": {"stance": STANCE_NOT_CONNECTED, "connected": False, "creates_enter": False},
    }
    ok_miss = finalize_lev(draft, missing)
    if not ok_miss.get("send") or ok_miss.get("action") != ACTION_SEND:
        return _fail(f"missing indicators must not stop Lev {ok_miss}")
    print("OK відсутність індикаторів не зупиняє сетап Лева")

    # Pump/Hunter вимкнено (office_indicator_gate) — суперечність від активного індикатора (канал) і далі веде до WAIT.
    contra = dict(_neutral_stances("LONG"))
    contra["channel"] = indicator_stance(
        lev_direction="LONG",
        connected=True,
        signal=True,
        indicator_direction="SHORT",
        reason="канал: ціна біля верхньої межі",
    )
    wait = finalize_lev(draft, contra)
    if wait.get("send") or wait.get("action") != ACTION_WAIT:
        return _fail(f"contradict must WAIT {wait}")
    if wait.get("direction") != "LONG":
        return _fail("підігнав напрям під індикатор")
    if wait.get("sl") != sl_before:
        return _fail("стоп змінено через індикатор")
    if not wait.get("continue_scan"):
        return _fail("після WAIT сканер має продовжувати")
    print("OK CONTRADICT → WAIT, напрям/стоп Лева не змінено")

    atr_skip = dict(draft)
    atr_skip["atr"] = {
        "gerchik_entry_blocked": True,
        "t0_entry_blocked": False,
        "label": "ATR day_used 81% > 80%",
    }
    sk = finalize_lev(atr_skip, _neutral_stances("LONG"))
    if sk.get("send") or not sk.get("continue_scan"):
        return _fail(f"ATR80 skip+continue {sk}")
    print("OK ATR 80 — SKIP входу, пошук триває")

    # --- Історичний BTC-кейс a–ґ ---
    reset_live()
    px = 84870.0
    # Синтетичні M15/H1 навколо споту — порт Pump з OHLCV, не TV alert.
    m15 = _bars_flat(30, px)
    h1 = _bars_flat(30, px)
    d1 = [
        _c(83000, 84200, 82800, 84000, vol=100),
        _c(84000, 85100, 83800, px, vol=110),
    ]
    pd_real = evaluate_pump_dump(candles=m15, daily=d1)
    collected = collect_indicator_stances(
        lev_direction="LONG",
        price=px,
        candles_m15=m15,
        candles_h1=h1,
        candles_d1=d1,
        pine_alerts=None,
    )
    cycle = lev_cycle(
        symbol="BTCUSDT",
        price=px,
        timeframe="H1",
        candles_m15=m15,
        candles_h1=h1,
        atr_h1=900.0,
        day_used_pct=35.0,
        candidates_long=_btc_long_cands(),
        candidates_short=_btc_short_cands_weak(),
        market_context={
            "btc_spot": px,
            "nasdaq": "DATA_UNAVAILABLE",
            "dxy": "DATA_UNAVAILABLE",
            "gold": "DATA_UNAVAILABLE",
            "oil": "DATA_UNAVAILABLE",
            "liquidations": "forceOrder не є прогнозною heatmap",
        },
        stances=collected,
    )
    a_without = draft_lev_scenario(
        symbol="BTCUSDT",
        timeframe="H1",
        price=px,
        atr_h1=900.0,
        day_used_pct=35.0,
        candidates_long=_btc_long_cands(),
        candidates_short=_btc_short_cands_weak(),
    )
    entry_changed = a_without.get("entry") != cycle.get("entry")
    sl_changed = a_without.get("sl") != cycle.get("sl")
    decision_changed = bool(a_without.get("send_card")) != bool(cycle.get("send"))
    # Якщо індикатори NEUTRAL/NOT_CONNECTED — рішення Лева SEND лишається.
    pd_stance = (collected.get("pump_dump") or {}).get("stance")
    ht_stance = (collected.get("ict_hunter") or {}).get("stance")
    ch_stance = (collected.get("channel") or {}).get("stance")
    if pd_stance not in (STANCE_NEUTRAL, STANCE_NOT_CONNECTED, STANCE_CONFIRM, STANCE_CONTRADICT):
        return _fail(f"pump stance {pd_stance}")
    if collected["pump_dump"].get("creates_enter") or collected["ict_hunter"].get("creates_enter"):
        return _fail("indicator creates_enter")
    if collected["channel"].get("creates_enter"):
        return _fail("channel enter")
    if (collected.get("pine_alerts") or {}).get("stance") != STANCE_NOT_CONNECTED:
        return _fail("pine alerts should be NOT_CONNECTED")

    txt = format_desk_card(
        symbol="BTCUSDT",
        direction="LONG",
        timeframe="H1",
        entry=cycle.get("entry"),
        sl=cycle.get("sl"),
        tp1=cycle.get("tp1"),
        setup_type="ЛЕВ",
        grade=str((cycle.get("confluence") or {}).get("grade") or "A"),
        entry_low=a_without.get("zone_lo"),
        entry_high=a_without.get("zone_hi"),
        zone_line=str((cycle.get("confluence") or {}).get("zone_line") or ""),
        now_line="Зараз: поза угодою, чекаю відкат",
        lev_note=str(cycle.get("lev_note") or ""),
        size={"size_usdt": 400, "depo": 1000, "risk_pct": 0.01},
    )
    for banned in ("PUMP", "DUMP", "HUNTER", "Hunter", "linreg", "forceOrder"):
        if banned in txt:
            return _fail(f"картка з міткою індикатора {banned}: {txt}")
    if "Лев:" not in txt:
        return _fail(f"немає висновку Лева {txt}")
    print("OK картка — висновок Лева, без міток індикаторів")

    case = {
        "symbol": "BTCUSDT",
        "spot": px,
        "a_lev_without_indicators": {
            "direction": a_without.get("direction"),
            "send_card": a_without.get("send_card"),
            "entry": a_without.get("entry"),
            "sl": a_without.get("sl"),
            "tp1": a_without.get("tp1"),
            "rr": a_without.get("rr"),
            "zone_lo": a_without.get("zone_lo"),
            "zone_hi": a_without.get("zone_hi"),
            "reason": a_without.get("reason"),
            "tags": (a_without.get("confluence") or {}).get("tags"),
        },
        "b_indicators": {
            "pump_dump": {
                "stance": pd_stance,
                "ohlcv_port_signal": pd_real.get("signal"),
                "total_l": pd_real.get("total_l"),
                "total_s": pd_real.get("total_s"),
                "creates_enter": False,
            },
            "ict_hunter": {
                "stance": ht_stance,
                "ohlcv_port": collected.get("raw", {}).get("ict_hunter", {}).get("signal"),
                "score": collected.get("raw", {}).get("ict_hunter", {}).get("score"),
                "patterns": collected.get("raw", {}).get("ict_hunter", {}).get("patterns"),
                "creates_enter": False,
            },
            "channel": {
                "stance": ch_stance,
                "ok": (collected.get("raw") or {}).get("channel", {}).get("ok"),
                "signal": False,
                "creates_enter": False,
            },
            "pine_alerts": collected.get("pine_alerts"),
        },
        "c_entry_sl_decision": {
            "entry_changed": entry_changed,
            "sl_changed": sl_changed,
            "decision_changed": decision_changed,
            "action": cycle.get("action"),
            "send": cycle.get("send"),
            "entry": cycle.get("entry"),
            "sl": cycle.get("sl"),
        },
        "d_alternative": cycle.get("alternative"),
        "e_cannot_verify_without_pine": [
            "історичні TradingView alerts Pump and Dump Hunter V2",
            "історичні alerts ICT SMC Hunter V9 Sync (час сигналу на графіку)",
            "прогнозна карта ліквідацій (forceOrder ≠ heatmap)",
            "живі Nasdaq/DXY/золото/нафта як причина напряму BTC без джерела",
        ],
        "card_excerpt": txt,
        "lev_note": cycle.get("lev_note"),
    }
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "lev_btc_case.json").write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    md = [
        "# BTC історичний кейс: Лев спочатку",
        "",
        "## (а) Власний висновок Лева БЕЗ індикаторів",
        f"- Напрямок: **{case['a_lev_without_indicators']['direction']}**",
        f"- Картка сетапу: {case['a_lev_without_indicators']['send_card']}",
        f"- Зона: {case['a_lev_without_indicators']['zone_lo']}–{case['a_lev_without_indicators']['zone_hi']}",
        f"- Вхід (середина зони, не спот {px}): {case['a_lev_without_indicators']['entry']}",
        f"- Стоп структурний: {case['a_lev_without_indicators']['sl']}",
        f"- TP1 при RR {MIN_RR}: {case['a_lev_without_indicators']['tp1']}",
        f"- Теги структури: {case['a_lev_without_indicators']['tags']}",
        "",
        "## (б) Що додав кожен індикатор (реальний OHLCV-порт, не імітація балів)",
        f"- Pump and Dump Hunter V2: stance={pd_stance}, signal порту={pd_real.get('signal')}, L={pd_real.get('total_l')} S={pd_real.get('total_s')}. ENTER не створює.",
        f"- ICT SMC Hunter V9: stance={ht_stance}, signal={case['b_indicators']['ict_hunter']['ohlcv_port']}, score={case['b_indicators']['ict_hunter']['score']}. ENTER не створює.",
        f"- Канал: stance={ch_stance}, ok={case['b_indicators']['channel']['ok']}, signal завжди False.",
        f"- TV alerts: {case['b_indicators']['pine_alerts']}",
        "",
        "## (в) Чи змінилось рішення про вхід і стоп",
        f"- entry_changed={entry_changed}, sl_changed={sl_changed}, decision_changed={decision_changed}",
        f"- Дія після індикаторів: {cycle.get('action')} send={cycle.get('send')}",
        "",
        "## (г) Альтернативний сценарій",
        json.dumps(case["d_alternative"], ensure_ascii=False),
        "",
        "## (ґ) Що неможливо перевірити без Pine-коду або історичних alerts",
        *[f"- {x}" for x in case["e_cannot_verify_without_pine"]],
        "",
        "## Картка",
        "```",
        txt,
        "```",
        "",
    ]
    (ART / "lev_btc_case.md").write_text("\n".join(md), encoding="utf-8")
    print("OK BTC case a–ґ записано")
    print(txt)

    if cycle.get("action") == ACTION_WAIT and cycle.get("direction") != "LONG":
        return _fail("WAIT змінив напрям")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

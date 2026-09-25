#!/usr/bin/env python3
"""Вечірнє ДЗ: факти, геометрія FVG, L/S, RR, без вигаданих рівнів і SKIP-як-угод."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from office_evening_homework import (  # noqa: E402
    build_homework_facts,
    format_dom_measured,
    homework_card_text,
    interpret_long_short,
    lev_system_prompt,
    recent_setups_note,
    rr_for_entry_range,
    split_telegram_chunks,
    unexplained_levels,
    validate_card_text,
    zone_side,
)
from office_radar import RADAR_SYMBOLS  # noqa: E402
from office_btc_liquidations import CREATES_ENTER  # noqa: E402


def _fail(msg: str) -> int:
    print(f"FAIL: {msg}")
    return 1


def main() -> int:
    if RADAR_SYMBOLS != ("BTCUSDT",):
        return _fail("T6 radar symbols must stay BTC only")
    if CREATES_ENTER:
        return _fail("T7 must not create ENTER")

    ls = interpret_long_short(0.67, 0.40)
    if "лонгів" in ls["crowd"]:
        return _fail("0.67 must not mean crowd in longs")
    if "шортів" not in ls["crowd"]:
        return _fail("0.67 is more shorts")

    if zone_side(low=0.1529, high=0.1560, price=0.12712) != "above":
        return _fail("lobster FVG is above price")

    facts = build_homework_facts(
        symbol="LOBUSDT",
        price=0.12712,
        weekly_high=0.314,
        weekly_low=0.103,
        session={"pdh": 0.168, "pdl": 0.102},
        structure={"event": "LH_LL"},
        pd_arr={"zone": "DISCOUNT", "equilibrium": 0.2},
        sweep={},
        fvg={"bullish_fvg": {"type": "BULLISH", "low": 0.1529, "high": 0.1560}},
        order_blocks={"bearish_ob": {"low": 0.1305, "high": 0.1537}},
        dom={"total_whale_bids": 0, "total_whale_asks": 0, "description": "Великих ордерів не знайдено"},
        ls={"current_ratio": 0.67, "history": [{"long_pct": 0.40}]},
        oi={},
        atr_day_used=45.0,
        funding=None,
        edge={"verdict": "Помилка розрахунку"},
        probability=None,
    )
    if facts["confirmed"]:
        return _fail("bullish FVG above price must unconfirm")
    if facts.get("funding_pct") is not None:
        return _fail("missing funding must stay None")
    if facts.get("edge") is not None:
        return _fail("failed edge must be omitted")
    block = facts["dom_text"]
    if "ніхто не захищає" in block:
        return _fail("dom narrative")
    if "не доказ" not in block:
        return _fail("neutral empty book")

    bad_txt = (
        "Bullish FVG знизу 0.1529–0.1560. L/S = 0.67 лонгів — натовп в лонгах. "
        "Великих гравців немає — китів немає."
    )
    chk = validate_card_text(bad_txt, facts)
    if chk["ok"]:
        return _fail("must catch lobster errors")

    trump = "SHORT зона 2.137–2.171 стоп 2.213 ціль 1.924 RR ≈ 1:3"
    allowed = {2.171, 2.213, 2.107, 2.132, 1.931, 2.096}
    extra = unexplained_levels(trump, allowed)
    if 2.137 not in extra and not any(abs(x - 2.137) < 1e-6 for x in extra):
        return _fail(f"2.137 must be unexplained {extra}")
    if 1.924 not in extra and not any(abs(x - 1.924) < 1e-6 for x in extra):
        return _fail(f"1.924 must be unexplained {extra}")

    rr = rr_for_entry_range(
        direction="SHORT",
        entry_low=2.137,
        entry_high=2.171,
        sl=2.213,
        tp=1.924,
    )
    if "залежить" not in rr["text"] and abs(rr["rr_max"] - rr["rr_min"]) > 0.15:
        return _fail("RR range")
    # при різному ризику текст має не бути одним 1:3
    if "1:3" in rr["text"] and "весь діапазон" not in rr["text"] and abs(rr["rr_max"] - rr["rr_min"]) > 0.15:
        return _fail("must not emit single RR")

    note = recent_setups_note(
        [{"symbol": "BTCUSDT", "direction": "LONG", "outcome": "SKIP"}]
    )
    if "НЕ угоди" not in note and "не угоди" not in note.lower():
        return _fail("SKIP is not a trade")
    if "SKIP" not in note:
        return _fail("show SKIP label")
    if "готовий торговий план" not in lev_system_prompt():
        return _fail("lev prompt")

    card = homework_card_text(facts=facts, llm_text="коротко", issues=["геометрія"])
    if "дані не підтверджені" not in card:
        return _fail("unconfirmed flag")
    long = "x" * 4000
    chunks = split_telegram_chunks(long, limit=3500)
    if len(chunks) < 2:
        return _fail("must split not truncate away")
    if sum(len(c) for c in chunks) < 4000:
        return _fail("lost body")
    print("OK evening homework facts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

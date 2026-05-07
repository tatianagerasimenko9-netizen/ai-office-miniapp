from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from office_bridge import ConversationTurn, OfficeSignal, _risk_reply  # noqa: E402


def main() -> None:
    os.environ["OFFICE_LLM_MODE"] = "daryna"

    signal = OfficeSignal(
        signal_id="test-llm-daryna",
        symbol="BTCUSDT",
        direction="LONG",
        score=13,
        session="LONDON",
        regime="TREND",
        source_text="test signal",
        meta={
            "btc_change_pct": -2.1,
            "sym_change_pct": 0.4,
            "funding_rate": "0.012",
            "rr": 1.8,
            "volatility_pct": 2.2,
            "live_risk": {"open_trades_count": 2},
            "against_bias": True,
            "daily_bias": "BEARISH",
            "news_risk": "SAFE",
            "daily_drawdown": 1.3,
        },
    )

    conversation = [ConversationTurn("news", "Критичних новин поруч немає.")]
    decision = _risk_reply(signal, conversation)
    print("decision:", decision.decision)
    print("note:", decision.note)


if __name__ == "__main__":
    main()

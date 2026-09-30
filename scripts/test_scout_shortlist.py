#!/usr/bin/env python3
"""Скан ринку → короткий список із причиною відбору (для повного аналізу Лева лише кандидатів)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import office_market_scout as SC  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name + (f"  {extra}" if extra and not cond else ""))
    if not cond:
        FAILS.append(name)


def tk(sym, ch, vol, last=1.0):
    return {"symbol": sym, "lastPrice": str(last), "priceChangePercent": str(ch), "quoteVolume": str(vol), "highPrice": str(last * 1.03), "lowPrice": str(last * 0.97)}


tickers = [tk("BTCUSDT", 0.5, 9e9, 60000), tk("ETHUSDT", -0.4, 5e9, 3000), tk("PUMPUSDT", 18.5, 60e6), tk("DUMPUSDT", -12.0, 45e6),
           tk("FLATUSDT", 0.2, 6e6), tk("TINYUSDT", 30.0, 1e6), tk("BIGUSDT", 1.0, 3e9), tk("WATCHUSDT", 0.1, 8e6)]
screen = SC.screen_futures_market(tickers)
check("скан бачить ліквідні перпи (TINY з обсягом < 5 млн відсіяно)", screen.screened == 7 and all(r["symbol"] != "TINYUSDT" for r in screen.rows), str(screen.screened))

sl = SC.shortlist_with_reasons(screen, extra_user_symbols=["FLATUSDT"], active_watching=["WATCHUSDT"])
by = {x["symbol"]: x["reason"] for x in sl}
check("кожна монета списку має причину", all(x["reason"] for x in sl) and len(sl) == len({x["symbol"] for x in sl}))
check("запит власниці — перша причина", "запит власниці" in by["FLATUSDT"] and sl[0]["symbol"] == "FLATUSDT", str(by.get("FLATUSDT")))
check("контекст ринку (BTC і золото) позначено", "контекст ринку" in by["BTCUSDT"] and "контекст ринку" in by["XAUUSDT"], str(by))
check("вже у спостереженні — у причині", "вже у спостереженні" in by["WATCHUSDT"], str(by.get("WATCHUSDT")))
check("ріст за 24 год з числом", "ріст за 24 год +18,5%" in by["PUMPUSDT"], str(by.get("PUMPUSDT")))
check("падіння за 24 год з числом", "падіння за 24 год -12,0%" in by["DUMPUSDT"], str(by.get("DUMPUSDT")))
check("великий обсяг — у причині", "за обсягом" in by["BIGUSDT"], str(by.get("BIGUSDT")))
check("той самий склад, що й у promote_for_deep_scan", [x["symbol"] for x in sl] == SC.promote_for_deep_scan(screen, extra_user_symbols=["FLATUSDT"], active_watching=["WATCHUSDT"]))
check("немає знімка ринку → порожні/контекстні, без вигаданих монет", all(x["symbol"] in SC.CONTEXT_SEEDS for x in SC.shortlist_with_reasons(SC.screen_futures_market(None))))
cap = SC.shortlist_with_reasons(screen, cap=3)
check("ліміт cap поважається", len(cap) == 3)

# причина доходить до Mini App (market_state → scanner → radar_reasons)
import office_mini_v2 as m2  # noqa: E402

rs = m2.radar_reasons({"scout_reason": "ріст за 24 год +18,5%", "rsi": 72, "score": 7})
check("Radar показує «у списку: причина» першим рядком", rs[0] == "у списку: ріст за 24 год +18,5%" and any("RSI 72" in x for x in rs), str(rs))
check("без причини Radar не вигадує", not any(x.startswith("у списку") for x in m2.radar_reasons({"rsi": 50})))

import office_market_state as ms  # noqa: E402
import tempfile  # noqa: E402

db = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ["OFFICE_DB_PATH"] = db
try:
    from office_bridge import init_office_db

    init_office_db(db)
except Exception:  # noqa: BLE001
    pass
r = ms.record_scan_facts(db, "PUMPUSDT", rsi_h1=71.0, decision="WATCH", scout_reason="ріст за 24 год +18,5%")
check("record_scan_facts зберігає причину відбору", bool(r) and "scout_reason" in str(r), str(r)[:200])

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nВСЕ ОК")
sys.exit(1 if FAILS else 0)

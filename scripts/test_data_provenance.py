"""Походження даних для торгових рішень: ф'ючерсна обгортка відхиляє спот/Bybit/без позначки; Brain читає лише fapi; споживачі рішень/супроводу підключені до обгортки. Офлайн."""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import office_market_data as MD  # noqa: E402

FAILS = []


def check(n, ok, info=""):
    print(("OK  " if ok else "FAIL"), n, "" if ok else info)
    if not ok:
        FAILS.append(n)


bar = {"open": 1.0, "high": 2.0, "low": 1.0, "close": 1.5, "volume": 1.0, "ts": "2026-10-11T21:00:00+00:00"}
orig = MD.fetch_candles


def with_rows(rows):
    MD.fetch_candles = lambda *a, **k: rows
    try:
        return MD.fetch_candles_futures("TIAUSDT", "15m", 3)
    finally:
        MD.fetch_candles = orig


check("ф'ючерсні свічки Binance приймаються", bool(with_rows([dict(bar, src="binance_futures")])))
check("спот Binance відхиляється (повертається {})", with_rows([dict(bar, src="binance_spot_vision")]) == {})
check("Bybit відхиляється", with_rows([dict(bar, src="bybit_linear")]) == {})
check("свічки без позначки джерела відхиляються (невідоме походження)", with_rows([dict(bar)]) == {})
check("змішаний набір (частина резервна) відхиляється повністю", with_rows([dict(bar, src="binance_futures"), dict(bar, src="binance_spot_vision")]) == {})
check("порожня відповідь → {}", with_rows({}) == {})
h = MD.source_health()
check("лічильники рішень у source_health", h.get("decision_ok", 0) >= 1 and h.get("decision_rejected_nonfutures", 0) >= 3 and "decision_no_data" in h, str({k: v for k, v in h.items() if k.startswith("decision")}))

live = (ROOT / "office2" / "live.py").read_text(encoding="utf-8")
check("Brain (Feed) читає свічки напряму з fapi.binance.com, без резервних джерел", 'KL_URL = "https://fapi.binance.com/fapi/v1/klines"' in live and "_fallback_klines" not in live and "fetch_candles(" not in re.sub(r"fetch_candles_futures", "", live.split("class Feed")[1].split("def ")[0]))
check("paper/radar/shadow-цикли в live.py використовують ф'ючерсну обгортку", live.count("fetch_candles_futures as fetch_candles") == 4 and "import fetch_candles\n" not in live)
st = (ROOT / "office_signal_track.py").read_text(encoding="utf-8")
check("супровід сигналів (tick/milestones/false_expiry) використовує ф'ючерсну обгортку", st.count("fetch_candles_futures as fetch") == 3 and "fetch_candles as fetch" not in st)
eng = (ROOT / "office2" / "engine.py").read_text(encoding="utf-8")
check("заморожений знімок READY містить data_provenance (джерело, ТФ, час останнього закритого бару)", '"data_provenance": provenance' in eng and "last_closed_bar_open_ts" in eng)

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)

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


bar = {"open": 1.0, "high": 2.0, "low": 1.0, "close": 1.5, "volume": 1.0, "ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()}
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
check("протухла ф'ючерсна свічка (кеш при збої) не є підставою для рішення", with_rows([dict(bar, src="binance_futures", ts="2026-01-01T00:00:00+00:00")]) == {})
import datetime as _dt
_now = _dt.datetime.now(_dt.timezone.utc)
fut_bar = dict(bar, src="binance_futures", ts=(_now + _dt.timedelta(minutes=30)).isoformat())
check("свічка з майбутньою міткою часу відхиляється", with_rows([fut_bar]) == {})
cur = dict(bar, src="binance_futures", ts=(_now - _dt.timedelta(minutes=3)).isoformat())
check("поточна (формується) свічка допустима за замовчуванням", bool(with_rows([cur])))
def with_closed(rows):
    MD.fetch_candles = lambda *a, **k: rows
    try:
        return MD.fetch_candles_futures("TIAUSDT", "15m", 3, closed_only=True)
    finally:
        MD.fetch_candles = orig
closed = dict(bar, src="binance_futures", ts=(_now - _dt.timedelta(minutes=20)).isoformat())
check("closed_only відкидає свічку, що формується, і лишає закриті", with_closed([closed, cur]) == [closed] and with_closed([cur]) == {})
import inspect
check("fetch_candles за замовчуванням не бере спот/Bybit (allow_fallback=False)", inspect.signature(orig).parameters["allow_fallback"].default is False)
h = MD.source_health()
check("лічильники рішень у source_health", h.get("decision_ok", 0) >= 1 and h.get("decision_rejected_nonfutures", 0) >= 3 and "decision_no_data" in h, str({k: v for k, v in h.items() if k.startswith("decision")}))

# історія для графіка: прямий запит ф'ючерсів з endTime, без резервних джерел
_calls = []
_orig_get = MD._http_get_json
MD._http_get_json = lambda url, params=None, *a, **k: (_calls.append((url, dict(params or {}))) or [[1700000000000 + i * 900000, "1", "2", "0.5", "1.5", "10"] for i in range(3)])
hist = MD.fetch_candles_history("ADA", "15m", 500, end_ms=1700000900000)
MD._http_get_json = _orig_get
check("історія графіка: лише fapi з endTime, свічки позначені binance_futures", _calls and "fapi.binance.com" in _calls[0][0] and _calls[0][1].get("endTime") == 1700000900000 and _calls[0][1]["symbol"] == "ADAUSDT" and all(r["src"] == "binance_futures" for r in hist))
MD._http_get_json = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
check("історія при збої Binance — порожньо, без підміни спот/Bybit", MD.fetch_candles_history("ADA", "15m", 10, end_ms=1) == {})
MD._http_get_json = _orig_get

live = (ROOT / "office2" / "live.py").read_text(encoding="utf-8")
check("Brain (Feed) читає свічки напряму з fapi.binance.com, без резервних джерел", 'KL_URL = "https://fapi.binance.com/fapi/v1/klines"' in live and "_fallback_klines" not in live and "fetch_candles(" not in re.sub(r"fetch_candles_futures", "", live.split("class Feed")[1].split("def ")[0]))
check("paper/radar/shadow-цикли в live.py використовують ф'ючерсну обгортку", live.count("fetch_candles_futures as fetch_candles") == 4 and "import fetch_candles\n" not in live)
st = (ROOT / "office_signal_track.py").read_text(encoding="utf-8")
check("супровід сигналів (tick/milestones/false_expiry) використовує ф'ючерсну обгортку", st.count("fetch_candles_futures as fetch") == 3 and "fetch_candles as fetch" not in st)
eng = (ROOT / "office2" / "engine.py").read_text(encoding="utf-8")
check("заморожений знімок READY містить data_provenance (джерело, ТФ, час останнього закритого бару)", '"data_provenance": provenance' in eng and "last_closed_bar_open_ts" in eng)

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)

#!/usr/bin/env python3
"""Діалог із Левом (офлайн, синтетичні свічки, без мережі): відповіді лише з циклу Лева й БД;
застарілі дані → NO TRADE; символи/наміри; уточнення про інвалідацію та зміни; нічого не пишеться в БД."""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
db = str(Path(tempfile.mkdtemp()) / "d.db")
os.environ["OFFICE_DB_PATH"] = db
os.environ["DATABASE_URL"] = ""
import test_replay_lev_history as T  # noqa: E402
import office_lev_dialog as D  # noqa: E402
import office_market_data as MD  # noqa: E402
from office_bridge import init_office_db, log_event, _fetchone  # noqa: E402

init_office_db(db)
assert D.explicit_symbol("аналіз SOL") == "SOLUSDT" and D.explicit_symbol("що по ethusdt?") == "ETHUSDT"
assert D.explicit_symbol("який план?") is None and D.explicit_symbol("Лев, план SL TP1") is None
assert D.detect_intent("а де інвалідація?") == "invalid" and D.detect_intent("що змінилось?") == "changes"
assert D.detect_intent("чому не входиш") == "why" and D.detect_intent("привіт") == "full"

syn = T.synth(days=45)["timeframes"]
END = datetime(2026, 6, 15, tzinfo=timezone.utc)
def shifted(rows, sec, shift):
    n = len(rows)
    out = []
    for i, c in enumerate(rows):
        ts = END - timedelta(seconds=sec * (n - i)) + shift
        out.append({**c, "ts": ts.isoformat()})
    return out
NOW = END.timestamp()
STATE = {"shift": timedelta(0)}
def fake_fetch(sym, interval, n=100):
    key = {"15m": ("15m", 900), "1h": ("1h", 3600), "4h": ("1h", 3600), "1d": ("1d", 86400), "1w": ("1d", 86400)}[interval]
    rows = shifted(syn[key[0]], key[1], STATE["shift"])
    return rows[-n:]
MD.fetch_candles = fake_fetch

assert D.parse_command("/lev") == "" and D.parse_command("Лев, аналіз SOL") == "аналіз SOL"
assert D.parse_command("Левада привіт") is None and D.parse_command("привіт") is None and D.parse_command("levitate") is None
# свіжі дані → повна відповідь із висновком, ціною, свіжістю, «не ордер»
r = D.answer(db, "Лев, аналіз BTC", now=NOW)
assert r["ok"] and r["symbol"] == "BTCUSDT" and r["verdict"] in ("PLAN", "WAIT", "NO_TRADE"), r
assert r["text"].split("\n")[0].startswith(("🟡 BTC", "🟢 BTC", "⚪ BTC", "🔴 BTC")) and "не ордер" in r["text"] and not r["data_stale"], r["text"]
assert "ЗАРАЗ" in r["text"] and "Risk Officer" not in r["text"] and "LONG" not in r["text"] and "WATCHING" not in r["text"], r["text"]
assert r["order_authorized"] is False
# уточнення: інвалідація і причина — окремі, змістовні відповіді
inv = D.answer(db, "а де інвалідація?", symbol="BTCUSDT", now=NOW)
assert "СКАСУЄ ПЛАН" in inv["text"] or "ПЛАНУ ЗАРАЗ НЕМАЄ" in inv["text"], inv["text"]
why = D.answer(db, "чому так?", symbol="BTCUSDT", now=NOW)
assert why["intent"] == "why" and why["symbol"] == "BTCUSDT"
# зміни: з журналу тез, без вигадок
log_event(db, "THESIS_VERSION", {"symbol": "BTCUSDT", "direction": "LONG", "state": "WATCHING", "regime": "RANGE", "lev_action": "WAIT"}, "s1")
ch = D.answer(db, "що змінилось?", symbol="BTCUSDT", now=NOW)
assert ch["intent"] == "changes" and ("ЗМІН ПОКИ НЕ БУЛО" in ch["text"] or "ЩО ЗМІНЮВАЛОСЬ" in ch["text"]), ch["text"]
assert "ЗМІН ПОКИ НЕ БУЛО" in D.answer(db, "що змінилось по SOL?", now=NOW)["text"]
# застарілі дані → NO TRADE, ніколи не план
STATE["shift"] = timedelta(hours=-3)
D._CACHE.clear()
old = D.answer(db, "план BTC", now=NOW)
assert old["data_stale"] and old["verdict"] == "NO_TRADE" and "ДАНІ ЗАСТАРІЛИ" in old["text"], old
assert "ПЛАН УГОДИ: вхід" not in old["text"] and "🟢" not in old["text"]
# помилка джерела → NO TRADE з причиною, не виняток
def boom(*a, **k):
    raise RuntimeError("net")
MD.fetch_candles = boom
D._CACHE.clear()
bad = D.answer(db, "аналіз XRP", now=NOW)
assert bad["ok"] and bad["verdict"] == "NO_TRADE" and bad["data_stale"], bad
# діалог нічого не пише в БД (крім того, що ми самі додали)
assert _fetchone(db, "SELECT COUNT(*) FROM office_events WHERE event_type IN ('RISK_SHADOW_REVIEW','RISK_VETO')", ())[0] == 0
# єдиний запис у БД від діалогу — умова, яку Лев сам оголосив і відстежуватиме (LEV_WATCH); більше нічого
assert _fetchone(db, "SELECT COUNT(*) FROM office_events WHERE event_type NOT IN ('THESIS_VERSION','LEV_WATCH')", ())[0] == 0
# контекст діалогу (production-дефект: «а інвалідація?» після /lev BTC відповіла про LINK)
import time as _t
D.LAST.update(symbol=None, at=0.0)
D._CACHE.clear()
MD.fetch_candles = fake_fetch
STATE["shift"] = timedelta(0)
assert D.ask(db, "")["needs_symbol"] is True and "Про яку монету" in D.ask(db, "а інвалідація?")["text"], "без контексту — перепитати, не вгадувати"
assert D.parse_followup("а інвалідація?") is None, "без попередньої відповіді уточнення не перехоплюємо"
a1 = D.ask(db, "аналіз BTC")
assert a1["symbol"] == "BTCUSDT"
assert D.parse_followup("а інвалідація?") == "а інвалідація?"
a2 = D.ask(db, D.parse_followup("а інвалідація?"))
assert a2["symbol"] == "BTCUSDT" and a2["intent"] == "invalid" and "BTC" in a2["text"] and "LINK" not in a2["text"], a2["text"]
assert D.parse_followup("привіт, як справи?") is None and D.parse_followup("/status") is None
assert D.ask(db, "а по SOL що?")["symbol"] == "SOLUSDT"                      # явна інша монета — її, а не BTC
assert D.ask(db, "а інвалідація?")["symbol"] == "SOLUSDT"                    # контекст оновився
D.LAST["at"] = _t.time() - 3600                                               # контекст застарів → перепитуємо
assert D.parse_followup("а інвалідація?") is None and D.ask(db, "а інвалідація?")["needs_symbol"] is True
print("OK Lev dialog: grounded answers, NO TRADE on stale/failed data, follow-ups, no DB writes")

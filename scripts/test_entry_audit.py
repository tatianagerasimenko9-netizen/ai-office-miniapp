"""entry_audit: розпізнавання заявленого тригера, вхід до/після тригера на закритих M15, контрфактичний paper. Офлайн, без мережі."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from office2 import entry_audit as EA  # noqa: E402

FAILS = []


def check(n, ok, info=""):
    print(("OK  " if ok else "FAIL"), n, "" if ok else info)
    if not ok:
        FAILS.append(n)


T0 = 1_791_720_000 - (1_791_720_000 % 900)
M = 900


def bar(i, o, h, l, c):
    return {"ts": T0 + i * M, "open": o, "high": h, "low": l, "close": c}


card = {"card_id": "W|X", "symbol": "XUSDT", "direction": "LONG", "created_ts": T0 + 2 * M + 30, "sent_ts": None, "expires_ts": T0 + 20 * M, "entry": 100.0, "sl": 98.0, "tp1": 103.0, "tp2": None, "tp3": None,
        "risk_pct": 2.0, "need_text": "бичаче закриття M15 вище 101.5", "trigger_text": None, "stage": "ARMED", "kind": "WATCH", "entry_ts": T0 + 3 * M}
check("тригер CLOSE_BEYOND розпізнано", EA.trigger_of(card) == {"kind": "CLOSE_BEYOND", "level": 101.5, "above": True})
check("тригер «назад у зону» розпізнано", EA.trigger_of({"direction": "SHORT", "need_text": "закриття M15 назад у зону 12.905–12.9325"})["kind"] == "CLOSE_IN_ZONE")
check("trigger_text з комою у числах", EA.trigger_of({"direction": "LONG", "trigger_text": "Підтвердження на 15 хв: закриття 0,591 ≥ середини зони 0,578523."}) == {"kind": "CLOSE_VS_ZONE_MID", "close": 0.591, "mid": 0.578523, "above": True})
check("нерозпізнане → None, не вгадуємо", EA.trigger_of({"direction": "LONG", "need_text": "ретрейс у зону 1–2"}) is None)

# ціна торкнулась входу 100 у барі 3 (до закриття вище 101.5 у барі 5) → вхід ДО тригера
bars = [bar(0, 100, 101, 99, 100.5), bar(1, 100.5, 101, 99.5, 100), bar(2, 100, 100.8, 99.6, 100.2), bar(3, 100.2, 100.6, 99.9, 100.1), bar(4, 100.1, 101.0, 100.0, 100.9),
        bar(5, 100.9, 102.5, 100.8, 102.0), bar(6, 102.0, 103.5, 101.5, 103.2), bar(7, 103, 103.1, 101, 101.5)]
now = T0 + 10 * M
a = EA.audit_card(card, EA.closed_m15(bars, now))
check("вхід від дотику ДО закриття тригера → ВХІД_ДО_ТРИГЕРА", a["verdict"] == "ВХІД_ДО_ТРИГЕРА" and a["confirm_close_ts"] == T0 + 6 * M, a)
v = EA.confirmed_variant(card, bars, now)
check("контрфактичний вхід лише після тригера: ціна більше не повертається до 100 → входу немає", v and v["entry_ts"] is None and v["status"] in ("WAITING_ENTRY", "NO_ENTRY"), v)
check("тригер ще не виконано на as_of → NO_CONFIRM", EA.confirmed_variant(card, bars, T0 + 5 * M)["status"] == "NO_CONFIRM")
card2 = dict(card, entry_ts=T0 + 7 * M)
check("вхід після закриття тригера → ВХІД_ПІСЛЯ_ТРИГЕРА", EA.audit_card(card2, EA.closed_m15(bars, now))["verdict"] == "ВХІД_ПІСЛЯ_ТРИГЕРА")
check("тригер не виконано взагалі → ВХІД_БЕЗ_ВИКОНАНОГО_ТРИГЕРА", EA.audit_card(card, EA.closed_m15(bars[:5], now))["verdict"] == "ВХІД_БЕЗ_ВИКОНАНОГО_ТРИГЕРА")
mid = {"card_id": "B|Y", "symbol": "YUSDT", "direction": "LONG", "created_ts": T0, "entry": 0.5805, "entry_ts": T0 + 3 * M, "need_text": None,
       "trigger_text": "Підтвердження на 15 хв: закриття 0,591 ≥ середини зони 0,578523."}
am = EA.audit_card(mid, [])
check("TIA-подібно: тригер при створенні, ліміт нижче за ціну тригера — позначено, відстань у %", am["verdict"].endswith("НИЖЧЕ_ЗА_ЦІНУ_ТРИГЕРА") and am["entry_vs_confirm_close_pct"] > 1.7, am)
check("незакрита свічка не враховується", all(c["ts"] + M <= now for c in EA.closed_m15(bars, now)))

check("без свічок: НЕМАЄ_СВІЧОК, а не «тригер не виконано»", EA.audit_card(card, [])["verdict"] == "НЕМАЄ_СВІЧОК" and EA.confirmed_variant(card, [], now) is None)

print("FAILED:", FAILS) if FAILS else print("ALL OK")
sys.exit(1 if FAILS else 0)

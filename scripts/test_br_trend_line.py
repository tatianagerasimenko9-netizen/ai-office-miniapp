"""Рядок тренду на картці B&R (офлайн): текст у трьох випадках, місце в картці, розрахунок із годинних свічок, збій даних не ламає картку, ІНТРАДЕЙ/СВІНГ без змін."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from office_br import card, live
assert card.trend_line("LONG", True, True) == "🧭 Тренд: 4 год 🟢 вгору · 1 год 🟢 вгору — сигнал ЗА трендом"
assert card.trend_line("LONG", False, False) == "🧭 Тренд: 4 год 🔴 вниз · 1 год 🔴 вниз — сигнал ПРОТИ тренду"
assert card.trend_line("SHORT", False, False).endswith("— сигнал ЗА трендом") and card.trend_line("SHORT", True, True).endswith("— сигнал ПРОТИ тренду")
assert card.trend_line("SHORT", True, False) == "🧭 Тренд: 4 год 🟢 вгору · 1 год 🔴 вниз — тренди різні"
assert card.trend_line("LONG", None, True) is None
row = {"sig_id": "BR|BTCUSDT|LONG|1", "seq": 7, "symbol": "BTCUSDT", "direction": "LONG", "level": 62000.0, "entry": 62216.2, "sl": 61651.4, "targets_json": json.dumps([{"p": 62800.0, "src": "structure"}]), "hyp_json": "{}"}
base = card.build_card(row); tr = card.trend_line("LONG", True, False); withl = card.build_card(row, None, tr).split("\n")
assert withl[1] == tr and [x for x in withl if x != tr] == base.split("\n") and card.build_caption(row, None, tr)[0] == "\n".join(withl)
from datetime import datetime, timezone
mk = lambda closes: [{"ts": datetime.fromtimestamp(1_700_000_000 // 14400 * 14400 + i * 3600, timezone.utc).isoformat(), "open": c, "high": c, "low": c, "close": c} for i, c in enumerate(closes)]
up = lambda *a, **k: mk([100 + 0.1 * i for i in range(900)]); dn = lambda *a, **k: mk([200 - 0.1 * i for i in range(900)])
mix = lambda *a, **k: mk([100 + 0.1 * i for i in range(880)] + [188 - 2.0 * i for i in range(20)])          # довгий ріст, різке падіння в кінці: H4 ще вгору, H1 вже вниз
assert live.trend_text(up, "BTCUSDT", "LONG").endswith("сигнал ЗА трендом") and live.trend_text(dn, "BTCUSDT", "LONG").endswith("сигнал ПРОТИ тренду")
assert "4 год 🟢 вгору · 1 год 🔴 вниз — тренди різні" in live.trend_text(mix, "BTCUSDT", "SHORT"), live.trend_text(mix, "BTCUSDT", "SHORT")
assert live.trend_text(lambda *a, **k: mk([1.0] * 300), "X", "LONG") is None                       # замало історії для 4 год → без рядка
def boom(*a, **k): raise RuntimeError("x")
assert live.trend_text(boom, "X", "LONG") is None
print("ok br trend line")

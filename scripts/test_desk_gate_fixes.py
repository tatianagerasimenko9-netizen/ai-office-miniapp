"""Баги gate картки: стоп з неправильного боку, RR, прив'язка стопу до зони, точність цін."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from office_desk_card import desk_entry_gate, anchor_sl_beyond_zone, format_desk_card

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg)

# 1. LONG: вхід 96, стоп 97 (вище входу) — раніше send=True
g = desk_entry_gate(symbol="AKEUSDT", direction="LONG", entry=96.0, sl=97.0, tp1=106.0, atr_h1=1.0)
check(not g["send"] and "боку" in g["reason"], f"LONG стоп вище входу пройшов: {g}")
# 2. SHORT: стоп нижче входу
g = desk_entry_gate(symbol="AKEUSDT", direction="SHORT", entry=100.0, sl=99.0, tp1=94.0, atr_h1=1.0)
check(not g["send"], f"SHORT стоп нижче входу пройшов: {g}")
# 3. RR < 1.5 після розширення стопа до ATR(H1)
g = desk_entry_gate(symbol="AKEUSDT", direction="LONG", entry=100.0, sl=99.5, tp1=103.2, atr_h1=3.0)
check(not g["send"] and "RR" in g["reason"], f"RR<1.5 пройшов: {g}")
# 4. Нормальний LONG
g = desk_entry_gate(symbol="AKEUSDT", direction="LONG", entry=100.0, sl=97.0, tp1=106.0, atr_h1=1.0)
check(g["send"], f"нормальний LONG заблоковано: {g}")
# 5. Стоп за зоною: зона 95–96, стоп модуля 97 → має стати нижче 95
s = anchor_sl_beyond_zone(direction="LONG", sl=97.0, zone_lo=95.0, zone_hi=96.0, atr_h1=1.0)
check(s < 95.0, f"LONG стоп не за зоною: {s}")
s = anchor_sl_beyond_zone(direction="SHORT", sl=99.0, zone_lo=100.0, zone_hi=101.0, atr_h1=1.0)
check(s > 101.0, f"SHORT стоп не за зоною: {s}")
# стоп, що вже за зоною, не звужується
s = anchor_sl_beyond_zone(direction="LONG", sl=90.0, zone_lo=95.0, zone_hi=96.0, atr_h1=1.0)
check(s == 90.0, f"широкий стоп звужено: {s}")
# 6. Картка: зона по зростанню, одна точність, порожні рядки
t = format_desk_card(symbol="AKEUSDT", direction="LONG", timeframe="M15", entry=100.0, sl=97.7874,
                     tp1=104.32, entry_low=100.4, entry_high=99.3549, setup_type="PUMP")
check("🎯 Вхід · 99.35–100.40" in t, f"зона/точність: {t}")
check("PUMP" in t, f"тип PUMP загублено: {t}")
check("\n\n🎯" in t and "\n\nВхід після" in t, f"немає порожніх рядків: {t}")
t = format_desk_card(symbol="BTCUSDT", direction="LONG", timeframe="H1", entry=84870.5, sl=83676.16,
                     tp1=87309.31, tp2=88772.6)
check("83 676.1" in t and "87 309.3" in t and "88 772.6" in t, f"BTC точність: {t}")

if fails:
    print("FAIL:\n" + "\n".join(fails)); sys.exit(1)
print("OK desk gate fixes")

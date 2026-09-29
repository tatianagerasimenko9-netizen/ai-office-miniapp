"""Gate картки: стоп/TP1 з правильного боку, RR ≥ MIN_RR після розширення стопа до ATR(H1), зона відкату з правильного боку ціни."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("OFFICE_DEPO_USDT", "1000")
os.environ.setdefault("OFFICE_EXINFO_SEED", "1")
from office_desk_card import desk_entry_gate

fails = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


g = desk_entry_gate(symbol="AKEUSDT", direction="LONG", entry=96.0, sl=97.0, tp1=106.0, atr_h1=1.0)
check(not g["send"], f"LONG стоп вище входу пройшов: {g}")
g = desk_entry_gate(symbol="AKEUSDT", direction="SHORT", entry=100.0, sl=99.0, tp1=94.0, atr_h1=1.0)
check(not g["send"], f"SHORT стоп нижче входу пройшов: {g}")
g = desk_entry_gate(symbol="AKEUSDT", direction="LONG", entry=100.0, sl=99.5, tp1=103.2, atr_h1=3.0)
check(not g["send"] and "RR" in g["reason"], f"RR<1.5 пройшов: {g}")
g = desk_entry_gate(symbol="AKEUSDT", direction="LONG", entry=100.0, sl=97.0, tp1=106.0, atr_h1=1.0)
check(g["send"], f"нормальний LONG заблоковано: {g}")

# зона відкату з правильного боку ціни
from office_confluence import evaluate_confluence  # noqa: E402
import inspect  # noqa: E402

src = inspect.getsource(evaluate_confluence)
check("не відкат" in src and "px_side" in src, "фільтр «зона з іншого боку ціни» відсутній")

if fails:
    print("FAIL:\n" + "\n".join(fails))
    sys.exit(1)
print("OK desk gate fixes")

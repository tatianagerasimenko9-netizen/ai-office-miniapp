"""B&R v2 мітка: чиста, нічого не блокує. Без мережі."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from office_br import v2, card

def row(seq, sym, ts, entry=100.0, sl=100.9, d="SHORT"):
    return dict(sig_id=f"S{seq}", seq=seq, symbol=sym, direction=d, created_ts=ts, entry=entry, sl=sl, level=100.5,
                targets_json='[{"p":99.0,"src":"R1"}]')
T = 1792940400.0  # 2026-11-02 15:00 UTC → у вікні 13–17
a, b = row(1, "BTCUSDT", T), row(2, "ETHUSDT", T + 14)
rows = [a, b]
la, lb = v2.line(a, rows), v2.line(b, rows)
assert "✅" in la and "перший у русі ✔" in la, la
assert "❌" in lb and "ідея вже в BTC" in lb, lb
assert "❌" in v2.line(row(3, "SOLUSDT", T + 900 * 5, sl=100.3), [row(3, "SOLUSDT", T + 900 * 5, sl=100.3)])  # стоп 0.3% < 0.8%
assert v2.in_session(T) and not v2.in_session(T - 6 * 3600)
other_dir = row(4, "XRPUSDT", T + 5, d="LONG")
assert "перший у русі ✔" in v2.line(other_dir, [a, other_dir])  # інший напрям — не той самий рух
txt = card.build_card(a, la)
assert la in txt and "тільки ручне рішення" in txt
assert card.build_card(a) .count("v2 ") == 0  # без мітки картка як раніше
print("OK br_v2")

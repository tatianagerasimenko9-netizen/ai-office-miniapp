"""Методика Дарії Жданової — shadow-спостерігач (НЕ торгове правило, у LIVE не підключений).

Джерело правил: docs/office2/DARIA_ZHDANOVA_METHOD.md, docs/strategies/DARIA_ZHDANOVA.md. Модуль лише ВИМІРЮЄ спостережувані ознаки на закритих свічках до моменту рішення
(жодних майбутніх барів) і описує їх простою мовою. Порогів «добре/погано» тут немає навмисне: у матеріалах авторки їх немає як чисел — вони чекають перевірки
на незалежних даних. Результат шляхом `observe()` можна зберігати поруч із карткою й порівнювати з фактичним результатом (збіги/розбіжності з основною стратегією)."""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

VERSION = "daria-shadow-1"
TOUCH_ATR = 0.25          # «торкання рівня» = екстремум свічки в межах 0,25 ATR від рівня (вимірювальна домовленість, не правило авторки)
LOOKBACK = 24             # барів для вимірювань (M15 → 6 годин)


def _atr(c: List[Dict[str, Any]], n: int = 14) -> float:
    trs = [max(b["high"] - b["low"], abs(b["high"] - p["close"]), abs(b["low"] - p["close"])) for p, b in zip(c, c[1:])]
    t = trs[-n:]
    return sum(t) / len(t) if t else 0.0


def observe(direction: str, level: float, candles: List[Dict[str, Any]], decision_ts: float, next_obstacle: Optional[float] = None, bar: int = 900) -> Dict[str, Any]:
    """direction — напрям ідеї ('LONG'/'SHORT'); level — ключовий рівень; candles — свічки {ts, open?, high, low, close, volume?}; decision_ts — момент рішення.
    Використовуються ЛИШЕ бари, що ЗАКРИЛИСЬ до decision_ts (ts + bar ≤ decision_ts)."""
    cl = sorted((b for b in candles if b.get("ts") is not None and b["ts"] + bar <= decision_ts), key=lambda b: b["ts"])[-LOOKBACK:]
    out: Dict[str, Any] = {"version": VERSION, "direction": direction, "level": level, "decision_ts": decision_ts, "bars_used": len(cl), "lines": [], "status": "OBSERVED",
                           "thresholds": "числових порогів у джерелі немає — потребують перевірки на незалежних даних"}
    if len(cl) < 8 or not level:
        out.update(status="NOT_AVAILABLE", reason="замало закритих свічок до моменту рішення")
        return out
    sg = 1.0 if direction == "LONG" else -1.0
    atr = _atr(cl) or (cl[-1]["high"] - cl[-1]["low"]) or 1e-12
    last = cl[-1]
    # 1) де остання закрита свічка відносно рівня (LONG: ввись від рівня = «над», SHORT: вниз)
    dist = (last["close"] - level) * sg
    out["close_vs_level"] = {"atr": round(dist / atr, 2), "pct": round(dist / level * 100.0, 3), "side": "за рівнем" if dist > 0 else "перед рівнем"}
    # 2) торкання/реакції рівня
    touches = sum(1 for b in cl if abs((b["high"] if sg < 0 else b["low"]) - level) <= TOUCH_ATR * atr)
    out["touches"] = touches
    # 3) підтиснення: LONG до опору — вищі мінімуми; SHORT до підтримки — нижчі максимуми (частка послідовних барів)
    k = cl[-10:]
    if sg > 0:
        steps = [1 if b["low"] >= a["low"] else 0 for a, b in zip(k, k[1:])]
    else:
        steps = [1 if b["high"] <= a["high"] else 0 for a, b in zip(k, k[1:])]
    out["squeeze_share"] = round(sum(steps) / len(steps), 2) if steps else None
    # 4) глибина відкату від найкращого екстремуму руху в бік ідеї
    ext = max(b["high"] for b in cl) if sg > 0 else min(b["low"] for b in cl)
    rng = max(b["high"] for b in cl) - min(b["low"] for b in cl)
    out["pullback_share"] = round(abs(ext - last["close"]) / rng, 2) if rng else None
    # 5) запас ходу до наступної перешкоди
    if next_obstacle:
        room = (next_obstacle - last["close"]) * sg
        out["room_atr"] = round(room / atr, 2)
    else:
        out["room_atr"] = None
    # 6) обсяг × результат останніх 3 барів (якщо є обсяг)
    vols = [b.get("volume") for b in cl if b.get("volume") is not None]
    if len(vols) >= 8:
        med = statistics.median(vols[:-3]) or 1e-12
        rel = sum(vols[-3:]) / 3.0 / med
        prog = abs(cl[-1]["close"] - cl[-4]["close"]) / atr
        out["volume_x_result"] = {"volume_rel": round(rel, 2), "progress_atr": round(prog, 2), "reading": "обсяг без прогресу ціни — боротьба/поглинання" if rel > 1.5 and prog < 0.5 else "обсяг і прогрес узгоджені" if rel > 1.5 and prog >= 0.5 else "без вираженого обсягу"}
    else:
        out["volume_x_result"] = None
    ln = out["lines"]
    ln.append(f"Остання закрита свічка {out['close_vs_level']['side']} ({out['close_vs_level']['atr']:+.2f} ATR від рівня).")
    ln.append(f"Рівень торкались {touches} раз(и) за {len(cl)} барів.")
    if out["squeeze_share"] is not None:
        ln.append(f"Підтиснення: {int(out['squeeze_share'] * 100)}% барів тиснуть до рівня ({'вищі мінімуми' if sg > 0 else 'нижчі максимуми'}).")
    if out["pullback_share"] is not None:
        ln.append(f"Глибина відкату від екстремуму: {int(out['pullback_share'] * 100)}% діапазону.")
    ln.append(f"Запас ходу до наступної перешкоди: {out['room_atr']:+.1f} ATR." if out["room_atr"] is not None else "Запас ходу: наступну перешкоду не задано — не оцінюю.")
    if out["volume_x_result"]:
        ln.append("Обсяг × результат: " + out["volume_x_result"]["reading"] + ".")
    ln.append("Пороги «добре/погано» не застосовано: у джерелі їх немає, вони перевіряються окремо.")
    return out

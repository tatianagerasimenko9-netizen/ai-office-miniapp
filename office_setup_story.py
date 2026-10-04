"""Людська назва сетапу й 2–4 вирішальні причини — ЛИШЕ з тегів, що реально дали READY (SIGNAL_PLAN.gate.confirm.tags + спосіб).

Детермінований словник, без LLM і без «красивої історії постфактум». Немає запису про підтвердження → назви немає (чесно «не збережено»).
Також визначає, які об'єкти малювати на графіку (лише ті, що брали участь у рішенні)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# структурна основа входу (перший за пріоритетом дає назву): тег → (фраза для назви, причина для людини, об'єкт на графіку)
STRUCT = [
    ("level_retest", ("ретест рівня", "Ціна повернулась до рівня і відбилась (ретест)", "level")),
    ("level_hold", ("рівень утримано", "Рівень утримано — ціна не пройшла крізь нього", "level")),
    ("level_false_break", ("хибний пробій рівня", "Хибний пробій рівня з поверненням", "level")),
    ("fvg_retest", ("повернення в розрив між свічками", "Ціна повернулась у розрив між свічками, який не заповнили, і відбилась", "fvg")),
    ("ob_retest", ("відбиття від зони, звідки почався рух", "Ціна відбилась від зони, звідки почався попередній рух", "block")),
    ("breaker_retest", ("відбиття від зламаної зони", "Ціна відбилась від зони, яку раніше пробили", "block")),
    ("sweep_pool", ("прокол за стопи й повернення", "Ціну різко повели за рівень, де стоять чужі стопи, і повернули назад", "level")),
    ("sfp", ("прокол за стопи й повернення", "Ціна коротко вийшла за екстремум і повернулась назад", "level")),
    ("spring", ("прокол вниз і повернення", "Ціна коротко пробила низ і повернулась назад", "level")),
    ("upthrust", ("прокол вгору і повернення", "Ціна коротко пробила верх і повернулась назад", "level")),
    ("spring_test", ("повторна перевірка низу", "Ціна повторно перевірила низ після проколу", "level")),
    ("upthrust_test", ("повторна перевірка верху", "Ціна повторно перевірила верх після проколу", "level")),
    ("choch", ("зміна напрямку руху", "Рух на малому таймфреймі змінив напрямок", "level")),
    ("bos", ("злам останньої опори", "Ціна зламала останню опору на малому таймфреймі", "level")),
    ("double_top", ("подвійна вершина", "Подвійна вершина підтверджена закриттям за лінією шиї", "level")),
    ("double_bottom", ("подвійне дно", "Подвійне дно підтверджено закриттям за лінією шиї", "level")),
    ("triple_top", ("потрійна вершина", "Потрійна вершина підтверджена закриттям", "level")),
    ("triple_bottom", ("потрійне дно", "Потрійне дно підтверджено закриттям", "level")),
    ("head_shoulders", ("голова і плечі", "Фігура «голова і плечі» підтверджена", "level")),
    ("inverse_head_shoulders", ("перевернута голова і плечі", "Фігура «перевернута голова і плечі» підтверджена", "level")),
    ("displacement", ("різкий рух у бік сценарію", "Був різкий рух у бік сценарію", "candle")),
    ("ote", ("відкат у зону входу", "Ціна відкотилась у зону, де зазвичай продовжують рух", "candle")),
    ("exhaustion", ("рух вичерпується", "Рух вичерпується: кожен наступний ривок слабший", "candle")),
]
PATTERN = {"flag": "прапор: коротка пауза в русі", "pennant": "вимпел: звужена пауза в русі", "ascending_triangle": "висхідний трикутник", "descending_triangle": "низхідний трикутник",
           "symmetrical_triangle": "симетричний трикутник", "rectangle": "прямокутник", "rising_wedge": "висхідний клин", "falling_wedge": "спадний клин"}
TRIGGER = {"engulf": ("розворотна свічка", "Розворотна свічка, що перекрила попередню"), "engulfing_ctx": ("розворотна свічка", "Розворотна свічка, що перекрила попередню"),
           "pin_bar": ("свічка з довгою тінню", "Свічка з довгою тінню біля зони"), "inside_bar_break": ("вихід із вузької свічки", "Ціна вийшла за межі вузької свічки")}
CHANNEL = "channel_edge"


def build(tags: List[str], mode: Optional[str], direction: str, *, rr_net: Any = None, rr_weighted: Any = None, tf: str = "M15",
          entry_txt: str = "", zone_txt: str = "") -> Dict[str, Any]:
    """{'name', 'why': [≤4], 'objects': [...]} або name=None, коли підтвердження не збережено."""
    side = "SHORT" if str(direction or "").upper() == "SHORT" else "LONG"
    ts = [str(t) for t in (tags or [])]
    if not ts and mode != "retest":
        return {"name": None, "why": [], "objects": []}
    main = next(((k, v) for k, v in STRUCT if k in ts), None)
    pat = next((PATTERN[t] for t in ts if t in PATTERN), None)
    trig = next((TRIGGER[t] for t in ts if t in TRIGGER), None)
    chan = CHANNEL in ts
    if mode == "retest" and main is None:
        core = "пробій зони і повернення до неї"
    elif main:
        core = main[1][0]
    elif pat:
        core = f"продовження руху ({pat.split(':')[0]})"
    elif trig:
        core = trig[0]
    elif chan:
        core = "відбиття від краю лінії тренду"
    else:
        core = "підтвердження на молодшому таймфреймі"
    name = f"{side} · {core}"
    if chan and core != "відбиття від краю лінії тренду":
        name += " біля краю лінії тренду"
    if pat and main:
        name += f" після паузи в русі ({pat.split(':')[0]})"
    if trig and main:
        name += f" + {trig[0]}"
    why: List[str] = []
    if main:
        why.append(main[1][1])
    if entry_txt and zone_txt:
        why.insert(0, f"Вхід {entry_txt} — у зоні {zone_txt}")
    if pat and not main:
        why.append(f"Після паузи в русі: {pat}")
    if chan:
        why.append("Ціна біля краю лінії тренду (регресійний канал)")
    if trig:
        why.append(trig[1])
    if mode == "retest":
        why.append("Ціна пробила зону й повернулась до неї окремою свічкою")
    else:
        why.append(f"Свічка {tf} закрилась усередині зони входу")
    if rr_net is not None:
        why.append(("Вигода до втрати: " + f"{float(rr_net):.2f}".replace(".", ",") + " до TP1" + (f", {float(rr_weighted):.2f}".replace(".", ",") + " із TP2" if rr_weighted is not None else "") + " (після комісій)"))
    objs: List[str] = []
    if main and main[1][2] not in objs:
        objs.append(main[1][2])
    if any(t in ts for t in ("fvg_retest",)) and "fvg" not in objs:
        objs.append("fvg")
    if chan:
        objs.append("channel")
    return {"name": name, "why": why[:4], "objects": objs}

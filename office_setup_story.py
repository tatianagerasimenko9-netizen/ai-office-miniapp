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
    ("fvg_retest", ("повернення до FVG", "Ціна повернулась до незаповненого розриву (FVG) і відреагувала", "fvg")),
    ("ob_retest", ("реакція від блоку (OB)", "Реакція від блоку, звідки йшов рух (order block)", "block")),
    ("breaker_retest", ("реакція від breaker", "Реакція від зламаного блоку (breaker)", "block")),
    ("sweep_pool", ("зняття ліквідності", "Зняли ліквідність за рівнем і повернулись назад", "level")),
    ("sfp", ("хибний пробій і повернення (SFP)", "Хибний пробій екстремуму з поверненням у діапазон (SFP)", "level")),
    ("spring", ("spring Вайкоффа", "Хибний прокол вниз і повернення (spring)", "level")),
    ("upthrust", ("upthrust Вайкоффа", "Хибний прокол вгору і повернення (upthrust)", "level")),
    ("spring_test", ("тест spring", "Тест після spring", "level")),
    ("upthrust_test", ("тест upthrust", "Тест після upthrust", "level")),
    ("choch", ("зміна характеру (CHoCH)", "Зміна характеру руху на молодшому таймфреймі (CHoCH)", "level")),
    ("bos", ("злам структури (BOS)", "Злам структури на молодшому таймфреймі (BOS)", "level")),
    ("double_top", ("подвійна вершина", "Подвійна вершина підтверджена закриттям за лінією шиї", "level")),
    ("double_bottom", ("подвійне дно", "Подвійне дно підтверджено закриттям за лінією шиї", "level")),
    ("triple_top", ("потрійна вершина", "Потрійна вершина підтверджена закриттям", "level")),
    ("triple_bottom", ("потрійне дно", "Потрійне дно підтверджено закриттям", "level")),
    ("head_shoulders", ("голова і плечі", "Фігура «голова і плечі» підтверджена", "level")),
    ("inverse_head_shoulders", ("перевернута голова і плечі", "Фігура «перевернута голова і плечі» підтверджена", "level")),
    ("displacement", ("сильний імпульс", "Сильний імпульсний рух у бік сценарію", "candle")),
    ("ote", ("зона OTE", "Ціна в зоні оптимального відкату (OTE)", "candle")),
    ("exhaustion", ("виснаження руху", "Рух виснажується", "candle")),
]
PATTERN = {"flag": "прапор", "pennant": "вимпел", "ascending_triangle": "висхідний трикутник", "descending_triangle": "низхідний трикутник",
           "symmetrical_triangle": "симетричний трикутник", "rectangle": "прямокутник", "rising_wedge": "висхідний клин", "falling_wedge": "спадний клин"}
TRIGGER = {"engulf": ("поглинання", "Розворотна свічка-поглинання"), "engulfing_ctx": ("поглинання", "Розворотна свічка-поглинання"),
           "pin_bar": ("пін-бар", "Пін-бар біля зони"), "inside_bar_break": ("пробій inside bar", "Пробій після inside bar")}
CHANNEL = "channel_edge"


def build(tags: List[str], mode: Optional[str], direction: str, *, rr_net: Any = None, rr_weighted: Any = None, tf: str = "M15") -> Dict[str, Any]:
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
        core = "пробій зони і ретест"
    elif main:
        core = main[1][0]
    elif pat:
        core = f"фігура продовження ({pat})"
    elif trig:
        core = trig[0]
    elif chan:
        core = "реакція від краю каналу"
    else:
        core = "підтвердження на молодшому таймфреймі"
    name = f"{side} · {core}"
    if chan and core != "реакція від краю каналу":
        name += " біля краю каналу"
    if pat and main:
        name += f" після фігури ({pat})"
    if trig and main:
        name += f" + {trig[0]}"
    why: List[str] = []
    if main:
        why.append(main[1][1])
    if pat and not main:
        why.append(f"Фігура продовження: {pat}")
    if chan:
        why.append("Ціна біля краю регресійного каналу")
    if trig:
        why.append(trig[1])
    if mode == "retest":
        why.append("Пробій зони з ретестом окремими свічками")
    else:
        why.append(f"Закриття свічки {tf} усередині зони входу")
    if rr_net is not None:
        why.append(f"Потенціал достатній: до TP1 {float(rr_net):.2f}" + (f", зважений {float(rr_weighted):.2f}" if rr_weighted is not None else "") + " (після комісій)")
    objs: List[str] = []
    if main and main[1][2] not in objs:
        objs.append(main[1][2])
    if any(t in ts for t in ("fvg_retest",)) and "fvg" not in objs:
        objs.append("fvg")
    if chan:
        objs.append("channel")
    return {"name": name, "why": why[:4], "objects": objs}

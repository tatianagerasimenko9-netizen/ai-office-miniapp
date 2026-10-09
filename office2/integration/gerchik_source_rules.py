"""Реєстр явних правил із повного тексту «Курс активного трейдера».

У Git зберігаються лише короткі парафрази й координати приватних PART_01..16,
не сам текст книги. Реєстр є research/shadow provenance, а не production CONFIG.
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

SOURCE_ID = "GERCHIK-KURS-AKTIVNOGO-TREIDERA-2019"
SOURCE_SHA256 = "2c0dd2a52d2a7f5b194db7a6c7cbb08e38bfb54a1913683a6046ffb73978a923"
SOURCE_PARTS = tuple(f"P{part:02d}" for part in range(1, 17))

_RULES: List[Dict[str, Any]] = [
    {"id": "G-SIGNAL-CLOSE", "chapter": 3, "refs": ["P05:L146-L155"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Сигнальне значення має закриття бара відносно рівня; intrabar-прокол сам по собі не підтверджує напрям."},
    {"id": "G-IMPULSE-CONFIRM", "chapter": 3, "refs": ["P05:L223-L247"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Пробій або відбій підтверджує імпульс; без імпульсу пробій імовірніше хибний, а відбій може перейти у проторговку.",
     "parameters_from_source": {"impulse_move_vs_average_daily": "2–3x"}},
    {"id": "G-LEVEL-HTF-FIRST", "chapter": 2, "refs": ["P02:L104-L140", "P07:L450-L469"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Сильний рівень і напрям визначають на старшому, переважно денному ТФ; молодший ТФ використовують для точки входу."},
    {"id": "G-LEVEL-FLOATING-NO-TRADE", "chapter": 2, "refs": ["P04:L187-L193", "P13:L209-L220"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Плаваючий рівень не торгують; чекають консолідацію та появу чіткої сторони."},
    {"id": "G-LEVEL-LEFT-TO-RIGHT", "chapter": 2, "refs": ["P04:L482-L495", "P13:L224-L248"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Рівні будують зліва направо від минулих ключових точок, не підганяючи графік під висновок."},
    {"id": "G-LEVEL-FALSE-BREAK-STRENGTH", "chapter": 2, "refs": ["P04:L424-L427", "P13:L342-L345"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Хибний пробій підсилює вже визначений рівень; кількість підтверджень враховують у домашній підготовці."},
    {"id": "G-RISK-STOP-FIRST", "chapter": 4, "refs": ["P03:L36-L40", "P06:L126-L180"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Угоду планують від ризику і відкривають лише коли визначене місце реального stop-loss; stop ставлять одразу."},
    {"id": "G-RISK-NO-WIDEN", "chapter": 7, "refs": ["P10:L313-L328", "P12:L241-L245"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Stop-loss не переносять у бік збільшення ризику; у крипті автор також вимагає реального, а не уявного stop."},
    {"id": "G-RISK-RR3", "chapter": 4, "refs": ["P06:L102-L115", "P09:L180-L264", "P14:L205-L216"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Плановий прибуток має бути щонайменше утричі більший за ризик.",
     "parameters_from_source": {"minimum_reward_risk": 3.0}},
    {"id": "G-RISK-SESSION-STOP", "chapter": 4, "refs": ["P07:L213-L232", "P11:L96-L97", "P14:L241-L262"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Після трьох збиткових угод поспіль торгівлю на сесію припиняють; денний ризик задають до початку.",
     "parameters_from_source": {"consecutive_losses_limit": 3},
     "ambiguity": "У різних розділах наведені різні діапазони ризику на депозит; це контекст, не єдиний CONFIG."},
    {"id": "G-STOP-TECHNICAL", "chapter": 4, "refs": ["P06:L222-L245", "P14:L303-L318"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Технічний stop ставлять за рівень, екстремум або хвіст пробійного бара з малим відступом і перевіряють проти допустимого ризику."},
    {"id": "G-ATR-CALC", "chapter": 4, "refs": ["P06:L372-L428", "P13:L522-L551"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Середній денний хід рахують за попередні дні без паранормальних значень; поточний день у середнє не включають."},
    {"id": "G-ATR-75-80", "chapter": 4, "refs": ["P06:L479-L503", "P06:L504-P07:L10"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Після проходження приблизно 75–80% денного ATR не відкривають новий вхід за ходом, крім окремо описаного випадку локального екстремуму."},
    {"id": "G-ATR-ROOM", "chapter": 4, "refs": ["P07:L11-L28", "P13:L555-L570"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Між рівнями має бути достатній технічний запас для кількох stop і мінімум 3R; якщо запас менший, входу немає.",
     "parameters_from_source": {"room_in_stops": "4–6 (в іншому викладі: мінімум 5)"}},
    {"id": "G-LUFT", "chapter": 4, "refs": ["P07:L60-L75"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Заявку розташовують перед рівнем із люфтом; люфт входить у загальний stop.",
     "parameters_from_source": {"luft": "20% розрахункового stop або 0.04% ціни"}},
    {"id": "G-CHANNEL", "chapter": 5, "refs": ["P07:L496-P08:L14", "P15:L110-L125"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Канал торгують лише за достатньої ширини; від середини потрібен окремий запас до цільової межі.",
     "parameters_from_source": {"channel_width_stops": "6–8", "middle_entry_room_stops": 4}},
    {"id": "GERCHIK-08-VIDBIY", "chapter": 5, "refs": ["P08:L127-L280", "P14:L372-L461"], "scope": "EXPLICIT_STRATEGY",
     "rule_ua": "Відбій вимагає БСУ, БПУ1 і сусідній БПУ2 без пробою; за поджаття чекають вирівнювальний бар; модель має явні умови скасування."},
    {"id": "GERCHIK-09-PROBIY", "chapter": 5, "refs": ["P08:L346-L382", "P14:L489-L543"], "scope": "EXPLICIT_STRATEGY",
     "rule_ua": "Для пробою шукають сильний рівень і підхід малими барами/поджаттям; stop-order ставлять за рівнем, захисний stop — з іншого боку; без імпульсу пробій сумнівний."},
    {"id": "GERCHIK-06-LP-1BAR", "chapter": 5, "refs": ["P08:L505-L575", "P14:L619-L646", "P15:L4-L13"], "scope": "EXPLICIT_STRATEGY",
     "rule_ua": "Однобарний ЛП: бар проколює рівень і повертається; до закриття ставлять stop-order у вихідній площині, stop — за хвіст або рівень, TP не менше 3R.",
     "parameters_from_source": {"preferred_max_depth_atr": "приблизно 30% / 1/3 ATR"}},
    {"id": "GERCHIK-06-LP-2BAR", "chapter": 5, "refs": ["P08:L616-L622", "P09:L1-L43", "P15:L23-L52"], "scope": "EXPLICIT_STRATEGY",
     "rule_ua": "Двобарний ЛП: перший бар закривається за рівнем, другий відкривається там і має повернутися; entry-order ставлять одразу після відкриття другого, TP не менше 3R."},
    {"id": "GERCHIK-06-LP-COMPLEX", "chapter": 5, "refs": ["P09:L56-L139", "P15:L63-L99"], "scope": "EXPLICIT_STRATEGY",
     "rule_ua": "Складний ЛП: щонайменше три наступні бари відкриваються й закриваються у площині пробою без зворотного пробою; після цього ставлять order на повернення, stop технічний, TP не менше 3R."},
    {"id": "G-TP-TRAIL", "chapter": 5, "refs": ["P09:L180-L264"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Після входу ризик не збільшують; позицію можна супроводжувати за локальними екстремумами, консолідаціями або денними барами після забезпечення планового результату."},
    {"id": "G-ADD-IN-PROFIT", "chapter": 5, "refs": ["P09:L272-L316"], "scope": "EXPLICIT_RULE",
     "rule_ua": "Обсяг додають лише в прибуткову позицію з нової чистої точки; попередній прибуток захищений, а новий ризик не більший за попередній."},
    {"id": "G-ONE-STRATEGY-SAMPLE", "chapter": 5, "refs": ["P07:L374-L437", "P14:L350-L368"], "scope": "TRAINING_RULE",
     "rule_ua": "Стратегії тестують окремо; перед вибором робочої моделі потрібна серія пробних угод, а одночасне змішування моделей шкодить системності.",
     "parameters_from_source": {"trial_trades": "щонайменше 100"}},
    {"id": "G-CRYPTO-CONTEXT", "chapter": 8, "refs": ["P12:L224-L252"], "scope": "MARKET_ADAPTATION",
     "rule_ua": "Для крипти стежать за ліквідними інструментами й BTC, використовують лімітні заявки, технічні stop та заздалегідь підготовлені orders; маржинальна торгівля має підвищений ризик."},
]

_REF_RE = re.compile(r"^P(0[1-9]|1[0-6]):L\d+(?:-P(0[1-9]|1[0-6]):L\d+|-L\d+)?$")


def gerchik_source_rules() -> List[Dict[str, Any]]:
    return deepcopy(_RULES)


def validate_source_registry(rules: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """Перевіряє структурну цілісність реєстру, не читаючи приватний корпус."""
    errors: List[str] = []
    checked = _RULES if rules is None else rules
    ids = [str(rule.get("id") or "") for rule in checked]
    if len(ids) != len(set(ids)):
        errors.append("duplicate rule ids")
    for rule in checked:
        if not rule.get("id") or not rule.get("rule_ua") or not rule.get("refs"):
            errors.append(f"incomplete rule: {rule.get('id')}")
        for ref in rule.get("refs") or []:
            if not _REF_RE.match(str(ref)):
                errors.append(f"invalid source ref {rule.get('id')}: {ref}")
    return errors

"""Реєстр джерел SM Trader (Smart Money Concept, 20.03.2026): кожен розділ/підрозділ змісту → source_section_id; 40 навчальних схем → visual fixture registry.

Це реєстр походження правил, а не доказ їхньої прибутковості. «Статус» розділу — що з нього алгоритмізовано (див. docs/office2/SMC_MATRIX.md, генерується office2.smc.matrix)."""
from __future__ import annotations

from typing import Any, Dict, List

# (id, заголовок у джерелі, рівень, клас: ALGO — є формальне правило; CONTEXT — контекст/освіта; EXTERNAL — реклама/посилання)
SECTIONS: List[Dict[str, Any]] = [
    {"id": "S01", "title": "Знакомство с концептом Смарт Мани", "cls": "CONTEXT"},
    {"id": "S02", "title": "Глоссарий терминов", "cls": "CONTEXT"},
    {"id": "S03", "title": "Что такое Smart Money?", "cls": "CONTEXT", "note": "твердження про «крупний капітал» — гіпотеза, не спостережувані дані"},
    {"id": "S04", "title": "Разница между Тех Анализом и Смарт Мани", "cls": "CONTEXT"},
    {"id": "S05", "title": "Риск-менеджмент и дисциплина", "cls": "ALGO", "note": "0,5–1% на угоду, стоп після 2 SL, 3%/тиждень — вже є в office2.risk/engine.portfolio_gate; не змінюється"},
    {"id": "S06", "title": "Рыночный цикл и тренды, фазы рынка", "cls": "ALGO", "note": "Wyckoff-фази — лише гіпотеза; спостережувані стани RANGE/UP/DOWN"},
    {"id": "S07", "title": "Стиль торговли и таймфреймы", "cls": "ALGO", "note": "для Office: день → 4H → 15m"},
    {"id": "S08", "title": "Анализ Таймфреймов: LTP / ITP / STP", "cls": "ALGO"},
    {"id": "S09.1", "title": "Трендовые движения", "cls": "ALGO"},
    {"id": "S09.2", "title": "Свинги (Swing High / Swing Low)", "cls": "ALGO"},
    {"id": "S09.3", "title": "BOS/MSB и Confirm", "cls": "ALGO"},
    {"id": "S09.4", "title": "Синхронизация структуры", "cls": "ALGO"},
    {"id": "S10.1", "title": "Структурные точки Swing", "cls": "ALGO"},
    {"id": "S10.2", "title": "Восходящая структура", "cls": "ALGO"},
    {"id": "S10.3", "title": "Нисходящая структура рынка", "cls": "ALGO"},
    {"id": "S10.4", "title": "Боковое движение цены (Range, Deviation)", "cls": "ALGO"},
    {"id": "S11", "title": "Range и Expansion: консолидация → расширение", "cls": "ALGO"},
    {"id": "S12", "title": "MSB (Market Structure Break) — слом структуры", "cls": "ALGO"},
    {"id": "S13", "title": "Fibonacci / PD Array: Premium / Discount и Dealing Range", "cls": "ALGO"},
    {"id": "S13.1", "title": "OTE (Optimal Trade Entry)", "cls": "ALGO"},
    {"id": "S14", "title": "Имбаланс — FVG", "cls": "ALGO"},
    {"id": "S14.1", "title": "Уважение FVG / VI / Gap; ключевые уровни 25/50/75/FF; тела vs тени", "cls": "ALGO"},
    {"id": "S14.2", "title": "Виды неэффективности: FVG, VI, Liquidity Void, Opening Gap, BPR", "cls": "ALGO"},
    {"id": "S15", "title": "Ликвидность: external/internal, пулы (PDH/PDL/PWH/PWL/PMH/PML, session H/L), EQH/EQL, трендовая", "cls": "ALGO"},
    {"id": "S16", "title": "Поток приказов — Order Flow", "cls": "ALGO", "note": "структурний proxy; біржових агресорів/дельти методичка не дає"},
    {"id": "S17", "title": "HRLR / LRLR", "cls": "ALGO", "note": "структурний proxy"},
    {"id": "S18", "title": "Ордер блоки (Order Block): умови, поглощение, по фитилям/по телу", "cls": "ALGO"},
    {"id": "S18.1", "title": "Структура OB: Wick / Open / Mean Threshold; тесты; фрактальность", "cls": "ALGO"},
    {"id": "S18.2", "title": "Агрессивный / консервативный вход от OB", "cls": "ALGO"},
    {"id": "S19", "title": "Брейкер Блок (Breaker Block)", "cls": "ALGO"},
    {"id": "S20", "title": "Митигейшн блок (Mitigation Block)", "cls": "ALGO", "note": "текст і схеми розходяться — два профілі (D-03)"},
    {"id": "S21", "title": "Rejection Block / Wick", "cls": "ALGO"},
    {"id": "S22", "title": "Захват ликвидности (Raid / Sweep / Stop Hunt)", "cls": "ALGO"},
    {"id": "S23", "title": "Ложный пробой — SFP", "cls": "ALGO"},
    {"id": "S24", "title": "STB (sell to buy) / BTS (buy to sell)", "cls": "ALGO"},
    {"id": "S25", "title": "Спонсированная свеча (Sponsored Candle)", "cls": "ALGO", "note": "сторона закриття не уточнена — два варіанти (D-04)"},
    {"id": "S26", "title": "Reversal vs Continuation: два типа сделок", "cls": "ALGO"},
    {"id": "S27", "title": "Торговые сессии, killzones, optimal trader time", "cls": "ALGO", "note": "годинник джерела «UTC+3/KZ» неоднозначний — без торгового gate (D-02)"},
    {"id": "S28", "title": "PO3 / AMD", "cls": "ALGO"},
    {"id": "S29", "title": "Judas Swing / NYM (True Daily Open)", "cls": "ALGO"},
    {"id": "S30", "title": "Как собрать свою торговую систему (чек-лист); Резюмирую", "cls": "CONTEXT"},
    {"id": "S31", "title": "Видеокурс / Telegram / платное обучение / ссылки", "cls": "EXTERNAL", "note": "відео й статті за посиланнями не прочитані — недоступні"},
]

# Розбіжності джерела (фіксуємо, не вирішуємо мовчки)
DISCREPANCIES: List[Dict[str, str]] = [
    {"id": "D-01", "where": "S09.3 / схеми 08–11", "what": "Текст: «BOS = BMS = CHoCH = MSB — одне й те саме», MSB — зміна напрямку, MS/Confirm — оновлення в напрямку тренду. Схеми 08–09 позначають BMS кожен злам максимуму В напрямку тренду, MSS — перший злам захищеного мінімуму проти тренду, Confirm — наступний злам у новому напрямку.",
     "decision": "Реалізовано за схемами: BMS (в напрямку тренду) → MSS (проти, захищений swing) → CONFIRM (оновлення в новому напрямку). Синонім MSB = MSS."},
    {"id": "D-02", "where": "S27 killzones", "what": "Вікна London 03–07, Asia 09–12, NY 14–17, «optimal» 10:00–11:30 / 15:00–17:00 подані як «UTC+3 / KZ». Це не вже сконвертований час Борисполя; не зрозуміло, чи UTC+3 — абсолютне зміщення, чи місцевий час іншого ринку.",
     "decision": "Зберігаємо source-clock як є, показуємо обидві інтерпретації (фіксоване UTC+3 і канонічні NY-вікна) з DST; торгового gate на ці вікна немає, поки автор не уточнить."},
    {"id": "D-03", "where": "S20 / схеми 25–27", "what": "Текст: Mitigation Block — той самий Breaker, але БЕЗ MSS і без зняття ліквідності (продовжує BMS). Схеми 25–27 підписують MSS на MB; відмінність схем 26: BB — «обновили максимум», MB — «нет обновления максимума».",
     "decision": "Два профілі: MB_TEXT і MB_SCHEME; жодного «тихого злиття» MB і BB."},
    {"id": "D-04", "where": "S25 Sponsored Candle", "what": "«Знімає екстремум і закріплюється тілом» — не вказано, з якого боку рівня закривається тіло.",
     "decision": "Два варіанти: SC_RECLAIM (закриття назад за рівнем) і SC_ACCEPT (закриття за рівнем); у READY не використовуються до ручної верифікації."},
    {"id": "D-05", "where": "S09.2 vs існуючий Brain v2.1", "what": "Методичка: swing = 3 свічки (центральна вища за обидві сусідні). Brain v2.1 (office2.features.swings, n=2) використовує 5-свічкові фрактали.",
     "decision": "SMC-детектори використовують n=1 за методичкою; Brain v2.1 не змінюється (різниця фіксується в shadow-порівнянні)."},
    {"id": "D-06", "where": "S10.4 / схема 07", "what": "Range позначається сіткою 0; 0,5; 1 (EQ = 0,5), OTE-сітка — 0; 0,5; 0,62; 0,705; 0,79; 1. Для FVG/OB — 0,25/0,5/0,75.", "decision": "Усі набори рівнів реалізовано окремо за призначенням."},
    {"id": "D-07", "where": "Запит vs документ", "what": "Запит: «41 схема», зокрема окрема схема «Reversal vs Continuation». У Masterplan і docx — 40 зображень (Схема 01…40); схема 40 «Reversal vs Continuation» містить 4 піддіаграми (Reversal LONG/SHORT, Continuation LONG/SHORT). Серед 12 PNG, доданих у розмову раніше, SMC-схем немає (скриншоти Mini App, пошти, Telegram і схема H&S/Flag).",
     "decision": "Прочитано й покрито 40; усі 4 піддіаграми схеми 40 мають тести (Reversal/Continuation × LONG/SHORT). Окремого 41-го файлу в середовищі немає — не вважається прочитаним; після надсилання файлу додається як fixture без зміни коду."},
    {"id": "D-08", "where": "Strong Candle PDF", "what": "PDF описує індикатор/стратегію TradingView (Volume Delta, Supertrend, Fibonacci-сітка); внутрішні алгоритми «сильної свічки» автор не розкриває.", "decision": "Strong Candle лишається EVIDENCE (office2.strongcandle), не READY-ґейтом; формул із PDF не вигадуємо."},
]

# 40 навчальних схем: номер → розділ джерела + що перевіряє fixture
IMAGES: List[Dict[str, Any]] = [
    {"n": 1, "title": "Теханализ и Smart-Money", "section": "S04", "fixture": None, "note": "ілюстрація: класичний ТА як наживка; не алгоритмізується"},
    {"n": 2, "title": "Фазы рынка", "section": "S06", "fixture": None, "note": "падіння → накопичення → ріст → розподіл → падіння; гіпотеза Wyckoff, не детектор READY"},
    {"n": 3, "title": "Рыночный цикл", "section": "S06", "fixture": None, "note": "реальний графік із фазами; якісний приклад"},
    {"n": 4, "title": "Swing", "section": "S10.1", "fixture": "swing_3candle", "note": "3 позитивні + 1 негативний приклад для Swing High/Low"},
    {"n": 5, "title": "Восходящая структура", "section": "S10.2", "fixture": "uptrend_structure"},
    {"n": 6, "title": "Нисходящая структура", "section": "S10.3", "fixture": "downtrend_structure"},
    {"n": 7, "title": "Консолидация — Range (0 / 0,5 / 1, девиация)", "section": "S10.4", "fixture": "range_deviation"},
    {"n": 8, "title": "BMS", "section": "S09.3", "fixture": "bms_chain"},
    {"n": 9, "title": "MSS + Confirm", "section": "S12", "fixture": "mss_confirm"},
    {"n": 10, "title": "MSS: валідний vs «нет обновления максимума»", "section": "S12", "fixture": "mss_valid_vs_invalid"},
    {"n": 11, "title": "Не MSS (корекція в межах розширення)", "section": "S12", "fixture": "not_mss_correction"},
    {"n": 12, "title": "OTE вместе с Ордер Блоком", "section": "S13.1", "fixture": "ote_with_ob"},
    {"n": 13, "title": "Применение объёмов с FVG", "section": "S14", "fixture": "fvg_basic", "note": "профіль обсягів на схемі — OHLC-only FVG не доводить дисбаланс біржового bid/ask"},
    {"n": 14, "title": "Имбаланс: эффективное vs неэффективное ценообразование", "section": "S14", "fixture": "fvg_basic"},
    {"n": 15, "title": "Типы ликвидности (EQH/EQL, Swing, Range, Trendline)", "section": "S15", "fixture": "liquidity_types"},
    {"n": 16, "title": "ORDER FLOW (висхідний/низхідний + FVG)", "section": "S16", "fixture": "order_flow"},
    {"n": 17, "title": "Медвежий Order Flow после смены тренда (POI старшого ТФ: OB+FVG)", "section": "S16", "fixture": "order_flow"},
    {"n": 18, "title": "HRLR и LRLR", "section": "S17", "fixture": "hrlr_lrlr"},
    {"n": 19, "title": "Бычий ордер блок (FVG, біля ключового рівня)", "section": "S18", "fixture": "bull_ob"},
    {"n": 20, "title": "Медвежий ордер блок", "section": "S18", "fixture": "bear_ob"},
    {"n": 21, "title": "Структура блока. Mean Threshold", "section": "S18.1", "fixture": "ob_levels"},
    {"n": 22, "title": "Пример использования Ордер Блока (BSL, 2 OB)", "section": "S18.2", "fixture": "ob_usage"},
    {"n": 23, "title": "Приклад угоди: захват ліквідності → OB → вхід/SL/TP", "section": "S18.2", "fixture": "ob_usage"},
    {"n": 24, "title": "Breaker Block (висхідна й низхідна структура)", "section": "S19", "fixture": "breaker_block"},
    {"n": 25, "title": "Mitigation Block", "section": "S20", "fixture": "mitigation_block"},
    {"n": 26, "title": "Отличие MB от BB (обновили / не обновили максимум)", "section": "S20", "fixture": "mb_vs_bb"},
    {"n": 27, "title": "MB в сочетании с BB", "section": "S20", "fixture": "mb_vs_bb"},
    {"n": 28, "title": "Пример Rejection Block (BSL, FVG, MSS, BMS)", "section": "S21", "fixture": "rejection_block"},
    {"n": 29, "title": "Скріншот TradingView: RJB+ (long, R:R 9,65)", "section": "S21", "fixture": None, "note": "реальний приклад ціни; без OHLC в документі"},
    {"n": 30, "title": "Rejection Block / Wick (бичачий, EQL, SSL, 0,5)", "section": "S21", "fixture": "rejection_block"},
    {"n": 31, "title": "Rejection Block / Wick (ведмежий, EQH, BSL, 0,5)", "section": "S21", "fixture": "rejection_block"},
    {"n": 32, "title": "Захват ликвидности (Stop Hunt / Raid), рух проти тренду", "section": "S22", "fixture": "raid_sweep"},
    {"n": 33, "title": "SFP (Swing Failure Pattern), long і short", "section": "S23", "fixture": "sfp"},
    {"n": 34, "title": "Зоны StB и BtS", "section": "S24", "fixture": "stb_bts"},
    {"n": 35, "title": "Пример Sell to Buy (Breaker + SSL)", "section": "S24", "fixture": "stb_bts"},
    {"n": 36, "title": "Пример Sell to Buy (2 OB, MSS, 0,5)", "section": "S24", "fixture": "stb_bts"},
    {"n": 37, "title": "Пример Buy to Sell (BSL, MSS, OB)", "section": "S24", "fixture": "stb_bts"},
    {"n": 38, "title": "Спонсированная цена / Institutional Sponsorship (FVG, SSL, OB, RJB)", "section": "S25", "fixture": "sponsored_candle"},
    {"n": 39, "title": "REVERSAL TYPE 1 (контекст HTF POI/RAID BSL; без контексту — не шукати вхід)", "section": "S26", "fixture": "reversal_type1"},
    {"n": 40, "title": "Reversal vs Continuation (4 схеми: напрям, RAID, MS, вхід)", "section": "S26", "fixture": "rev_vs_cont"},
]


def section_ids() -> List[str]:
    return [s["id"] for s in SECTIONS]


def get(sid: str) -> Dict[str, Any]:
    return next((s for s in SECTIONS if s["id"] == sid), {"id": sid, "title": "?", "cls": "?"})

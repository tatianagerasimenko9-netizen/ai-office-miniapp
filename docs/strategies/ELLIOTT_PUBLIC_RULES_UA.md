# Хвилі Еліота: публічні правила (ЗОВНІШНЄ) і наша об'єктивна реалізація (23.11.2026)
Статус: за проханням власниці знайдено публічні джерела, НЕ з її матеріалів (див. SOURCE_RULES.md: усе нижче — ЗОВНІШНЄ або ГІПОТЕЗА, спочатку тільки тест на історії/shadow; в бою нічого не вмикати без її «так»).

## Що кажуть джерела
Три «жорсткі» правила імпульсу з 5 хвиль (R.N. Elliott / Frost & Prechter, «Elliott Wave Principle»; цитуються в eSignal, O'Reilly «Mastering Elliott Wave», Nasdaq/StockCharts):
1. Хвиля 2 не відкочується більше ніж на 100% хвилі 1 (не заходить за її початок).
2. Хвиля 3 ніколи не найкоротша серед хвиль 1, 3, 5.
3. Хвиля 4 не заходить у цінову зону хвилі 1 (на ф'ючерсах деякі автори допускають 10–15%; у «кінцевих діагоналях» перекриття дозволено).
Гайдлайни (НЕ правила, джерела розходяться): хвиля 2 часто відкочується на 50–61,8% хвилі 1; хвиля 3 «зазвичай» ≥ 1,618 від хвилі 1 (може 2,618); хвиля 4 — 23,6–38,2–50% від хвилі 3; чергування хвиль 2 і 4.
Джерела: [O'Reilly: A Summary of Rules and Guidelines](https://www.oreilly.com/library/view/mastering-elliott-wave/9781118235157/xhtml/sec18.html) · [Wikipedia: Elliott wave principle](https://en.wikipedia.org/wiki/Elliott_wave_principle) · [eSignal Manual ch9](https://www.esignal.com/publicdocs/eSignal_Manual_ch9.pdf) · [StockCharts: Identifying Elliott Wave Patterns](https://chartschool.stockcharts.com/table-of-contents/market-analysis/elliott-wave-analysis-articles/identifying-elliott-wave-patterns) · [StockCharts: Guidelines for Applying Elliott Wave Theory](https://chartschool.stockcharts.com/table-of-contents/market-analysis/elliott-wave-analysis-articles/guidelines-for-applying-elliott-wave-theory) · [LuxAlgo: Fib wave relationships](https://www.luxalgo.com/library/concept/fib-wave-relationships.md).

## Що кажуть дослідження про прибутковість
Рецензованого бектесту саме Elliott Wave як торгової системи знайти НЕ вдалося (є лише огляди й не-рецензовані). Загальна література з технічного аналізу: багато робіт показують прибуток, але більшість страждає від data snooping; роботи з поправкою на неї (напр. [Wang et al., Cardiff: Illusory Profitability](https://orca.cardiff.ac.uk/66242/1/WangQ%20-%20IllusoryProfitability.pdf)) вважають прибутковість ілюзорною; є й протилежні результати (30 валют, 1971–2015). Висновок: заяви «хвилі Еліота дають гарний результат» НЕ ПІДТВЕРДЖЕНО публічними дослідженнями; перевіряємо самі.

## Чому в СВІНГу Bollinger/RSI2/Donchian, а не хвилі Еліота
Індикатори — формули: однакові дані дають однаковий сигнал. Хвилі Еліота — це розмітка: два аналітики ставлять різні лічильники, а «помилку» завжди можна пояснити «іншим рахунком». Щоб тестувати, потрібна об'єктивна версія. Нижче наша (OUR_IMPLEMENTATION, ГІПОТЕЗА).

## Наша об'єктивна реалізація (scripts: strategy_search/elliott_test.py)
- Пивоти: причинний ATR-зигзаг (поріг K×ATR14, K = 2, 3, 4), пивот видно лише після розвороту на K·ATR (без заглядання вперед).
- Сетап A «вхід у хвилю 3»: LONG після підтвердженого мінімуму P2 при P2>P0 (правило 1); варіанти за глибиною відкату (A0 будь-який, A1 38,2–78,6%, A2 50–61,8%); стоп за P0; ціль P2 + 1,618·(P1−P0). Дзеркально SHORT.
- Сетап B «кінець хвилі 5»: після 5 хвиль угору і виконання правил 1–3 — SHORT; стоп за P5; ціль P4. Контроль — ті самі 5 хвиль з порушенням правил.
- Допущення (не з джерел): сам зигзаг-поріг, цілі/стопи, ліміт утримання (H4 60, D1 30), вхід на відкритті наступного бару.

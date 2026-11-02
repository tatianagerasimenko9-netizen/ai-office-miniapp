# Завдання B12 для ChatGPT (скопіювати власниці → ChatGPT)

Онови main. Прочитай `docs/handoff/br-profitability/KNOWLEDGE_BASE_GAP.md`, `MASTER_CHECKLIST.md` (B12), `COORDINATION.md`, `docs/sources/evidence.jsonl`, `CONFORMITY_2026-10-12.md`.

Контекст результатів Claude (workflow `B&R HTF stop replay`, Actions → summary): стоп за confirmed swing D1/H4/H1 покращує net R (D1 +0.35R, CI [+0.27;+0.44]; сер. −0.18R проти −0.53R), 67% вибитих стопів потім дійшли до TP1 за 24 год — але БЕЗ контролю випадкових моментів і з цензуруванням нерозв'язаних. Поділ у часі додається в тому ж summary.

## Роби (лише файли в `analysis/`, жодних змін live)
1. `analysis/b12_flags.py` з CLI: `python3 analysis/b12_flags.py --plans "<glob psv>" --candles-dir candles --out b12.json` — друкує markdown-таблицю в stdout. Свічки: `candles/{SYM}/{1m,1h,4h,1d}.csv` (open_time секунди, o,h,l,c; M1 з 15.10, H1/H4 з 01.09, D1 з 01.08). Workflow сам запустить його на пуш у `chatgpt/**` (шлях `analysis/**`) і виведе результат у Actions summary — не проси завантажувати свічки.
2. Прапорці на момент `created_ts` БЕЗ майбутніх даних (лише закриті свічки), по кожному плану:
   - `day_used_pct` (G-ATR-DAYUSED): частка ATR доби, використана до сигналу; ATR за джерелом = 3–5 D1 без паранормальних (G-ATR-CALC); бакети <50, 50–75, 75–80, ≥80 (≥80 — поріг із джерела).
   - `htf_level_hit`: рівень сигналу в межах X% (ГІПОТЕЗА, сітка 0.1/0.2/0.3 ATR_H1) від confirmed swing H4 або D1; число торкань.
   - `paranormal_base`: рівень = край бази після паранормального D1-бару ≥2× середнього (G-LVL-PARANORMAL, D-POST-IMPULSE-BASE), якщо визначно за джерелом; інакше null.
   - `sweep_before_retest`: був прокол ліквідності swing перед ретестом (SMC), null якщо неоднозначно.
   - `btc_regime`: тренд BTC (напрям EMA/структури H4) відносно напряму сигналу.
   - `round_number_near_stop` (D-STOP-STRUCTURE / G-LUFT).
3. Для кожного прапорця/бакета: n, кластерів, net R (модель як у `baseline.py`, TP1 і/або стоп за D1-swing), кластерний 95% CI; ранні 60% / пізні 40% за часом; поправка на кількість перевірених гіпотез (Бонферроні). Висновок «підтверджено» лише якщо CI не містить 0 І знак збігається на пізній вибірці. Інакше «НЕ ПІДТВЕРДЖЕНО». Жодних вигаданих порогів: усе поза джерелом = ГІПОТЕЗА.
4. Контроль stop-hunt: частка випадкових моментів (той самий символ/напрям, випадковий час), де після «стопу на такій же відстані» ціна дійшла б до TP1 за 24 год. Порівняй з 67%.
5. Запиши результат у `docs/handoff/br-profitability/STATUS_LOG.md` і `analysis/B12_report.md`. PR відкрий draft; merge робить Claude.

Заборонено: чіпати `office_br/` live-код, гейти, ризик, ордери, Binance-pacing.

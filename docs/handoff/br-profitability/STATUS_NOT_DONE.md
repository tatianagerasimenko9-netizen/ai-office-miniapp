# Стан і не зроблене (02.11.2026)
Злито: milestone-політика (#264, #267), 3-SL→попередження (#265), replay B&R (#266), хибні TP/SL після термінального (#283), зменшення пам'яті (#307, гіпотеза).
Production: Worker `ai-office-miniapp` призупинено Render (OOM 512 MiB crashloop 01.11 + банер «Payment failed») → доки власниця не оновить оплату й не натисне Resume (бажано Standard), B&R нових сигналів не генерує. Дії власниці: оплата, Resume + Manual Deploy (clear build cache), рішення про крипто-сканер PR #6 / etalon PR #1.
B&R: HTF map / LTF-підтвердження — лише shadow-лог, не гейт. Параметри detect.py (pivot_k=3, lookback 96, retest_tol_atr 0.30, sl_buffer_atr 0.10 …) — ГІПОТЕЗА, без змін з 14.10. У БД дублі планів (970 унікальних з 1118) і багато сигналів без результату.
Відкриті PR: #306 (draft, #169), #287, #275, #284, #286, #282, #292, #301 — перевірити актуальність. Червоні CI на main (pre-existing): test_br_live, test_pr45_chart, test_pr_confluence (немає mplfinance).
Сирі дані: `data/br_plans.psv` ще НЕ вивантажено (немає доступу до БД з CI) — виконати `scripts/br_export_handoff.py` з DATABASE_URL.

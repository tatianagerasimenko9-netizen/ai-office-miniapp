# data/ — сирі унікальні плани B&R (дедуп: symbol+dir+created_ts+entry+sl; 970 рядків)
Файли: `br_plans_1_300.psv`, `br_plans_301_600.psv`, `br_plans_601_1118.psv` (за `seq` у `br_test_signal`; seq-пропуски = дублі, прибрані).
Формат (розділювач `|`): `seq|sym|dir|created_ts|entry|sl|targets|events`
- `dir`: L/S. `created_ts` — epoch UTC (сек).
- `targets`: `price:S|R` (S = структурна ціль, R = ціль за R-кратністю), TP1..TP3.
- `events`: `E`=ENTRY, `T1/T2/T3`=торкання цілі, `SL`, `AMB`=SL і ціль в одній свічці; формат `ТИП@(touched_ts − 1790000000)`. Події впорядковано за часом. Порожньо = результату не записано.
- Ціни округлено до 6 (entry/sl) і 5 знаків (цілі). Витрати моделі 0,15%/угоду НЕ закладені в дані.
Джерело: production Postgres, read-only SQL з `../export_br_data.sql` (різниця лише в стислому форматі подій). Зріз знято 02.11.2026 ~14:30 UTC.

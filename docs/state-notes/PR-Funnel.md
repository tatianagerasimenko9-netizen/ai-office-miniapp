# PR-Funnel — RR із структури + воронка скану (2026-10-01)

## Проблема (аудит)
1. TP1 будували рівно на 1,5R брутто, а фінальний гейт рахує RR після комісій (0,10%) → план не міг пройти до READY.
2. Глибокий аналіз бачив ~24 майже статичні монети (26 різних у Лондоні); 8 місць мувер-квоти займали T0-заблоковані монети, Gainers витісняли Losers, після SKIP сценарій губився, відкатів не було.

## Що змінено (пороги НЕ змінено)
- `office_lev_targets.pick_targets`: рівні попереду входу (свінги H1/H4, зони ≥2 торкань, PDH/PWH, Азія; не далі 3×ATR(D1); злиття <0,15%) → перший, що проходить `rr_gate` після комісій; є реальний наступний рівень → TP2 і зважене правило; немає → TP1 ≥ 1,5; інакше SKIP з причиною. Мін. простір до TP1 (1,2% мажори / 3% альти) діє.
- `draft_lev_scenario`/`finalize_lev`/`lev_cycle`: `tp2`, `target_why`, `target_reject`, `draft.rr` = керівний (зважений або net) RR; параметр `target_levels` для тестів/replay.
- `office_scan_funnel`: ротація, квоти (Gainers 5, Losers 5, обсяг 4, спостереження 6, відкат до 6, ротація ≥10), кеп 36 (`OFFICE_SCOUT_DEEP_CAP`); PULLBACK WATCH; `direction_gate`+`reversal_confirmed` (CHoCH на закритих H1); збереження/відновлення з БД.
- Relay: скаут використовує воронку; T0/Gerchik-SKIP після сильного руху → реєстр; напрям проти імпульсу без CHoCH → WATCHING без запису; `tp2` у відправку й lev-watch.
- Replay: V0_current тепер = TP зі структури (як у чинній логіці).

## Тести
`scripts/test_lev_targets.py`, `test_scan_funnel.py`, `test_funnel_check.py`; оновлено `test_lev_analyst_first.py`.

## Shadow на production
Одноразово через ~11 хв після старту worker: `LAUNCH_DIAG` задачі `funnel_ready_path`, `funnel_check`, `funnel_deep_pass`.

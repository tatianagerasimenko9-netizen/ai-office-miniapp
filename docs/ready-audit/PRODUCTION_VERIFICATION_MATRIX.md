# Матриця production-перевірки (оновлено 2026-10-04 22:30 UTC / 01:30 Київ)

Правило: «production verified» = код на production + натуральна подія (не лише зелені тести). Нуль подій / нуль порівнянь = **НЕ ПЕРЕВІРЕНО**.
Колонки: UNIT = локальні тести, CI = GitHub Actions, DEPLOYED = версія в `[boot] git_sha`, NATURAL = натуральна production-подія, MOBILE = перевірено на телефоні власницею.

| Функція | UNIT | CI | DEPLOYED | NATURAL | MOBILE | Статус | Примітки |
|---|---|---|---|---|---|---|---|
| #118 зона входу = зона сетапу | ✅ | ✅ | ✅ | ✅ SAMSUNG, DASH, ETC, MARSCOIN, LDO | ✅ | VERIFIED | |
| #119 заморожена картка, докази → PNG, sha | ✅ | ✅ | ✅ | ✅ ETC, MARSCOIN, LDO (sha збігається, evidence_verify ok) | ✅ iPhone | VERIFIED (основне) | LIVE-канал Mini App — окремий баг, див. #121 |
| #120 provenance свічок + double/triple докази + `evidence_unsupported` | ✅ | ✅ | ✅ `eb7f277` | ❌ ще не було READY після deploy | ❌ | DEPLOYED, НЕ ПЕРЕВІРЕНО | чекати натуральний READY |
| #121 канал у Mini App | ✅ (джерело HTML + API) | ✅ | ✅ `38c28a0` | ❌ | ❌ | DEPLOYED, НЕ ПЕРЕВІРЕНО | потрібен погляд на ETC/MARSCOIN/LDO у Mini App |
| #122 READY лише на Futures-свічках | ✅ | ✅ | ✅ `f10b26f` | ❌ | — | DEPLOYED, НЕ ПЕРЕВІРЕНО | натуральна подія = `READY_HELD_NON_FUTURES` у журналі |
| #123 «Схоже на…» (Telegram) + примітка (Mini App) | ✅ | ✅ | ✅ (в `main` після #122) | ❌ | ❌ | DEPLOYED, НЕ ПЕРЕВІРЕНО | перший READY із фігурою |
| #124 вимір WS-miss і callers | ✅ | ✅ | ✅ `f48e7a9` | ⏳ збір ≥25 хв | — | У ПРОЦЕСІ | звіт 22:57 UTC |
| #116 WS-тикер | ✅ | ✅ | ✅ | ✅ | — | ПРАЦЮЄ, ефект −11% REST, оптимізація НЕПОВНА | ticker/24hr 207/цикл, 1m ≈18/хв, 15m ≈26/хв |
| Lifecycle TP/SL ≤90 с | ✅ | ✅ | ✅ | ⚠ ALGO SL: 44–104 с | — | **НЕ ПЕРЕВІРЕНО** (≤90 с не доведено) | потрібні натуральні ENTRY/TP1/TP2/TP3/SL |
| EXPIRED | ✅ | ✅ | ✅ | ❌ | — | НЕ ПЕРЕВІРЕНО | |
| INVALIDATED | ✅ | ✅ | ✅ | ❌ | — | НЕ ПЕРЕВІРЕНО | |
| «План призупинено» | ✅ | ✅ | ✅ | ❌ | — | НЕ ПЕРЕВІРЕНО | |
| Звірка snapshot OHLC з архівом Binance | ✅ скрипт | ✅ | — | ❌ 0 порівнянь | — | **НЕ ПЕРЕВІРЕНО** (0 порівнянь ≠ PASS) | архів дня ще недоступний |
| LRC паритет Pine ↔ Office | ✅ | ✅ (real Binance) | n/a | n/a | n/a | MATH VERIFIED (≈2,8e-12) | торгова роль каналу не підтверджена |
| Pattern Engine 2.0 (Bulkowski) | ❌ | ❌ | ❌ | ❌ | — | НЕ ПОЧАТО (джерело недоступне з sandbox) | старі детектори = «схоже на», не доведені |
| Wyckoff (повний) | — | — | — | — | — | НЕ РЕАЛІЗОВАНО | лише spring/upthrust, див. AUDIT_WYCKOFF |
| SMC/ICT | ✅ | ✅ | ✅ | ✅ теги в READY | — | ПРАЦЮЄ, є семантичні ризики | див. AUDIT_SMC_ICT |
| HTF-контекст (MN/W/4D/3D) | — | — | — | — | — | ВІДСУТНІЙ у lev-потоці | див. GAP_AUDIT |

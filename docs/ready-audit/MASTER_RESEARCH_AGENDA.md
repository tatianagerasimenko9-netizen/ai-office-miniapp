# Master-план досліджень Office (зафіксовано 2026-10-05 00:30 UTC / 03:30 Київ)

Правило: дослідження / replay / shadow — без окремого дозволу; **production trading logic не змінювати** до цифр ДО/ПІСЛЯ і конкретної пропозиції (тоді потрібне рішення власниці). Статуси: ✅ зроблено · 🟡 частково · ⏳ у процесі · ⬜ не починалось. «Немає даних = не перевірено».

| № | Тема | Статус | Де / що далі |
|---|---|---|---|
| 1 | Якість READY — P0: звірка БД ↔ snapshot ↔ lifecycle ↔ Telegram, строгий replay | 🟡 | `READY_QUALITY_FINDINGS.md` (24 год N=608: TP1-first 26,0%, SL 63,8%; серед вирішених 28,9% проти бази 28,4%). Повторити на 4 жовтня та наступних днях; «10 SL» у Telegram не WR |
| 2 | Stop Engine: ланцюг інвалідація → рівень → ліквідність → sweep → ATR → люфт → SL → розмір | ⏳ | `scripts/ready_stop_research.py` (після SL, геометрія проти блукання, альтернативні стопи при незмінному $ ризику, train/test). Далі: ліквідність/BSL/SSL у виборі стопу |
| 3 | Position sizing: notional = risk$ / stop distance (+fees/slippage/funding) | 🟡 | враховано в R-обліку replay (комісія 0,1%); slippage/funding не моделювались |
| 4 | Ліквідність і люфт (круглі числа, EQH/EQL, BSL/SSL, PDH/PDL/PWH/PWL/PMH/PML, session H/L, swing, liquidation clusters); люфт evidence-based, без константи ±0,2% | ⬜ | залежить від п.2; потрібні історичні кластери ліквідацій |
| 5 | HTF-ієрархія Month→M1; «НЕ АНАЛІЗУВАВСЯ», а не neutral | 🟡 | `GAP_AUDIT_DESIGNED_VS_PRODUCTION.md`; у lev-потоці немає W/Month/3D/4D |
| 6 | Levels / Gerchik (справжній mirror, touch/retest/reaction, вік, HTF-значущість) | 🟡 | `AUDIT_LEVELS.md` (mirror = середина вчорашнього дня ±0,2%, не Герчик); формальний детектор — не розпочато |
| 7 | SMC/ICT формалізація | 🟡 | `AUDIT_SMC_ICT.md` (CHoCH при trend=None; CHoCH від останнього свінга; OTE без напрямку ноги, відтворено запуском) |
| 8 | Фрактали + OTE/Fibonacci (impulse start/end, напрям ноги) | 🟡 | фрактал K=2 уже в `ready_stop_research.py` як спосіб визначення свінга; OTE — далі |
| 9 | Дивергенції (regular/hidden; Week/D1/H4/H1 + M15/M5/M1; RSI, CVD, OI) | ⬜ | |
| 10 | CVD / volume / order flow (CVD-дивергенція, absorption, exhaustion) | ⬜ | потрібні aggTrades-дані (архів Binance доступний у CI) |
| 11 | DOM / стакан / кластери / великі гравці (walls, spoofing) | ⬜ | `depth` в Office вимкнений (`OFFICE_DEPTH`, авто-вмикання за 24 год стабільності) |
| 12 | Liquidation heatmap: кластери + відстань, magnet → sweep → reclaim | ⬜ | є `LIQ_MAP`/`BTC_FORCE_ORDERS` у БД (з 25–30.09) |
| 13 | OI / funding / long-short: price×OI, OI acceleration; funding і L:S не самостійні | ⬜ | |
| 14 | Options/GEX BTC/ETH: страйки, експірація, gamma flip як context/pressure | ⬜ | потрібне джерело даних (без платних ключів — перевірити публічні) |
| 15 | Market context: BTC/ETH, dominance, капіталізація, breadth, coin-vs-BTC/market, сесії | 🟡 | BTC 4 год проти напряму: 18% TP1 / 72% SL проти 27% / 63% за напрямом (24 год); без hard-block; розширити вибірку |
| 16 | Super POI — лише прозорий confluence, без непрозорого score | ⬜ | |
| 17 | Macro/calendar: Forex Factory як додаткове джерело, cross-check; у Telegram лише actionable window | ⬜ | |
| 18 | Pattern Engine 2.0: swings → geometry → formal criteria → name; Bulkowski без gate power до validation | 🟡 | `docs/pattern-engine/AUDIT_*`; у production формулювання «Схоже на…» (#123); джерело Bulkowski недоступне з sandbox |
| 19 | Цільова архітектура: HTF → LEVELS → LIQUIDITY → ZONE → BEHAVIOR → MONEY FLOW → TRIGGER → INVALIDATION+BUFFER → RR → SIZE → READY; ваги лише після replay/train-test/regime split/shadow | ⬜ | shadow Office 2.0 після п.1–5 |
| 20 | Thesis ↔ READY: READY не привʼязаний до тези, `office_market_thesis.check` не в ланцюжку | ✅ факт, ⬜ архітектура | `VERSION_CHAIN_APT_BCH.md`; кількісно: **195 із 1414 READY (13,8%) видані після закінчення останньої версії тези, 170 із них >60 хв після**; медіана віку тези на момент READY 11 хв. Привʼязку проєктувати в shadow |
| 21 | MERL: нова ідея після вже зафіксованого SL попередньої; dedup / identity / cooldown / re-entry | 🟡 факт | MERL `…8289eae821373953`: 3 SIGNAL_PLAN (11:14 без доставки, 12:10 mid 9711, 17:35 mid 9792) і SL між ними; перевірити політику повторної видачі в replay; не латати |
| 22 | BTC alignment (18%/72% vs 27%/63%) на більшій вибірці/режимах; не hard-block | 🟡 | входить у зрізи `ready_stop_research.py` |
| 23 | Підтвердження #120–#125 | 🟡 | #120 ✅ (POL/ALICE/BNB); #121 канал бачили на BCH/APT (власниця); #123 wording видно; **#122 Futures-only без натуральної події**; #125 — контрольний замір ≥25 хв о 00:52 UTC |
| 24 | REST/WS: baseline #124; stale WS ↔ свіжий REST до зміни TTL; далі `monitor_trade_radar`, `pending_milestones` | 🟡 | `REST_LOAD_AUDIT.md`; TTL не міняти |
| 25 | Telegram коротко / Mini App детально; frozen snapshot не переписувати; картинка = докази | ✅ принцип | не переробляти |
| 26 | Scenario ≠ моя угода; усі READY для статистики; SL сценарію ≠ мій збиток | ✅ принцип | у звітах «SL сценарію» |
| 27 | Не змінювати без доказів: ATR/RR/SL/TP/risk/position, gate, кількість confirmations, HTF hard filters, phase hard-blocks, pattern/channel gate power, lifecycle, кнопка | ✅ | |
| 28 | Порядок: #125 замір → replay 4 жовтня з gate-ознаками → MFE/MAE і after-SL → Stop/Liquidity/Buffer → GAP → Data&Edge → Office 2.0/Brain/Pattern shadow | ⏳ | |

## Поточні кількісні опорні точки
- 24 год (N=608): TP1 першим 26,0%, SL першим 63,8%, нічого 10,2%; серед вирішених 28,9% проти 28,4% бази «блукання без зносу».
- Стоп <1,12%: 11% TP1 / 77% SL; ≥2,22%: 36% / 51%; TP1/стоп ≥4,3: 10% / 81% — треба розрізнити геометрію й дефект (`ready_stop_research.py`, розділ 2).
- Gate-ознаки збережені лише для 41 плану 4 жовтня; 326 планів 4 жовтня чекають архіву доби.


## Доповнення 05.10 (повтори, дублікати, lifecycle)
| Пункт | Статус |
|---|---|
| Повторні READY після SL (ланцюги symbol→direction→idea→outcome→next) | ЧАСТКОВО: `ready_repeat_audit.py`, 92/204 пар мають ≥2 READY (71% READY); «після SL» 1/23 TP проти «перша» 21/119 — не доведено; потрібен structural-reset у знімку |
| Літеральні дублі / дубль доставки / дубль lifecycle | ЗРОБЛЕНО (діагноз): IO = дубль Telegram-доставки (порожній `photo send failed` → запасна Telethon-відправка); KAITO = дві різні ідеї (одна в позиції); SIGNAL_RESULT «конфлікти» = змішування з rejected=true; MERL і SOXS/NVDA літеральні — відкриті |
| Три зрізи статистики (усі / перша на idea / незалежна) | ЧАСТКОВО (проксі), фікс. горизонт 12 год |
| READY при відкритій попередній ідеї (KAITO) | ВІДКРИТО: причина обходу «дубль незавершеної ідеї» не знайдена |
| Короткі стопи: stop%/ATR15/ATR1h, 3/6/12/24 год | ЧАСТКОВО (72 плани, цензурування); гіпотеза: `min_tp1_pct=3%` + вузький стоп = завищений RR |
| Два симулятори (1m lifecycle проти 15m SIGNAL_RESULT) | ЗНАЙДЕНО: клас збігається 43/43, час входу/результату розходиться на 4 планах |
| КОРЕКЦІЯ 05.10 (5 діб, 1476 READY): «після SL 4%» не підтвердилось | після SL 16% проти 19% першої (12 год: 5% проти 8%); залежності від часу після SL немає; кандидат — «той самий рівень SL» (0/18 за 24 год, N=39) для shadow; 90% READY — у парах з ≥2 READY |
| RR/геометрія на всій вибірці | ЗРОБЛЕНО (описово): факт TP1-first нижчий за базу блукання на ≈10 п.п. у всіх групах RR; RR>10 — 0/38; стоп ≥4% — на рівні бази; нестабільно в часі; причини дефіциту не розділені (симулятор/дрейф/відбір) |
| Structural reset | ВИЗНАЧЕНО формально (docs, п.6 REPEAT_DUPLICATES_AUDIT); не обчислювано зараз — потрібне поле у знімку або 1m-реконструкція |

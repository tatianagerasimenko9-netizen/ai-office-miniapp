# 23. AI Office vs scanner_bot (My Crypto Scanner)

`scanner_bot` / `file-1.py.py` / `2scanner_bot_1.py` **немає в цьому репозиторії**. Ядро за правилами офісу **не змінюють**. Докази — sidecar-код і два різні Telegram-експорти.

## Хто що робить

| | My Crypto Scanner (`file-1` на ПК Тетяни) | AI Office (це репо) |
|--|-------------------------------------------|---------------------|
| Канал | «My Crypto Scanner» (HTML квітень–серпень) | Група «AI Office» (JSON травень–вересень) |
| Формує картку LONG/SHORT/TP/SL | Сканер сам | Офіс **розбирає** чужий текст **або** пише свій LLM-текст |
| Дозволяє «угоду» столу | Власні ліміти 6%, пауза N SL | `office_handle_signal` → SKIP/ENTER; kill zone; Дарина |
| Чи може сканер постити після NO TRADE офісу | **Так** — окремий процес, окремий чат | Офіс не зупиняє `file-1` |
| Спільна БД статусів | Ні (журнал сканера в його повідомленнях) | `office_signals` / `trade_journal` |
| Синхрон TP/SL | Повідомлення `*SL*` / `*TP*` у каналі сканера | HIT_TP у `office_signals` якщо офіс сам вів рядок |

## Як вони стикуються в коді офісу (CONFIRMED)

1. **SOURCE → MAIN** (`office_relay_wizard.py` ~2907–2914): якщо `SOURCE_CHAT_ID` і `looks_like_signal` — форвард тексту в MAIN. Ядро сканера не чіпають.  
2. **MAIN handler** (~2935–3024): `OFFICE_SIGNAL_SOURCE_BOT_IDS` / username → `from_scanner=True`. Дзеркало в OFFICE: «Новий сигнал від My Crypto Scanner». Далі `parse_signal` + **`office_handle_signal`**.  
3. **Verdict ENTER** → in-memory `active_positions` + журнал. **SKIP** (kill zone, circuit, REJECTED) — офіс не входить. Сканер у своєму каналі вже міг написати «ВХОДЬ».  
4. **Офісний чат** з тікером `Btc` йде в `full_auto_analysis`, **не** в `office_handle_signal`. Тому NO TRADE Лева в групі **не** є командою сканеру.

## Чи може бот діяти всупереч NO TRADE?

**Так, сканер може.** NO TRADE / SKIP — рішення **офісу** по скопійованому або проактивному сетапу. `file-1` лишається автономним видавцем карток (у HTML-експорті: сотні карток, денний стоп 6%, wick SL).

**Офісний проактивний сканер** (інший!) при `has_edge=False` або словах пропуск — не шле ENTER, може тихий WATCHING. Це не `file-1`.

## Результати

Два журнали. HTML сканера має власні ПІДСУМОК дня. Група офісу — `Угод: 0` і мета «39 expired». Змішувати PnL **заборонено** (вже в `15_STATISTICS.md`).

У групі офісу вставок «Сигнал бота» ≈ 3 — рідко `/review` руками, окремого intent немає → ризик сприйняти як позицію.

## Висновок

Офіс задуманий як **sidecar-рев’ю** чужого сканера + власний LLM-desk. Зараз це **два незв’язані стани**. Office 2.0: один стан (SCANNER: ACCEPT/IGNORE vs OFFICE: SIGNAL/NO_TRADE) або свідомий розрив «сканер = сировина, офіс = дозвіл».

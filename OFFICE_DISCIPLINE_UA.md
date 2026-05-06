# Discipline Pack (MASTER п.36)

Короткий «проп-фірм» шар поверх журналу й офісу: **не замінює** ризик-вето Дарини й фінал Лева, а додає процесні тригери.

## Що вже в коді

1. **`OFFICE_DISCIPLINE_REVIEW_EVERY`** (relay/bridge): якщо задано ціле `N ≥ 2`, після кожних `N` **закритих** угод у `trade_journal` при новому сигналі офіс отримує нагадування про обов’язковий міні-review перед наступним входом.
2. **Circuit breaker** (п.31): серія SL — окреме правило в `office_bridge.py` (`OFFICE_CIRCUIT_LOSSES`, `OFFICE_CIRCUIT_DISABLE`).
3. **Risk committee** (п.30): relay шле один пост на день при порозі денних LOSS або серії SL (`OFFICE_RISK_COMMITTEE_*` у `RUNBOOK_UA.md`).

## Рекомендована поведінка команди

- Перед входом після nudge: 1–2 речення — що повторюється, що змінити в сетапі або в розмірі ризику.
- Не розширювати трейд «щоб відігратися» після серії SL — спочатку розбір (той самий circuit breaker / risk committee).

## Зв’язок з правилами

Деталі ролей і тону — `OFFICE_RULES_UA.md` та `OFFICE_PERSONA_PACK_UA.md`.

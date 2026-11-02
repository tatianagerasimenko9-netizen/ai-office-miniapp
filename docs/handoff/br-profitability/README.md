# B&R profitability — handoff (читати першим)

**Короткий промпт для ChatGPT (скопіювати):**
> Прочитай репозиторій tatianagerasimenko9-netizen/ai-office-miniapp, гілка main, папку `docs/handoff/br-profitability/`. Працюй за `MASTER_CHECKLIST.md` і `CONTROL_PROTOCOL.md`, повне завдання — `PROMPT_FOR_CHATGPT.md`. Кожен пункт чеклиста закривай файлами/PR з ID у назві коміту й доказом; нічого не пропускай; Claude перевіряє кожен коміт. Поверни звіт у форматі з розділу «Формат звіту».

Файли:
- `MASTER_CHECKLIST.md` — усе, що просила власниця, зі статусами, критеріями приймання і дедлайном 19:00 Київ 02.11.2026.
- `CONTROL_PROTOCOL.md` — як Claude перевіряє роботу; `STATUS_LOG.md` — журнал перевірок.
- `PROMPT_FOR_CHATGPT.md` — повне аналітичне завдання (сесії/години, новини, стопи за структурою старшого ТФ, контролі, holdout). Пріоритет сьогодні: A4, A5, A7 з чеклиста.
- `FINDINGS_SO_FAR.md`, `STATUS_NOT_DONE.md`, `OWNER_REQUESTS_STATUS.md`, `UNIVERSE_GAP.md`, `SHADOW_PLAN.md` — контекст.
- `export_br_data.sql` + `scripts/br_export_handoff.py` — вивантаження сирих даних (результат: `data/br_plans.psv`).

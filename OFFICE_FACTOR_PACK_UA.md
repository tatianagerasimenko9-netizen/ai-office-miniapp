# Factor Pack v2 — єдиний знімок факторів

**Код:** `office_factor_pack.py` (`FactorPackV2`, `build_factor_pack_from_desk_inputs`).  
**Дані зараз:** Binance Futures `24hr ticker` + `premiumIndex` (funding, mark/index).  
**Оновлено:** 2026-05-06  

## Поля (канон)

| Група | Поля | Джерело зараз |
|-------|------|----------------|
| Funding / ціна | `funding_rate_pct`, `mark_price`, `index_price` | premiumIndex |
| Ліквідність | `liquidity_quote_usdt_24h`, `liquidity_tier` | 24h quote volume |
| Волатильність | `atr_pct_proxy`, `hl_range_pct` | HL діапазон із ticker |
| Контекст | `btc_relative_strength_pct`, `regime`, `session_hint` | desk-евристики |
| ICT/SMC (зарезервовано) | `fvg_state`, `order_block_state`, `bollinger_state`, `ict_smc_tags` | поки `unknown`/теги режиму |
| Рівні (зарезервовано) | `mirror_level_hint`, `ote_zone_near`, `equilibrium_near` | None доки немає графіка |
| Геп | `gap_session_pct` | None доки немає окремого feed |
| Якість | `sources`, `notes` | список API |

Пусті поля **не вигадуються** — агенти беруть лише те, що є в `factor_pack_v2` або в тексті сигналу.

## Де з’являється

- `!ask` / desk: `build_desk_market_snapshot` додає `factor_pack_v2` у знімок; блок у **Задачнику** показує funding + tier.
- `office_desk_user_question`: у `OfficeSignal.meta["factor_pack_v2"]` для логів і майбутнього використання в промптах.

## Наступні кроки (не в цьому коміті)

- Підключити funding з інших бірж / aggregate — розширити `sources`.
- Знімання з графіка (FVG/OB) — окремий сервіс або ручні поля в сигналі → запис у `meta`.

# SMC — карта методу

Джерела: `sources/SMC_FULL.txt` (SM Trader, 20.03.2026), 40 схем SM Trader (#303–343), рукописні схеми kavya_thetrader (#66–98), SMC_CONTENTS_LINKS (посилання не відкривались). Окремо від Дарії та Герчика.

## Що в джерелі підтверджено
Swing = 3 свічки; HH/HL/LH/LL; BMS/MSB/MSS/Confirm (зміна без оновлення протилежного екстремуму — складна корекція); Range 0/0,5/1 + девіація; Premium/Discount; OTE 0,5/0,62/0,705/0,79; FVG-рівні 0,25/0,5/0,75/FF; OB: Wick/Open/MT(50% тіла), блок працює до закріплення ТІЛАМИ за MT; агресивний/консервативний вхід; ліквідність (BSL/SSL, EQH/EQL), sweep/SFP; Breaker/Mitigation/Rejection/StB/BtS; reversal vs continuation (контекст HTF); killzones і NYM (годинник «UTC+3/KZ» неоднозначний); ризик 0,5–1%/угоду, після 2 SL — пауза.

## Чого немає в джерелі
Числових порогів «сильного імпульсу», проколу, EQH-допуску, тривалості range — усі такі значення в `office2/smc/*` є `OUR_IMPLEMENTATION` (див. `docs/office2/SMC_RULES.md` — позначити). Біржових агресорів/дельти методичка не дає.

## Реалізація
`office2/smc/*` (shadow), реєстр розділів `office2/smc/sources.py`, матриця `docs/office2/SMC_MATRIX.md`.

# 14. Патерни (Bulkowski / Gerchik / SMC)

## Gerchik

- Конспект + `office_gerchik_kernel.py`.  
- `GERCHIK_KERNEL` у `LEV_RULE`, `DESK_BASE_RULE`, `MARICHKA_RULE`.  
- `compute_gerchik_ops()` 0–10: сканер skip ≤4; Дарина veto в desk-path.

Це **скоринг евристик**, не live pattern detector.

## Bulkowski

- Індекс архіву в бібліотеці.  
- `BULKOWSKI_KERNEL` **тільки Марічка**.  
- Немає функції «знайшов Double Bottom → рівень → статистика → setup engine».  
- У чаті ризик лекцій «за книгою» саме через цей промпт + довгі домашки.

## SMC/ICT

Tools: OTE, FVG, OB, PD array, sweep 1h, session levels. Грубі евристики на свічках.

## PRINCIPLE theory→backtest→rule

**ABSENT** як конвеєр. Правила живуть у промптах і константах (85, ATR 80/90) **без** історичного expectancy.

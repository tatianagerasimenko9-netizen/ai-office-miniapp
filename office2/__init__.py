"""Office 2.0 — SHADOW/REPLAY (research-only).

Повний торговий pipeline зверху вниз, який ніколи не імпортується з production і нічого не відправляє:
HTF regime → BTC/market → key levels/liquidity → setup zone → reaction (sweep+reclaim) → structure (CHoCH) → money flow →
LTF trigger → structural invalidation + buffer → TP (наступна ліквідність) → фіксований $-ризик → портфельний ризик → READY2.

Правила:
  * лише закриті бари на момент рішення (без lookahead; перевіряється тестом усічення даних);
  * кожен етап — окремий фільтр із абляцією на train/test проти геометричної бази r/(r+t);
  * параметри задані ЗАЗДАЛЕГІДЬ (не підбираються на test).
"""

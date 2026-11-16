"""Картка-пам'ятка власниці (дні, час за Києвом, що означають сигнали). Дані — IMPROVEMENTS_LOG_UA.md, розділи J, K."""
import sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
out = sys.argv[1]
BG, TXT, MUT = "#101418", "#f2f4f7", "#9aa4b2"; YEL, BLU, GRN, RED, ORG = "#ffd500", "#0057b7", "#2ecc71", "#ff5a5f", "#f5a524"
fig = plt.figure(figsize=(7.2, 14.8), dpi=150, facecolor=BG); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(205, 0); ax.axis("off")
def t(x, y, s, size=13, c=TXT, w="normal", ha="left"): ax.text(x, y, s, color=c, fontsize=size, fontweight=w, ha=ha, va="center")
def box(y, h, c): ax.add_patch(FancyBboxPatch((4, y), 92, h, boxstyle="round,pad=0,rounding_size=1.5", fc=c, ec="none"))
ax.add_patch(Rectangle((0, 0), 100, 12, fc=BLU)); ax.add_patch(Rectangle((0, 0), 100, 6, fc=YEL))
t(5, 3, "ПАМ'ЯТКА · СИГНАЛИ", 17, "#2a2200", "bold"); t(5, 9, "час за Києвом · СВІНГ на історії 2022–2026", 11, "#ffffff")
y = 16; t(5, y, "ДНІ ТИЖНЯ (СВІНГ, $ на угоду)", 13, YEL, "bold"); y += 4
days = [("Пн", .19), ("Вт", 1.69), ("Ср", 3.08), ("Чт", 2.36), ("Пт", 2.13), ("Сб", -.02), ("Нд", 1.71)]
box(y, 17, "#1b222b")
for i, (n, v) in enumerate(days):
    x = 6 + i * 13.1; t(x + 5.5, y + 3.5, n, 13, TXT, "bold", "center")
    col = GRN if v >= 1.5 else (ORG if v > 0.1 else MUT); t(x + 5.5, y + 10.5, (f"+${v:.2f}" if v >= 0 else f"−${-v:.2f}"), 11.5, col, "bold", "center")
    ax.add_patch(Rectangle((x + 1.5, y + 14.2), 8 * max(v, 0) / 3.1, 1.6, fc=col, ec="none"))
y += 22; t(5, y, "Найкращі: Вт · Ср · Чт · Пт.   Пн і Сб — майже нуль (не мінус): сигнал не пропускаємо.", 10.2, MUT); 
y += 8; t(5, y, "ГОДИНИ ВХОДУ (за Києвом, зима UTC+2)", 13, YEL, "bold"); y += 4
hrs = [("02–06", 1.42), ("06–10", .53), ("10–14", .75), ("14–18", 2.37), ("18–22", 2.46), ("22–02", 1.61)]
box(y, 17, "#1b222b")
for i, (n, v) in enumerate(hrs):
    x = 6 + i * 15.3; t(x + 6.5, y + 3.5, n, 12, TXT, "bold", "center")
    col = GRN if v >= 2 else (ORG if v >= 1 else MUT); t(x + 6.5, y + 10.5, (f"+${v:.2f}" if v >= 0 else f"−${-v:.2f}"), 11.5, col, "bold", "center")
    ax.add_patch(Rectangle((x + 1.5, y + 14.2), 10 * v / 2.5, 1.6, fc=col, ec="none"))
y += 22; t(5, y, "Найкраще: 14:00–22:00.  Слабше: 06:00–14:00.  Влітку (UTC+3) +1 година.", 10.2, MUT)
y += 8; t(5, y, "МІСЯЦІ", 13, YEL, "bold"); y += 4; box(y, 14, "#1b222b")
t(8, y + 4.2, "Березень і грудень — у мінусі в обох половинах історії.", 10.8, RED, "bold"); t(8, y + 9.6, "Найкращі: травень, червень, листопад. Решта здебільшого в плюсі.", 10.8, TXT)
y += 20; t(5, y, "ЯК ЧИТАТИ СИГНАЛИ", 13, YEL, "bold"); y += 4
items = [("🟨" , "ІНТРАДЕЙ", "угоди до 2 діб · шапка жовта", YEL), ("🟦", "СВІНГ", "угоди до 10 діб · шапка синя", "#4d9bff")]
for _, n, d, c in items:
    box(y, 9, "#1b222b"); ax.add_patch(Rectangle((4, y), 3, 9, fc=c, ec="none")); t(9, y + 4.5, n, 12, c, "bold"); t(33, y + 4.5, d, 10.5, TXT); y += 11
box(y, 38, "#1b222b"); t(8, y + 4, "Пункти під карткою (лише підказка, нічого не блокують):", 10.6, ORG, "bold")
for k, s in enumerate(["«Слабкий сигнал» — є близький рівень, малий стоп, ринок проти.", "«Обережно» — акція/нафта в СВІНГу (мало історії), новини.", "«На тесті слабше» — AI Office: LONG при падінні BTC, Лондон.", "«новини» — важлива подія календаря в найближчі 12 год."]):
    t(8, y + 10 + k * 6.3, "• " + s, 10, TXT)
y += 42; box(y, 22, "#1b222b"); t(8, y + 4, "Правила (не змінювати без вашого рішення):", 10.8, GRN, "bold")
for k, s in enumerate(["Вхід лімітом, стоп і ціль — на біржі. Ризик $10 на угоду.", "Сума позиції вже на картці: «Відкрий на $…».", "Усі дні й години в плюсі — сигнали не пропускаємо."]):
    t(8, y + 9.5 + k * 4.2, "• " + s, 10, TXT)
y += 28; t(50, y, "Це спостереження на історії, не гарантія прибутку.", 9.5, MUT, ha="center")
fig.savefig(out, facecolor=BG); print("saved", out)

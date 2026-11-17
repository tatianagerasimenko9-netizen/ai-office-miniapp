"""МАКЕТ «Табло СВІНГ» (цифри умовні, лише показати вигляд)."""
import sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
BG, CARD, TXT, MUT, YEL, BLU, GRN, RED = "#101418", "#1b222b", "#f2f4f7", "#9aa4b2", "#ffd500", "#0057b7", "#2ecc71", "#ff5a5f"
rows = [("GALA", "▼", 2, +1.4, ""), ("ICP", "▼", 2, -0.3, ""), ("ATOM", "▼", 3, +2.2, "стоп → беззбиток 2,34"), ("NATGAS", "▲", 1, +0.1, ""), ("BZ", "▼", 1, -0.6, ""), ("CL", "▼", 1, -0.2, ""),
        ("UNI", "▲", 6, +0.8, ""), ("XLM", "▲", 8, +3.1, "стоп → беззбиток 0,2891"), ("RUNE", "▼", 9, +0.5, "завтра закриття за часом")]
fig = plt.figure(figsize=(7.2, 14.0), dpi=150, facecolor=BG); ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(190, 0); ax.axis("off")
def t(x, y, s, size=12, c=TXT, w="normal", ha="left"): ax.text(x, y, s, color=c, fontsize=size, fontweight=w, ha=ha, va="center")
ax.add_patch(Rectangle((0, 0), 100, 12, fc=BLU)); ax.add_patch(Rectangle((0, 0), 100, 6, fc=YEL)); t(5, 3, "СВІНГ · ТАБЛО", 17, "#2a2200", "bold"); t(5, 9, "МАКЕТ · цифри умовні · щодня о 09:00 за Києвом", 10.5, "#ffffff")
y = 15
for i, (v, l, c) in enumerate([("9", "відкрито", TXT), ("+$62", "зараз у плюсі", GRN), ("3", "стопів поспіль", RED), ("+$118", "за тиждень", GRN)]):
    x = 4 + i * 23.2; ax.add_patch(FancyBboxPatch((x, y), 21.5, 14, boxstyle="round,pad=0,rounding_size=1.2", fc=CARD, ec="none")); t(x + 10.7, y + 5.3, v, 17, c, "bold", "center"); t(x + 10.7, y + 10.8, l, 9, MUT, ha="center")
y += 19; t(5, y, "ВІДКРИТІ ЗАРАЗ (кожна монета — окремий рядок)", 11.5, YEL, "bold"); y += 4
for sym, d, day, r, note in rows:
    ax.add_patch(FancyBboxPatch((4, y), 92, 11.5, boxstyle="round,pad=0,rounding_size=1.2", fc=CARD, ec="none"))
    col = GRN if r >= 0.3 else (RED if r <= -0.3 else MUT); ax.add_patch(Rectangle((4, y), 1.6, 11.5, fc=col, ec="none"))
    t(8, y + 4, f"{sym} {d}", 12.5, TXT, "bold"); t(8, y + 8.6, note if note else "стоп і ціль — на картці", 8.6, MUT)
    t(52, y + 4, f"день {day} із 10", 10, TXT, ha="center")
    for k in range(10): ax.add_patch(Rectangle((38 + k * 2.8, y + 7.3), 2.3, 1.6, fc=(YEL if k < day else "#33404d"), ec="none"))
    t(93, y + 4.2, f"{r:+.1f}R", 12.5, col, "bold", "right"); t(93, y + 8.6, f"{'+' if r >= 0 else '−'}${abs(r) * 10:.0f}", 10, col, ha="right"); y += 13.5
y += 3; ax.add_patch(FancyBboxPatch((4, y), 92, 30, boxstyle="round,pad=0,rounding_size=1.5", fc=CARD, ec="none"))
t(8, y + 4, "ЩО ЦЕ ДАЄ", 11, YEL, "bold")
for k, s in enumerate(["🟡 смужка: скільки діб минуло з 10 (бачите, коли закриття за часом)", "колір: плюс / мінус / близько нуля прямо зараз", "«стоп → беззбиток …»: коли дійшло до +2R, одразу ціна", "угорі: скільки відкрито, скільки стопів поспіль, тиждень"]):
    t(8, y + 10 + k * 5, "• " + s.replace("🟡 ", ""), 9.6, TXT)
y += 34; t(50, y, "Спостереження на історії, не гарантія прибутку", 9, MUT, ha="center")
fig.savefig(sys.argv[1], facecolor=BG)

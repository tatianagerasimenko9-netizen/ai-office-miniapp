"""Макет картки стратегії «Зверху вниз» (ПРИКЛАД на вигаданих свічках — лише щоб показати вигляд). Використання: mock_td_card.py OUT_DIR"""
import sys, os
import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

BG, PANEL, TXT, DIM = "#0b1620", "#122433", "#f2f6fa", "#8da2b5"
GRN, RED, YEL, BLU = "#2ed38a", "#ff5468", "#ffc83d", "#5fb4ff"

def candles(n=72, seed=11, start=76400.0):
    r = np.random.default_rng(seed); px = start; out = []
    for i in range(n):
        drift = 20 if i > 44 else -6
        o = px; c = o + r.normal(drift, 45); h = max(o, c) + abs(r.normal(25, 15)); l = min(o, c) - abs(r.normal(25, 15))
        out.append([o, h, l, c]); px = c
    out[-1] = [out[-2][3], out[-2][3] + 150, out[-2][3] - 15, out[-2][3] + 140]
    return np.array(out)

def fmt(x): return f"{x:,.1f}".replace(",", " ").replace(".", ",")

def render(path, with_add):
    K = candles(); ent = K[-1, 3]; lo8 = K[-8:, 2].min(); sl = lo8 - 40; risk = ent - sl; tp = ent + 5.2 * risk
    sym, side = "BTCUSDT", "LONG"; risk_usd = 10; pct = lambda p: abs(p - ent) / ent * 100
    fig = plt.figure(figsize=(7.2, 11.2), facecolor=BG, dpi=150)
    fig.text(.06, .962, "ЗВЕРХУ ВНИЗ", color=DIM, fontsize=13, fontweight="bold")
    fig.patches.append(FancyBboxPatch((.80, .952), .14, .026, boxstyle="round,pad=0.002,rounding_size=0.01", transform=fig.transFigure, facecolor="#3a2f12", edgecolor=YEL, linewidth=1))
    fig.text(.87, .9645, "ТЕСТ", color=YEL, fontsize=11, fontweight="bold", ha="center", va="center")
    fig.text(.06, .905, sym, color=TXT, fontsize=30, fontweight="bold")
    fig.text(.94, .905, "▲ LONG" if side == "LONG" else "▼ SHORT", color=GRN if side == "LONG" else RED, fontsize=26, fontweight="bold", ha="right")
    fig.text(.06, .878, "Біржа Binance Futures · графік M15", color=DIM, fontsize=10)
    ax = fig.add_axes([.04, .42, .78, .44]); ax.set_facecolor(BG)
    vis = K[-56:]; ybot = min(sl, vis[:, 2].min()) - .25 * risk; ytop = ent + max(1.6 * risk, .45 * (vis[:, 1].max() - ybot))
    n = len(K)
    for i, (o, h, l, c) in enumerate(K):
        col = GRN if c >= o else RED
        ax.vlines(i, l, h, color=col, linewidth=1); ax.add_patch(Rectangle((i - .33, min(o, c)), .66, max(abs(c - o), 1), facecolor=col, edgecolor=col))
    ax.add_patch(Rectangle((n - 1.5, sl), 13, ent - sl, facecolor=RED, alpha=.16, edgecolor="none"))
    ax.add_patch(Rectangle((n - 1.5, ent), 13, ytop - ent, facecolor=GRN, alpha=.07, edgecolor="none"))
    ax.axhline(sl, color=RED, linewidth=1.6); ax.axhline(ent, color=YEL, linewidth=1.6, linestyle=(0, (5, 3)))
    ax.annotate("", xy=(n + 4, ytop - .1 * risk), xytext=(n + 4, ent + .3 * risk), arrowprops=dict(arrowstyle="-|>", color=GRN, linewidth=2.2))
    ax.text(n + 5.3, ent + .5 * risk, "до цілі", color=GRN, fontsize=9, ha="left", va="bottom", rotation=90)
    if with_add:
        add = ent - .55 * risk
        ax.add_patch(Rectangle((n - 12, add - .08 * risk), 24, .16 * risk, facecolor=BLU, alpha=.22, edgecolor=BLU, linewidth=.8, linestyle=":"))
        ax.text(n - 11, add + .14 * risk, "можливий добір (за бажанням)", color=BLU, fontsize=8.5, va="bottom")
    ax.set_xlim(n - 56, n + 12); ax.set_ylim(ybot, ytop)
    for s in ax.spines.values(): s.set_visible(False)
    ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
    for p, lab, col in ((ent, "ВХІД", YEL), (sl, "СТОП", RED)):
        fig.text(.835, ax.transData.transform((0, p))[1] / (fig.get_figheight() * fig.dpi), f"{lab}\n{fmt(p)}" + (f"\n−{pct(p):.2f}% · −\\${risk_usd}".replace(".", ",") if lab == "СТОП" else ""), color=col, fontsize=9.5, fontweight="bold", va="center")
    fig.text(.835, .855, f"ЦІЛЬ\n{fmt(tp)}\n+{pct(tp):.2f}% · +\\${risk_usd * (tp - ent) / risk:.0f}".replace(".", ","), color=GRN, fontsize=9.5, fontweight="bold", va="top")
    # блоки значень
    rows = [("ВХІД", fmt(ent), "ринком або лімітом біля цієї ціни", YEL), ("СТОП", fmt(sl), f"−{pct(sl):.2f}% · збиток при спрацюванні −\\${risk_usd}".replace(".", ","), RED),
            ("ЦІЛЬ", fmt(tp), f"+{pct(tp):.2f}% · прибуток при ризику \\${risk_usd}: +\\${risk_usd * (tp - ent) / risk:.0f}".replace(".", ","), GRN)]
    y = .375
    for lab, val, sub, col in rows:
        fig.patches.append(FancyBboxPatch((.05, y - .075), .90, .085, boxstyle="round,pad=0.002,rounding_size=0.012", transform=fig.transFigure, facecolor=PANEL, edgecolor="none"))
        fig.patches.append(Rectangle((.05, y - .075), .012, .085, transform=fig.transFigure, facecolor=col, edgecolor="none"))
        fig.text(.09, y - .012, lab, color=col, fontsize=12, fontweight="bold", va="top")
        fig.text(.92, y - .012, val, color=TXT, fontsize=22, fontweight="bold", ha="right", va="top")
        fig.text(.09, y - .052, sub, color=DIM, fontsize=10, va="top")
        y -= .097
    fig.text(.06, y - .004, "Тримати до цілі або стопа, максимум 48 годин.", color=TXT, fontsize=11)
    fig.text(.06, y - .03, "Стоп виставити на біржі одразу після входу.", color=TXT, fontsize=11)
    fig.text(.5, .018, "ПРИКЛАД ВИГЛЯДУ · свічки вигадані · тестова стратегія, не гроші", color=DIM, fontsize=9, ha="center")
    fig.savefig(path, facecolor=BG); plt.close(fig)

out = sys.argv[1]; os.makedirs(out, exist_ok=True)
render(os.path.join(out, "card_A.png"), False)
render(os.path.join(out, "card_B_dobir.png"), True)

"""Зображення-картка «Зверху вниз» (ТЕСТ): графік M15 зі свічками, лінії входу/стопа, ціль, % і $ при ризику $10. Лише реальні свічки Binance Futures; жодних вигаданих рівнів."""
from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime

BG, PANEL, TXT, DIM = "#0b1620", "#122433", "#f2f6fa", "#8da2b5"
GRN, RED, YEL = "#2ed38a", "#ff5468", "#ffc83d"
N_BARS = 60


def render_td(row, bars):
    if not isinstance(bars, list) or len(bars) < 100:
        raise ValueError("missing Binance Futures M15 history")
    prices = [(float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])) for x in bars]
    if not all(all(math.isfinite(p) and p > 0 for p in b) for b in prices):
        raise ValueError("invalid candles")
    last = datetime.fromisoformat(str(bars[-1]["ts"]).replace("Z", "+00:00")).timestamp()
    if float(row["confirm_ts"]) - last > 900 or last > float(row["confirm_ts"]):
        raise ValueError("candles not aligned with signal confirmation")
    import matplotlib
    from matplotlib import pyplot as plt
    from matplotlib.patches import Rectangle, FancyBboxPatch
    from office_price_format import format_px

    sym = row["symbol"]; side = 1 if row["direction"] == "LONG" else -1
    tg = json.loads(row["targets_json"]) if isinstance(row["targets_json"], str) else row["targets_json"]
    ent, sl, tp = float(row["entry"]), float(row["sl"]), float(tg[0]["p"])
    risk = abs(ent - sl); usd_tp = 10 * abs(tp - ent) / risk if risk > 0 else 0.0
    pct = lambda p: f"{abs(p - ent) / ent * 100:.2f}".replace(".", ",")
    fmt = lambda p: format_px(p, sym).replace(".", ",")
    K = prices[-N_BARS:]; n = len(K)
    lo = min(min(b[2] for b in K), sl); hi = max(max(b[1] for b in K), ent)
    if side > 0:
        ybot = lo - .25 * risk; ytop = max(ent + max(1.6 * risk, .45 * (hi - ybot)), hi + .05 * (hi - ybot))
    else:
        ytop = hi + .25 * risk; ybot = min(ent - max(1.6 * risk, .45 * (ytop - lo)), lo - .05 * (ytop - lo))
    with matplotlib.rc_context({"text.parse_math": False}):
        fig = plt.figure(figsize=(7.2, 11.2), facecolor=BG, dpi=130)
        fig.text(.06, .962, "ЗВЕРХУ ВНИЗ", color=DIM, fontsize=13, fontweight="bold")
        fig.text(.30, .962, f"№{int(row['seq'])}", color=DIM, fontsize=13)
        fig.patches.append(FancyBboxPatch((.80, .952), .14, .026, boxstyle="round,pad=0.002,rounding_size=0.01", transform=fig.transFigure, facecolor="#3a2f12", edgecolor=YEL, linewidth=1))
        fig.text(.87, .9645, "ТЕСТ", color=YEL, fontsize=11, fontweight="bold", ha="center", va="center")
        fig.text(.06, .905, sym, color=TXT, fontsize=30, fontweight="bold")
        fig.text(.94, .905, "▲ LONG" if side > 0 else "▼ SHORT", color=GRN if side > 0 else RED, fontsize=26, fontweight="bold", ha="right")
        fig.text(.06, .878, "Binance Futures · графік M15", color=DIM, fontsize=10)
        ax = fig.add_axes([.04, .47, .78, .39]); ax.set_facecolor(BG)
        for i, (o, h, l, c) in enumerate(K):
            col = GRN if c >= o else RED
            ax.vlines(i, l, h, color=col, linewidth=1); ax.add_patch(Rectangle((i - .33, min(o, c)), .66, max(abs(c - o), 1e-12), facecolor=col, edgecolor=col))
        tz0, tz1 = (ent, ytop) if side > 0 else (ybot, ent)
        sz0, sz1 = (sl, ent) if side > 0 else (ent, sl)
        ax.add_patch(Rectangle((n - 1.5, sz0), 13, sz1 - sz0, facecolor=RED, alpha=.16, edgecolor="none"))
        ax.add_patch(Rectangle((n - 1.5, tz0), 13, tz1 - tz0, facecolor=GRN, alpha=.07, edgecolor="none"))
        ax.axhline(sl, color=RED, linewidth=1.6); ax.axhline(ent, color=YEL, linewidth=1.6, linestyle=(0, (5, 3)))
        ax.annotate("", xy=(n + 4, ent + side * (ytop - ent if side > 0 else ent - ybot) * .85), xytext=(n + 4, ent + side * .3 * risk), arrowprops=dict(arrowstyle="-|>", color=GRN, linewidth=2.2))
        ax.set_xlim(n - 56, n + 12); ax.set_ylim(ybot, ytop)
        for s_ in ax.spines.values(): s_.set_visible(False)
        ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
        H = fig.get_figheight() * fig.dpi
        ypos = lambda p: ax.transData.transform((0, p))[1] / H
        fig.text(.835, ypos(ent), f"ВХІД\n{fmt(ent)}", color=YEL, fontsize=9.5, fontweight="bold", va="center")
        fig.text(.835, ypos(sl), f"СТОП\n{fmt(sl)}\n−{pct(sl)}% · −$10", color=RED, fontsize=9.5, fontweight="bold", va="center")
        ty = ypos(ent + side * (ytop - ent if side > 0 else ent - ybot) * .85)
        fig.text(.835, ty, f"ЦІЛЬ\n{fmt(tp)}\n+{pct(tp)}% · +${usd_tp:.0f}", color=GRN, fontsize=9.5, fontweight="bold", va="center")
        rows = [("ВХІД", fmt(ent), "ринком або лімітом біля цієї ціни", YEL), ("СТОП", fmt(sl), f"−{pct(sl)}% · збиток при спрацюванні −$10", RED),
                ("ЦІЛЬ", fmt(tp), f"+{pct(tp)}% · прибуток при ризику $10: +${usd_tp:.0f}", GRN)]
        y = .405
        for lab, val, sub, col in rows:
            fig.patches.append(FancyBboxPatch((.05, y - .07), .90, .08, boxstyle="round,pad=0.002,rounding_size=0.012", transform=fig.transFigure, facecolor=PANEL, edgecolor="none"))
            fig.patches.append(Rectangle((.05, y - .07), .012, .08, transform=fig.transFigure, facecolor=col, edgecolor="none"))
            fig.text(.09, y - .012, lab, color=col, fontsize=12, fontweight="bold", va="top")
            fig.text(.92, y - .012, val, color=TXT, fontsize=22, fontweight="bold", ha="right", va="top")
            fig.text(.09, y - .047, sub, color=DIM, fontsize=10, va="top")
            y -= .087
        fig.text(.06, y - .006, "Тримати до цілі або стопа, максимум 48 годин.", color=TXT, fontsize=11)
        fig.text(.06, y - .028, "Стоп виставити на біржі одразу після входу.", color=TXT, fontsize=11)
        fig.text(.5, .008, "Тестова стратегія · ручне рішення · ордерів Office не відкриває", color=DIM, fontsize=9, ha="center")
        fd, path = tempfile.mkstemp(prefix="td_live_", suffix=".png"); os.close(fd)
        try: fig.savefig(path, facecolor=BG)
        finally: plt.close(fig)
    return path

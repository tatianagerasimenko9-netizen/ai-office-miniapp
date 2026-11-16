"""Зображення-картка стратегій (ІНТРАДЕЙ / СВІНГ): кольорова шапка, реальні свічки Binance Futures, лінії входу/стопа/цілі, сума позиції й три колонки ВХІД / СТОП / ЦІЛЬ, за потреби блок «СЛАБКИЙ СИГНАЛ». Жодних вигаданих рівнів."""
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
    _hy = json.loads(row["hyp_json"]) if isinstance(row.get("hyp_json"), str) and row.get("hyp_json") else {}
    if float(row["confirm_ts"]) - last > float(_hy.get("tf_s", 900)) or last > float(row["confirm_ts"]):
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
    import textwrap
    from office_br.card import strat, td_size, usd_fmt, warn_line
    nm, _em, bcol, dcol, sub = strat(row); nm = _hy.get("label", nm); sub = _hy.get("sub", sub)
    wl = warn_line(row); wr_ = textwrap.wrap((lambda t: t[0].upper() + t[1:])(wl.split(": ", 1)[1]), 40)[:3] if wl else []
    H_IN = 9.0 + ((.62 + .3 * len(wr_) + .1) if wr_ else 0.0)
    with matplotlib.rc_context({"text.parse_math": False}):
        fig = plt.figure(figsize=(7.2, H_IN), facecolor=BG, dpi=130)
        u = lambda inches: inches / H_IN                      # дюйми → частка висоти
        fig.patches.append(Rectangle((0, 1 - u(.95)), 1, u(.95), transform=fig.transFigure, facecolor=bcol, edgecolor="none"))
        fig.text(.05, 1 - u(.42), nm, color=dcol, fontsize=31, fontweight="bold", va="center")
        fig.text(.95, 1 - u(.42), f"№{int(row['seq'])}", color=dcol, fontsize=23, fontweight="bold", va="center", ha="right")
        fig.text(.05, 1 - u(.77), sub, color=dcol, fontsize=12.5, va="center")
        fig.text(.05, 1 - u(1.42), sym, color=TXT, fontsize=29, fontweight="bold", va="center")
        fig.text(.95, 1 - u(1.42), "▲ LONG" if side > 0 else "▼ SHORT", color=GRN if side > 0 else RED, fontsize=26, fontweight="bold", va="center", ha="right")
        ax = fig.add_axes([.03, u(H_IN - 1.7 - 4.1), .80, u(4.1)]); ax.set_facecolor(BG)
        for i, (o, h, l, c) in enumerate(K):
            col = GRN if c >= o else RED
            ax.vlines(i, l, h, color=col, linewidth=1.1); ax.add_patch(Rectangle((i - .33, min(o, c)), .66, max(abs(c - o), 1e-12), facecolor=col, edgecolor=col))
        tz0, tz1 = (ent, ytop) if side > 0 else (ybot, ent)
        sz0, sz1 = (sl, ent) if side > 0 else (ent, sl)
        ax.add_patch(Rectangle((n - 1.5, sz0), 13, sz1 - sz0, facecolor=RED, alpha=.16, edgecolor="none"))
        ax.add_patch(Rectangle((n - 1.5, tz0), 13, tz1 - tz0, facecolor=GRN, alpha=.07, edgecolor="none"))
        ax.axhline(sl, color=RED, linewidth=1.8); ax.axhline(ent, color=YEL, linewidth=1.8, linestyle=(0, (5, 3)))
        ax.axhline(tp if (ybot <= tp <= ytop) else (ytop if side > 0 else ybot), color=GRN, linewidth=1.8)
        ax.set_xlim(n - 56, n + 12); ax.set_ylim(ybot, ytop)
        for s_ in ax.spines.values(): s_.set_visible(False)
        ax.tick_params(left=False, bottom=False, labelleft=False, labelbottom=False)
        Hp = fig.get_figheight() * fig.dpi
        ypos = lambda p: ax.transData.transform((0, min(max(p, ybot), ytop)))[1] / Hp
        fig.text(.845, ypos(sl), "СТОП", color=RED, fontsize=11, fontweight="bold", va="center")
        fig.text(.845, ypos(ent), "ВХІД", color=YEL, fontsize=11, fontweight="bold", va="center")
        fig.text(.845, ypos(tp), "ЦІЛЬ", color=GRN, fontsize=11, fontweight="bold", va="center")
        y = 1 - 1.7 - 4.1 - .18                              # поточна позиція (дюйми від верху)
        def box(y0, h, face="#122433", edge="none", lw=0):
            fig.patches.append(FancyBboxPatch((.04, 1 - u(y0 + h)), .92, u(h), boxstyle="round,pad=0.002,rounding_size=0.012", transform=fig.transFigure, facecolor=face, edgecolor=edge, linewidth=lw))
        y = 1.7 + 4.1 + .22
        box(y, .78)
        fig.text(.07, 1 - u(y + .39), "ВІДКРИЙ НА", color=DIM, fontsize=13, fontweight="bold", va="center")
        fig.text(.93, 1 - u(y + .39), f"${usd_fmt(td_size(row))}", color=TXT, fontsize=29, fontweight="bold", va="center", ha="right")
        y += .78 + .16
        cw = .92 / 3 - .01
        for k_, (lab, col, val, l1, l2) in enumerate((("ВХІД", YEL, fmt(ent), "лімітом", ""), ("СТОП", RED, fmt(sl), f"−{pct(sl)}%", "−$10"), ("ЦІЛЬ", GRN, fmt(tp), f"+{pct(tp)}%", f"+${usd_tp:.0f} · лімітом"))):
            x0 = .04 + k_ * (cw + .015)
            fig.patches.append(Rectangle((x0, 1 - u(y + 1.62)), cw, u(1.62), transform=fig.transFigure, facecolor="#122433", edgecolor="none"))
            fig.patches.append(Rectangle((x0, 1 - u(y + .1)), cw, u(.1), transform=fig.transFigure, facecolor=col, edgecolor="none"))
            fig.text(x0 + cw / 2, 1 - u(y + .36), lab, color=col, fontsize=14, fontweight="bold", ha="center", va="center")
            fig.text(x0 + cw / 2, 1 - u(y + .78), val, color=TXT, fontsize=18 if len(val) <= 8 else 15, fontweight="bold", ha="center", va="center")
            fig.text(x0 + cw / 2, 1 - u(y + 1.16), l1, color=DIM, fontsize=11.5, ha="center", va="center")
            fig.text(x0 + cw / 2, 1 - u(y + 1.42), l2, color=DIM, fontsize=11.5, ha="center", va="center")
        y += 1.62 + .18
        if wr_:
            hh = .62 + .3 * len(wr_)
            box(y, hh, "#3a3000", YEL, 2.2)
            fig.text(.07, 1 - u(y + .3), ("СЛАБКИЙ СИГНАЛ" if wl.startswith("Слабкий") else "ОБЕРЕЖНО"), color=YEL, fontsize=16, fontweight="bold", va="center")
            for i_, ln in enumerate(wr_): fig.text(.07, 1 - u(y + .62 + .27 * i_), ln, color=TXT, fontsize=12.5, va="center")
            y += hh + .1
        fd, path = tempfile.mkstemp(prefix="td_live_", suffix=".png"); os.close(fd)
        try: fig.savefig(path, facecolor=BG, bbox_inches=matplotlib.transforms.Bbox.from_extents(0, 0, 7.2, H_IN) if False else None)
        finally: plt.close(fig)
    return path

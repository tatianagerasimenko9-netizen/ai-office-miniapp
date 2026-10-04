#!/usr/bin/env python3
"""Контрольні графіки поведінки оригінального Pine (еталон з lrc_parity): активний UP/DOWN канал, пробій, старий пробитий (синій пунктир) + новий активний, зміна знака нахилу.
Малюємо на тих самих послідовностях, що й у числовому аудиті. Це еталон Pine, а не поточний Office (у Office ці стани відсутні)."""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lrc_parity as lp  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp")
L = 100


def draw(closes, end, title, fname, show_from=None, keep_events=True):
    end = min(end, len(closes) - 1)
    a0 = show_from if show_from is not None else max(0, end - 260)
    ser = {r["i"]: r for r in lp.pine_series(closes[: end + 1], L)}
    fig, ax = plt.subplots(figsize=(10, 6), dpi=100, facecolor="#0f1420")
    ax.set_facecolor("#0f1420")
    xs = np.arange(a0, end + 1)
    ax.plot(xs, closes[a0: end + 1], color="#cfd6e4", linewidth=1.4)
    # синій пунктир: лишається одна лінія (та, що пробита) від бару, що передував пробою; extend none
    labelled = False
    if keep_events:
        for i, r in ser.items():
            k = r["kept_broken"]
            if k and i >= a0:
                ax.plot([i - L, i - 1], [k["y_start"], k["y_end"]], color="#4d8bff", linestyle=":", linewidth=2.4)
                if not labelled:
                    ax.annotate("пробита лінія (пунктир)", (i - 1, k["y_end"]), color="#4d8bff", fontsize=12, xytext=(-150, -34), textcoords="offset points",
                                arrowprops=dict(arrowstyle="-", color="#4d8bff"))
                    labelled = True
    r = ser[end]
    col = "#2ebd85" if r["slope"] > 0 else ("#e5534b" if r["slope"] < 0 else "#4d8bff")
    x0 = end - (L - 1)
    for k, ls in ((-1, "--"), (0, "-"), (1, "--")):
        y1, y2 = r["intercept"] + r["dev"] * 2 * k, r["endy"] + r["dev"] * 2 * k
        sl = (y2 - y1) / (L - 1)
        ax.plot([x0, end + 25], [y1, y2 + sl * 25], color=col, linestyle=ls, linewidth=2)   # extend right
    ax.text(0.01, 0.97, f"{title}\nнахил {r['slope']:+.4f}  {r['arrow']}  outofchannel={r['ooc']}" + ("  Up trend" if r["trend_up"] else "") + ("  Down trend" if r["trend_dn"] else ""),
            transform=ax.transAxes, color="#e8ecf3", fontsize=12, va="top")
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(colors="#6b778c")
    fig.savefig(OUT / fname, facecolor="#0f1420")
    plt.close(fig)


t = np.arange(400, dtype=float)
rng = np.random.default_rng(3)
n_ = rng.normal(0, 0.12, 400)
draw(list(100 + 0.1 * t + n_), 399, "1) Активний висхідний канал (зелений)", "lrc_1_up.png")
draw(list(200 - 0.1 * t + n_), 399, "2) Активний низхідний канал (червоний)", "lrc_2_down.png")
brk = list(100 + 0.1 * t - np.where(t > 300, 0.45 * (t - 300), 0) + n_)
first = next(r["i"] for r in lp.pine_series(brk, L) if r["ooc"] == 0)
draw(brk, first, "3) Пробій висхідного каналу вниз (момент пробою)", "lrc_3_break.png")
draw(brk, 399, "4) Старий пробитий (синій пунктир) + новий активний канал", "lrc_4_broken_plus_new.png")
chg = list(150 - np.where(t < 250, 0.1 * t, 0.1 * 250 - 0.2 * (t - 250)) + n_)
ser = lp.pine_series(chg, L)
up = next((r["i"] for r in ser if r["trend_up"]), 399)
draw(chg, up + 15, "5) Зміна знака нахилу (Up trend)", "lrc_5_trend_change.png", keep_events=False)
print("ok", OUT)

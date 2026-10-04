"""Telegram-картка «План готовий»: короткий вертикальний текст + чиста картинка-графік з тих самих цифр плану.

Текст читається за 3–5 секунд: напрям і монета, «Чому» (1–2 речення з цифрами), вхід, стоп, цілі, ризик, строк. Без ринкових рядків.
Картинку малюємо самі (matplotlib), лише з даних сценарію: свічки, зона входу (жовта), SL, TP1–TP3, ціна READY, ключовий рівень."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

TEMPLATE_VERSION = "ready-card-v2"
PHASE_WARN_SIGMA = 3.0   # у Telegram фазу показуємо лише від 3σ за 30 хв; нормальна фаза мовчить

LEVEL_TAGS = ("level_retest", "level_hold", "level_false_break", "sweep_pool", "sfp", "spring", "upthrust", "spring_test", "upthrust_test",
              "double_top", "double_bottom", "triple_top", "triple_bottom", "head_shoulders", "inverse_head_shoulders")


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


def _price(v: Any) -> Optional[float]:
    return _f(v.get("price") if isinstance(v, dict) else v)


def _num(v: Any, symbol: str) -> str:
    from office_price_format import format_px

    x = _f(v)
    return "—" if x is None else format_px(x, symbol).replace(".", ",")


def _zone(entry: Any, zone: Any):
    """Зона входу = зона сетапу зі знімка (gate.zone). Межа «далі не входити» (max_entry) — інше поняття і сюди не потрапляє."""
    from office_ready_core import entry_zone

    return entry_zone(entry, zone)


def short_why(*, tags: List[str], mode: Optional[str], direction: str, symbol: str, entry: Any, zone_lo: Any = None, zone_hi: Any = None) -> str:
    """1–2 коротких речення з цифрами: що саме сталося з ціною (а не назва патерну). Лише з реально збережених тегів."""
    short = str(direction or "").upper() == "SHORT"
    ts = [str(t) for t in (tags or [])]
    et = _num(entry, symbol)
    lo, hi = _f(zone_lo), _f(zone_hi)
    zt = f"{_num(min(lo, hi), symbol)}–{_num(max(lo, hi), symbol)}" if lo is not None and hi is not None else et
    down, up = "вниз", "вгору"
    way = down if short else up
    back = up if short else down
    has = lambda *k: next((t for t in k if t in ts), None)  # noqa: E731
    first = ""
    if has("level_retest", "level_hold"):
        first = f"Ціна повернулась до {et} і відбилась {way}."
    elif has("level_false_break"):
        first = f"Ціна коротко пробила {et} і повернулась назад."
    elif has("sweep_pool", "sfp"):
        first = f"Ціну {'підняли над' if short else 'опустили під'} {et}, зняли стопи і повернули {way}."
    elif has("upthrust", "upthrust_test"):
        first = f"Ціна коротко вийшла над {zt} і повернулась під зону."
    elif has("spring", "spring_test"):
        first = f"Ціна коротко вийшла під {zt} і повернулась над зону."
    elif has("fvg_retest"):
        first = f"Ціна повернулась у розрив {zt} і відбилась {way}."
    elif has("ob_retest"):
        first = f"Ціна відбилась {way} від зони {zt}, звідки почався попередній рух."
    elif has("breaker_retest"):
        first = f"Ціна відбилась {way} від зони {zt}, яку раніше пробили."
    elif has("double_top", "double_bottom", "triple_top", "triple_bottom", "head_shoulders", "inverse_head_shoulders"):
        first = f"Фігура розвороту біля {et}: закриття за лінією шиї, рух {way}."
    elif has("choch", "bos"):
        first = f"Рух на малих свічках змінив напрямок {way}, зона {zt} утримується."
    elif has("ote"):
        first = f"Після різкого руху ціна відкотилась у зону {zt}."
    elif has("displacement"):
        first = f"Був різкий рух {way}, ціна тримається біля {et}."
    elif next((t for t in ts if t in ("flag", "pennant", "ascending_triangle", "descending_triangle", "symmetrical_triangle", "rectangle", "rising_wedge", "falling_wedge")), None):
        first = f"Ціна вийшла з фігури {way} і тримається біля {et}."
    elif has("channel_edge"):
        first = f"Ціна біля краю лінії тренду {et} і відбилась {way}."
    elif mode == "retest":
        first = f"Ціна пробила зону {zt} і повернулась до неї."
    else:
        first = f"Свічка закрилась у зоні входу {zt}."
    second = ""
    if has("engulf", "engulfing_ctx"):
        second = "Підтвердила розворотна свічка."
    elif has("pin_bar"):
        second = "Підтвердила свічка з довгою тінню."
    elif has("inside_bar_break"):
        second = "Підтвердив вихід із вузької свічки."
    return (first + (" " + second if second else "")).strip()


def phase_sigma(closes_5m: Any, direction: str) -> Optional[float]:
    try:
        import office_phase as ph

        return ph.sigma_extension([float(c["close"] if isinstance(c, dict) else c) for c in (closes_5m or [])], direction)
    except Exception:  # noqa: BLE001
        return None


def caption(*, symbol: str, direction: str, entry: Any, sl: Any, tp1: Any, tp2: Any = None, tp3: Any = None, zone: Any = None,
            risk_usd: Any = None, valid_until: str = "", why: str = "", sigma30: Optional[float] = None) -> str:
    from office_user_messages import _dir_head, _pct_txt, ticker

    dot, word = _dir_head(direction)
    L = [f"{dot} {word} · {ticker(symbol)}"]
    if why:
        L.append(f"Чому: {why}")
    L.append("")
    lo, hi = _zone(entry, zone)
    z = _num(lo, symbol) if lo == hi else f"{_num(lo, symbol)}–{_num(hi, symbol)}"
    L.append(f"Вхід: {z}")
    L.append(f"Стоп: {_num(sl, symbol)}" + _pct_txt(sl, entry, "−"))
    for i, v in ((1, tp1), (2, tp2), (3, tp3)):
        p = _price(v)
        if p is not None:
            L.append(f"TP{i}: {_num(p, symbol)}" + _pct_txt(p, entry, "+"))
    if risk_usd:
        L.append(f"Ризик: {float(risk_usd):.0f} $")
    if sigma30 is not None and sigma30 >= PHASE_WARN_SIGMA:
        L.append("⚠️ Рух уже розтягнутий: " + f"{sigma30:.1f}".replace(".", ",") + "σ за 30 хв.")
    if valid_until:
        L.append(f"⏳ до {valid_until}")
    return "\n".join(L)


# ------------------------------------------------------------------ картинка
BG, FG, GRID = "#0f1420", "#e8ecf3", "#1f2735"
UP, DOWN, YEL, TPC, SLC = "#2ebd85", "#e5534b", "#f2c230", "#2ebd85", "#e5534b"
EVC = "#7aa2ff"   # докази сетапу (фігура, рівень, FVG тощо): синій, щоб не плутати із зоною входу (жовта), SL (червоний) і TP (зелений)


def render(*, symbol: str, direction: str, candles: List[Dict[str, Any]], entry: Any, zone: Any = None, sl: Any, tp1: Any, tp2: Any = None, tp3: Any = None,
           ready_price: Any = None, key_level: Any = None, key_label: str = "рівень", evidence: Any = None, path: str, width_px: int = 1000, height_px: int = 800) -> Dict[str, Any]:
    """PNG-картка. {'ok': True, 'path', 'sha256', 'size', 'drawn': {...}} або {'ok': False, 'reason'}."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"matplotlib: {type(exc).__name__}"}
    from office_user_messages import _dir_head, ticker

    cs = [c for c in (candles or []) if all(_f(c.get(k)) is not None for k in ("open", "high", "low", "close"))][-96:]
    if len(cs) < 12:
        return {"ok": False, "reason": "мало свічок"}
    short = str(direction or "").upper() == "SHORT"
    e, sl_, t1, t2, t3 = _f(entry), _f(sl), _price(tp1), _price(tp2), _price(tp3)
    zlo, zhi = _zone(entry, zone)
    if e is None or sl_ is None:
        return {"ok": False, "reason": "немає входу/стопа"}
    hi_c, lo_c = max(float(c["high"]) for c in cs), min(float(c["low"]) for c in cs)
    core = [hi_c, lo_c, e, sl_] + [x for x in (t1, t2, zlo, zhi) if x is not None]
    top, bot = max(core), min(core)
    span = max(top - bot, e * 0.002)
    t3_edge = False
    if t3 is not None:
        if abs(t3 - e) <= 1.6 * span:
            top, bot = max(top, t3), min(bot, t3)
        else:
            t3_edge = True
    pad = (top - bot) * 0.08
    y0, y1 = bot - pad, top + pad
    rng = y1 - y0
    n = len(cs)
    fig = plt.figure(figsize=(width_px / 100, height_px / 100), dpi=100, facecolor=BG)
    ax = fig.add_axes([0.02, 0.05, 0.55, 0.80], facecolor=BG)
    ax.set_xlim(-1, n + 1)
    ax.set_ylim(y0, y1)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])
    # зона входу — жовта, мінімум 1,4% висоти, щоб її було видно
    zl, zh = zlo, zhi
    mh = rng * 0.014
    if zh - zl < mh:
        mid = (zh + zl) / 2
        zl, zh = mid - mh / 2, mid + mh / 2
    ax.add_patch(Rectangle((-1, zl), n + 2, zh - zl, facecolor=YEL, alpha=0.30, edgecolor=YEL, linewidth=1.2, zorder=1))
    for i, c in enumerate(cs):
        o, h, l, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
        col = UP if cl >= o else DOWN
        ax.vlines(i, l, h, color=col, linewidth=1.6, zorder=3)
        ax.add_patch(Rectangle((i - 0.33, min(o, cl)), 0.66, max(abs(cl - o), rng * 0.0015), facecolor=col, edgecolor=col, zorder=4))
    labels = []   # (y, text, colour, bold)
    from office_patterns import _ts as _tsf

    tt = [_tsf(c.get("ts")) for c in cs]
    step = None
    if all(t is not None for t in tt) and n > 2:
        diffs = sorted(tt[i + 1] - tt[i] for i in range(n - 1))
        step = diffs[len(diffs) // 2] or None

    def x_of(t: Any) -> Optional[float]:
        return None if (step is None or t is None) else (float(t) - tt[0]) / step

    renderer = fig.canvas.get_renderer()
    placed: List[Any] = []        # зайняті прямокутники підписів (екранні координати): жоден підпис не лягає на інший
    skipped: List[str] = []

    def put(txt: str, color: str, cands: List[Any]) -> bool:
        """Ставить підпис у першому кандидаті, де він повністю в межах графіка й не перетинає вже поставлені; немає чистого місця → без підпису (геометрія лишається)."""
        for x, y, ha, va in cands:
            t = ax.text(x, y, txt, color=color, fontsize=17, fontweight="bold", ha=ha, va=va, zorder=9)
            bb = t.get_window_extent(renderer).expanded(1.06, 1.3)
            if ax.bbox.x0 <= bb.x0 and bb.x1 <= ax.bbox.x1 and ax.bbox.y0 <= bb.y0 and bb.y1 <= ax.bbox.y1 and not any(bb.overlaps(o) for o in placed):
                placed.append(bb)
                return True
            t.remove()
        skipped.append(txt)
        return False

    def spots(x_left: float, y: float, dy: float) -> List[Any]:
        """Кандидати для підпису біля горизонтального об'єкта: ліворуч/праворуч, над/під."""
        return [(x_left, y + dy, "left", "bottom"), (n - 1.0, y + dy, "right", "bottom"), (x_left, y - dy, "left", "top"), (n - 1.0, y - dy, "right", "top")]

    drawn_ev: List[str] = []
    for it in (evidence or [])[:3]:   # докази цього READY: лише те, що дало підтвердження (office_ready_evidence)
        try:
            kind, lab, dw = str(it.get("kind")), str(it.get("label") or ""), it.get("draw")
            if dw == "lines":
                chan = kind == "channel_edge"
                for ln in it.get("lines") or []:
                    x0, x1 = x_of(ln["t0"]), x_of(ln["t1"])
                    if x0 is None or x1 is None or x1 == x0:
                        continue
                    slope_ = (float(ln["p1"]) - float(ln["p0"])) / (x1 - x0)
                    xs, xe = max(x0, -1.0), n - 0.5
                    ya, yb = float(ln["p0"]) + slope_ * (xs - x0), float(ln["p0"]) + slope_ * (xe - x0)
                    mid = chan and ln.get("role") == "mid"
                    ax.plot([xs, xe], [ya, yb], color=EVC, linewidth=1.4 if chan else 2.6, linestyle=":" if mid else "-", alpha=0.75 if chan else 0.95, zorder=5)
                ln0 = (it.get("lines") or [None])[0]
                if ln0 and lab:
                    x0, x1 = x_of(ln0["t0"]), x_of(ln0["t1"])
                    if x0 is not None and x1 not in (None, x0):
                        slope0 = (float(ln0["p1"]) - float(ln0["p0"])) / (x1 - x0)
                        cands = [(max(x0, 0.0) - 0.8, float(ln0["p0"]) + slope0 * (max(x0, 0.0) - x0), "right", "center")]   # зліва від початку лінії — там зазвичай порожньо
                        xa, xb = max(x0, 0.0), min(max(x0, x1), n - 1.0)   # лише там, де лінія реально видна на графіку
                        for fr in (0.5, 0.3, 0.7, 0.15, 0.85):
                            xl = xa + (xb - xa) * fr
                            yl = float(ln0["p0"]) + (float(ln0["p1"]) - float(ln0["p0"])) / (x1 - x0) * (xl - x0)
                            cands += [(xl, yl + rng * 0.03, "center", "bottom"), (xl, yl - rng * 0.03, "center", "top")]
                        put(lab, EVC, cands)
            elif dw == "band":
                xs = max(-1.0, x_of(it.get("t0")) or -1.0)
                ax.add_patch(Rectangle((xs, float(it["lo"])), n + 1 - xs, max(float(it["hi"]) - float(it["lo"]), rng * 0.006), facecolor=EVC, alpha=0.16, edgecolor=EVC,
                                       linewidth=1.2, linestyle="--", zorder=1))
                if lab:
                    cands = [(xs + 0.6, float(it["hi"]) + rng * 0.008, "left", "bottom"), (n - 1.0, float(it["hi"]) + rng * 0.008, "right", "bottom"),
                             (xs + 0.6, float(it["lo"]) - rng * 0.008, "left", "top"), (n - 1.0, float(it["lo"]) - rng * 0.008, "right", "top")]
                    put(lab, EVC, cands)
            elif dw == "hline":
                xs = max(-1.0, x_of(it.get("t0")) or -1.0)
                ax.plot([xs, n - 0.5], [float(it["price"])] * 2, color=EVC, linewidth=2.0, linestyle="--", zorder=5)
                if lab:
                    put(lab, EVC, spots(xs + 0.6, float(it["price"]), rng * 0.008))
            elif dw == "marker" and x_of(it.get("t")) is not None:
                ax.scatter([x_of(it["t"])], [float(it["price"])], s=150, marker="v" if short else "^", color=EVC, edgecolors=BG, zorder=9)
                if lab:
                    xm, pm = x_of(it["t"]), float(it["price"])
                    put(lab, EVC, [(xm - 1.0, pm, "right", "center"), (xm + 1.0, pm, "left", "center"), (xm, pm + rng * 0.04, "center", "bottom"), (xm, pm - rng * 0.04, "center", "top")])
            drawn_ev.append(kind)
        except Exception:  # noqa: BLE001
            continue

    def hline(y: float, col: str, ls: str = "-", lw: float = 2.0) -> None:
        ax.axhline(y, color=col, linestyle=ls, linewidth=lw, zorder=2, alpha=0.95)

    if key_level is not None and _f(key_level) is not None and y0 < float(key_level) < y1 and abs(float(key_level) - e) > rng * 0.02:
        hline(float(key_level), "#8b96a8", "--", 1.4)
        labels.append((float(key_level), key_label, "#8b96a8", False))
    hline(sl_, SLC)
    labels.append((sl_, f"SL  {_num(sl_, symbol)}", SLC, True))
    for k, v in ((1, t1), (2, t2), (3, t3)):
        if v is None or (k == 3 and t3_edge):
            continue
        hline(v, TPC)
        labels.append((v, f"TP{k}  {_num(v, symbol)}", TPC, True))
    if t3_edge:
        up = (t3 > e)
        ax.annotate("", xy=(n * 0.5, y1 - rng * 0.005 if up else y0 + rng * 0.005), xytext=(n * 0.5, (y1 if up else y0) + (-rng * 0.07 if up else rng * 0.07)),
                    arrowprops=dict(arrowstyle="-|>", color=TPC, lw=3), zorder=6)
        labels.append((y1 - rng * 0.02 if up else y0 + rng * 0.02, f"TP3  {_num(t3, symbol)}", TPC, True))
    labels.append(((zlo + zhi) / 2, "ВХІД  " + (_num(zlo, symbol) if zlo == zhi else f"{_num(zlo, symbol)}–{_num(zhi, symbol)}"), YEL, True))
    rp = _f(ready_price)
    if rp is not None and y0 < rp < y1:
        ax.scatter([n - 1], [rp], s=120, color="#ffffff", edgecolors=BG, linewidths=2, zorder=7)
        labels.append((rp, f"READY  {_num(rp, symbol)}", "#ffffff", True))
    # підписи справа без накладання: мінімальний крок 6,5% висоти
    gap = rng * 0.065
    labels.sort(key=lambda t: t[0])
    ys: List[float] = []
    for y, *_ in labels:
        ys.append(y if not ys else max(y, ys[-1] + gap))
    over = ys[-1] - (y1 - rng * 0.01) if ys else 0
    if over > 0:
        ys = [v - over for v in ys]
    for i in range(len(ys) - 2, -1, -1):   # якщо зсув вгору/вниз зіткнув — розсуваємо назад
        ys[i] = min(ys[i], ys[i + 1] - gap)
    right_boxes: List[Any] = []
    for (y, txt, col, bold), yy in zip(labels, ys):
        ann = ax.annotate(txt, xy=(n + 1, y), xytext=(n + 3.2, yy), color=col, fontsize=20, fontweight="bold" if bold else "normal", va="center", annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=col, lw=1.2, alpha=0.8, shrinkA=0, shrinkB=0), zorder=8)
        right_boxes.append((txt, ann))
    dot, word = _dir_head(direction)
    fig.text(0.03, 0.935, f"{word}  {ticker(symbol)}", color=(DOWN if short else UP), fontsize=34, fontweight="bold", va="center")
    fig.text(0.03, 0.015, "15 хв · аналіз, не ордер", color="#6b778c", fontsize=14, va="bottom")
    from matplotlib.text import Text as _Text

    fig.canvas.draw()   # позиції підписів-анотацій уточнюються лише під час малювання
    for _ in range(8):   # довгі ціни (дешеві монети): зменшуємо шрифт підписів справа, доки все не вміститься
        if not right_boxes or max(_Text.get_window_extent(a, renderer).x1 for _t, a in right_boxes) <= fig.bbox.width - 8:
            break
        for _t, a in right_boxes:
            a.set_fontsize(max(11.0, a.get_fontsize() - 1.5))
        fig.canvas.draw()
    fh = fig.bbox.height
    boxes = [("ev", *(b.x0, fh - b.y1, b.x1, fh - b.y0)) for b in placed]   # екранні (піксельні) прямокутники підписів: перевірка «нічого не накладається»
    for txt, ann in right_boxes:
        b = _Text.get_window_extent(ann, renderer)
        boxes.append((txt, b.x0, fh - b.y1, b.x1, fh - b.y0))
    fig.savefig(path, facecolor=BG, dpi=100)
    plt.close(fig)
    data = open(path, "rb").read()
    return {"ok": True, "path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
            "drawn": {"candles": n, "entry": [zlo, zhi], "sl": sl_, "tps": [t1, t2, t3], "tp3_edge": t3_edge, "ready": rp, "key_level": _f(key_level), "evidence": drawn_ev, "label_boxes": boxes, "labels_skipped": skipped, "size_px": [width_px, height_px]}}

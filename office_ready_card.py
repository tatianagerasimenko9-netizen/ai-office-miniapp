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


def short_why(*, tags: List[str], mode: Optional[str], direction: str, symbol: str, entry: Any, zone_lo: Any = None, zone_hi: Any = None, prefer: Any = None) -> str:
    """1–2 коротких речення з цифрами: що саме сталося з ціною (а не назва патерну). Лише з реально збережених тегів."""
    short = str(direction or "").upper() == "SHORT"
    ts = [str(t) for t in (tags or [])]
    if prefer:   # «Чому» пояснює те, що реально намальовано на картці (докази з геометрією), а не довільний тег
        pf = [t for t in ts if t in {str(x) for x in prefer}]
        ts = pf or ts
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
        first = f"Схоже на фігуру розвороту біля {et}: закриття за лінією шиї, рух {way}."
    elif has("choch", "bos"):
        first = f"Рух на малих свічках змінив напрямок {way}, зона {zt} утримується."
    elif has("ote"):
        first = f"Після різкого руху ціна відкотилась у зону {zt}."
    elif has("displacement"):
        first = f"Був різкий рух {way}, ціна тримається біля {et}."
    elif next((t for t in ts if t in ("flag", "pennant", "ascending_triangle", "descending_triangle", "symmetrical_triangle", "rectangle", "rising_wedge", "falling_wedge")), None):
        first = f"Схоже на фігуру продовження: ціна вийшла {way} і тримається біля {et}."
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


def _ohlc_sha(cs: List[Dict[str, Any]], tsf: Any) -> str:
    """sha тих свічок, що реально намальовані (та сама формула, що й у знімку): доказ, що картка не змінила жодної свічки."""
    from office_ready_evidence import ohlc_sha

    return ohlc_sha([[tsf(c.get("ts")), float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"]), _f(c.get("volume"))] for c in cs])


def render(*, symbol: str, direction: str, candles: List[Dict[str, Any]], entry: Any, zone: Any = None, sl: Any, tp1: Any, tp2: Any = None, tp3: Any = None,
           ready_price: Any = None, key_level: Any = None, key_label: str = "рівень", evidence: Any = None, path: str, width_px: int = 1000, height_px: int = 800,
           learning: bool = False, extra_stops: Any = None, max_bars: int = 96, tf_label: Optional[str] = None, story: Optional[str] = None, inset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """PNG-картка. {'ok': True, 'path', 'sha256', 'size', 'drawn': {...}} або {'ok': False, 'reason'}."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": f"matplotlib: {type(exc).__name__}"}
    from office_user_messages import _dir_head, ticker

    cs = [c for c in (candles or []) if all(_f(c.get(k)) is not None for k in ("open", "high", "low", "close"))][-int(max_bars or 96):]
    if len(cs) < 12:
        return {"ok": False, "reason": "мало свічок"}
    short = str(direction or "").upper() == "SHORT"
    e, sl_, t1, t2, t3 = _f(entry), _f(sl), _price(tp1), _price(tp2), _price(tp3)
    zlo, zhi = _zone(entry, zone)
    if e is None or sl_ is None:
        return {"ok": False, "reason": "немає входу/стопа"}
    hi_c, lo_c = max(float(c["high"]) for c in cs), min(float(c["low"]) for c in cs)
    xs_ = [(_f(p_), n_) for p_, n_ in (extra_stops or []) if _f(p_) is not None]
    t2_edge = t3_edge = False
    if tf_label:     # нова картка: далекі цілі не стискають реальні свічки; ціль, яка зробила б свічки < 45 % висоти графіка, показується стрілкою біля краю з підписом (ціна — у блоках внизу)
        core = [hi_c, lo_c, e, sl_] + [x for x in (t1, zlo, zhi) if x is not None] + [p_ for p_, _n in xs_]
        top, bot = max(core), min(core)
        for k_, tv in ((2, t2), (3, t3)):
            if tv is None:
                continue
            nt, nb = max(top, tv), min(bot, tv)
            if (hi_c - lo_c) / max(nt - nb, 1e-12) >= 0.45:
                top, bot = nt, nb
            elif k_ == 2:
                t2_edge = True
            else:
                t3_edge = True
        span = max(top - bot, e * 0.002)
    else:
        core = [hi_c, lo_c, e, sl_] + [x for x in (t1, t2, zlo, zhi) if x is not None] + [p_ for p_, _n in xs_]
        top, bot = max(core), min(core)
        span = max(top - bot, e * 0.002)
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
    ax = fig.add_axes([0.02, 0.51 if inset else (0.12 if story else 0.05), 0.64 if tf_label else 0.55, 0.34 if inset else (0.73 if story else 0.80)], facecolor=BG)
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
    obstacles: List[Any] = []     # маркери й точки: підписи не лягають поверх
    placed: List[Any] = []        # зайняті прямокутники підписів (екранні координати): жоден підпис не лягає на інший
    skipped: List[str] = []

    MAX_LABEL_PX = 90.0   # підпис не може бути далі за стільки пікселів від своєї геометрії; немає місця поруч → без підпису (краще лінія без слова, ніж слово не там)
    label_dist: List[float] = []

    def put(txt: str, color: str, cands: List[Any], anchors: List[Any]) -> bool:
        """Ставить підпис у першому кандидаті: повністю в межах графіка, без перетину з уже поставленими й не далі MAX_LABEL_PX від геометрії (anchors — точки на ній, у даних)."""
        pts = [ax.transData.transform((float(ax_), float(ay_))) for ax_, ay_ in anchors]
        for x, y, ha, va in cands:
            t = ax.text(x, y, txt, color=color, fontsize=17, fontweight="bold", ha=ha, va=va, zorder=9)
            raw = t.get_window_extent(renderer)
            bb = raw.expanded(1.06, 1.3)
            dist = min((max(raw.x0 - px, 0.0, px - raw.x1) ** 2 + max(raw.y0 - py, 0.0, py - raw.y1) ** 2) ** 0.5 for px, py in pts) if pts else 0.0
            if (ax.bbox.x0 <= bb.x0 and bb.x1 <= ax.bbox.x1 and ax.bbox.y0 <= bb.y0 and bb.y1 <= ax.bbox.y1 and not any(bb.overlaps(o) for o in placed + obstacles)
                    and dist <= MAX_LABEL_PX):
                placed.append(bb)
                label_dist.append(round(float(dist), 1))
                return True
            t.remove()
        skipped.append(txt)
        return False

    def block(x: float, y: float, px: float = 16.0) -> None:
        """Маркер/точка — перешкода для підписів: текст не лягає поверх."""
        from matplotlib.transforms import Bbox

        cx, cy = ax.transData.transform((float(x), float(y)))
        obstacles.append(Bbox([[cx - px, cy - px], [cx + px, cy + px]]))

    def spots(x_left: float, x_right: float, y: float, dy: float) -> List[Any]:
        """Кандидати для підпису біля горизонтального відрізка: над/під, з лівого й правого краю."""
        return [(x_left, y + dy, "left", "bottom"), (x_right, y + dy, "right", "bottom"), (x_left, y - dy, "left", "top"), (x_right, y - dy, "right", "top")]

    def seg_anchors(xa_: float, xb_: float, y: float) -> List[Any]:
        return [(xa_ + (xb_ - xa_) * k / 6.0, y) for k in range(7)]

    _rp0 = _f(ready_price)
    if _rp0 is not None and y0 < _rp0 < y1:
        block(n - 1, _rp0, 16.0)   # маркер READY — перешкода для підписів доказів
    for it in (evidence or [])[:3]:   # спершу всі маркери доказів стають перешкодами, потім ставимо підписи
        try:
            if it.get("draw") == "break" and x_of(it.get("t0")) is not None and x_of(it.get("t_break")) is not None:
                block(x_of(it["t0"]), float(it["price"]))
                block(x_of(it["t_break"]), float(it["close"]))
            elif it.get("draw") == "sweep" and x_of(it.get("t_sweep")) is not None:
                block(x_of(it["t_sweep"]), float(it["extreme"]))
            elif it.get("draw") == "marker" and x_of(it.get("t")) is not None:
                block(x_of(it["t"]), float(it["price"]))
            elif it.get("draw") == "multi":
                for p_ in it.get("points") or []:
                    if x_of(p_.get("t")) is not None:
                        block(x_of(p_["t"]), float(p_["price"]))
                if x_of(it.get("t_confirm")) is not None:
                    block(x_of(it["t_confirm"]), float(it["close"]))
        except Exception:  # noqa: BLE001
            continue
    drawn_ev: List[str] = []
    for it in (evidence or [])[:3]:   # докази цього READY: лише те, що дало підтвердження (office_ready_evidence)
        try:
            kind, lab, dw = str(it.get("kind")), str(it.get("label") or ""), it.get("draw")
            if lab and dw in ("sweep", "break") and it.get("price") is not None:
                lab = f"{lab} {_num(it['price'], symbol)}"   # у підписі — сам рівень
            if dw == "lines":
                chan = kind == "channel_edge"
                first = None
                for ln in it.get("lines") or []:
                    x0, x1 = x_of(ln["t0"]), x_of(ln["t1"])
                    if x0 is None or x1 is None or x1 == x0:
                        continue
                    slope_ = (float(ln["p1"]) - float(ln["p0"])) / (x1 - x0)
                    xs, xe = max(x0, -1.0), n - 0.5
                    ya, yb = float(ln["p0"]) + slope_ * (xs - x0), float(ln["p0"]) + slope_ * (xe - x0)
                    mid = chan and ln.get("role") == "mid"
                    ax.plot([xs, xe], [ya, yb], color=EVC, linewidth=1.4 if chan else 2.6, linestyle=":" if mid else "-", alpha=0.75 if chan else 0.95, zorder=5)
                    if first is None:
                        first = (x0, x1, slope_, float(ln["p0"]))
                if first and lab:
                    x0, x1, sl0, p0 = first
                    xa, xb = max(x0, 0.0), min(max(x0, x1), n - 1.0)   # лише там, де лінія реально видна на графіку
                    ypt = lambda xx: p0 + sl0 * (xx - x0)  # noqa: E731
                    cands = [(xa - 0.8, ypt(xa), "right", "center")]   # зліва від початку лінії — там зазвичай порожньо
                    for fr in (0.5, 0.3, 0.7, 0.15, 0.85):
                        xl = xa + (xb - xa) * fr
                        cands += [(xl, ypt(xl) + rng * 0.03, "center", "bottom"), (xl, ypt(xl) - rng * 0.03, "center", "top")]
                    put(lab, EVC, cands, [(xa + (xb - xa) * k / 6.0, ypt(xa + (xb - xa) * k / 6.0)) for k in range(7)])
            elif dw == "band":   # FVG / рівень / OB / OTE: зона від t0 до t1 (або до кінця графіка)
                xs = max(-1.0, x_of(it.get("t0")) if x_of(it.get("t0")) is not None else -1.0)
                xe = min(n + 1.0, x_of(it.get("t1")) + 0.5) if x_of(it.get("t1")) is not None else n + 1.0
                lo_, hi_ = float(it["lo"]), float(it["hi"])
                ax.add_patch(Rectangle((xs, lo_), max(xe - xs, 0.5), max(hi_ - lo_, rng * 0.006), facecolor=EVC, alpha=0.18, edgecolor=EVC, linewidth=1.4, linestyle="--", zorder=1))
                if lab:
                    cands = spots(xs + 0.4, xe - 0.4, hi_ if True else lo_, rng * 0.008)[:2] + [(xs + 0.4, lo_ - rng * 0.008, "left", "top"), (xe - 0.4, lo_ - rng * 0.008, "right", "top")]
                    put(lab, EVC, cands, [(xs, hi_), (xs, lo_), (xe, hi_), (xe, lo_), ((xs + xe) / 2, hi_), ((xs + xe) / 2, lo_)])
            elif dw == "hline":
                xs = max(-1.0, x_of(it.get("t0")) if x_of(it.get("t0")) is not None else -1.0)
                ax.plot([xs, n - 0.5], [float(it["price"])] * 2, color=EVC, linewidth=2.0, linestyle="--", zorder=5)
                if lab:
                    put(lab, EVC, spots(xs + 0.6, n - 1.0, float(it["price"]), rng * 0.008), seg_anchors(xs, n - 1.0, float(it["price"])))
            elif dw == "break":   # BOS/CHoCH: структурний свінг → закриття за ним
                xs, xb_ = x_of(it.get("t0")), x_of(it.get("t_break"))
                if xs is None or xb_ is None:
                    continue
                pr = float(it["price"])
                ax.plot([max(xs, -1.0), min(xb_ + 2.0, n - 0.5)], [pr, pr], color=EVC, linewidth=2.2, linestyle="--", zorder=5)
                ax.scatter([xs], [pr], s=70, color=BG, edgecolors=EVC, linewidths=2, zorder=8)                 # свінг
                ax.scatter([xb_], [float(it["close"])], s=150, color=EVC, edgecolors=BG, linewidths=2, zorder=8)  # свічка, що закрилась за ним
                if lab:
                    xm = (max(xs, 0.0) + xb_) / 2
                    put(lab, EVC, [(xm, pr + rng * 0.03, "center", "bottom"), (xm, pr - rng * 0.03, "center", "top"), (xb_ + 1.5, pr + rng * 0.03, "left", "bottom"),
                                   (xs - 0.5, pr + rng * 0.03, "right", "bottom")], [(xs, pr), (xb_, pr), (xm, pr)])
            elif dw == "sweep":   # знятий рівень: лінія від першого дотику, тінь за рівень, закриття назад
                xs, xw = x_of(it.get("t0")), x_of(it.get("t_sweep"))
                if xs is None or xw is None:
                    continue
                pr, ex, cl = float(it["price"]), float(it["extreme"]), float(it["close"])
                ax.plot([max(xs, -1.0), min(xw + 3.0, n - 0.5)], [pr, pr], color=EVC, linewidth=2.2, linestyle="--", zorder=5)
                ax.plot([xw, xw], [ex, cl], color=EVC, linewidth=3.0, zorder=6)                       # тінь за рівень і повернення
                ax.scatter([xw], [ex], s=110, marker="v" if it.get("type") == "high" else "^", color=EVC, edgecolors=BG, zorder=8)
                if lab:
                    above = it.get("type") == "high"
                    d_ = rng * 0.035
                    put(lab, EVC, [(xw - 1.0, pr + (d_ if above else -d_), "right", "bottom" if above else "top"), (xw + 1.5, pr + (d_ if above else -d_), "left", "bottom" if above else "top"),
                                   (xw - 1.0, pr - (d_ if above else -d_), "right", "top" if above else "bottom")], [(xs, pr), (xw, pr), (xw, ex)])
            elif dw == "multi":   # подвійна/потрійна вершина або дно: реальні екстремуми + лінія шиї + свічка підтвердження
                pts = [(x_of(p_["t"]), float(p_["price"])) for p_ in it.get("points") or []]
                if not pts or any(px_ is None for px_, _ in pts):
                    continue
                neck, xc = float(it["neckline"]), x_of(it.get("t_confirm"))
                ax.plot([max(pts[0][0], -1.0), min((xc if xc is not None else n - 1) + 2.0, n - 0.5)], [neck, neck], color=EVC, linewidth=2.2, linestyle="--", zorder=5)
                for px_, py_ in pts:
                    ax.scatter([px_], [py_], s=110, marker="v" if short else "^", color=EVC, edgecolors=BG, zorder=8)
                if xc is not None:
                    ax.scatter([xc], [float(it["close"])], s=130, color=EVC, edgecolors=BG, linewidths=2, zorder=8)
                if lab:
                    xm = (pts[0][0] + pts[-1][0]) / 2
                    ytop = max(p_[1] for p_ in pts)
                    put(lab, EVC, [(xm, ytop + rng * 0.035, "center", "bottom"), (xm, ytop - rng * 0.035, "center", "top"), (pts[0][0] - 0.8, ytop, "right", "center")],
                        [(px_, py_) for px_, py_ in pts] + [(xm, neck)])
            elif dw == "marker" and x_of(it.get("t")) is not None:
                ax.scatter([x_of(it["t"])], [float(it["price"])], s=150, marker="v" if short else "^", color=EVC, edgecolors=BG, zorder=9)
                if lab:
                    xm, pm = x_of(it["t"]), float(it["price"])
                    put(lab, EVC, [(xm - 1.0, pm, "right", "center"), (xm + 1.0, pm, "left", "center"), (xm, pm + rng * 0.04, "center", "bottom"), (xm, pm - rng * 0.04, "center", "top")],
                        [(xm, pm)])
            drawn_ev.append(kind)
        except Exception:  # noqa: BLE001
            continue

    def hline(y: float, col: str, ls: str = "-", lw: float = 2.0) -> None:
        ax.axhline(y, color=col, linestyle=ls, linewidth=lw, zorder=2, alpha=0.95)

    if key_level is not None and _f(key_level) is not None and y0 < float(key_level) < y1 and abs(float(key_level) - e) > rng * 0.02:
        hline(float(key_level), "#8b96a8", "--", 1.4)
        labels.append((float(key_level), key_label, "#8b96a8", False))
    hline(sl_, SLC)
    labels.append((sl_, f"{('Стоп 1' if xs_ else 'Стоп') if learning else 'SL'}  {_num(sl_, symbol)}", SLC, True))
    for (p_, n_), col_ in zip(xs_, ("#FFB347", "#C792EA")):      # додаткові варіанти стопа (лише навчальні картки): інші кольори, пунктир
        if y0 < p_ < y1:
            hline(p_, col_, "--", 1.6)
            labels.append((p_, f"{n_}  {_num(p_, symbol)}", col_, True))
    for k, v in ((1, t1), (2, t2), (3, t3)):
        if v is None or (k == 3 and t3_edge) or (k == 2 and t2_edge):
            continue
        hline(v, TPC)
        labels.append((v, f"{'Ціль ' + str(k) if learning else 'TP' + str(k)}  {_num(v, symbol)}", TPC, True))
    for k_, tv, edge_ in ((2, t2, t2_edge), (3, t3, t3_edge)):
        if not edge_:
            continue
        up = (tv > e)
        xa_ = n * (0.40 if k_ == 2 else 0.60)
        ax.annotate("", xy=(xa_, y1 - rng * 0.005 if up else y0 + rng * 0.005), xytext=(xa_, (y1 if up else y0) + (-rng * 0.07 if up else rng * 0.07)),
                    arrowprops=dict(arrowstyle="-|>", color=TPC, lw=3), zorder=6)
        labels.append((y1 - rng * (0.02 if k_ == 3 else 0.075) if up else y0 + rng * (0.02 if k_ == 3 else 0.075), f"{'Ціль ' + str(k_) if learning else 'TP' + str(k_)}  {_num(tv, symbol)}", TPC, True))
    labels.append(((zlo + zhi) / 2, "ВХІД  " + (_num(zlo, symbol) if zlo == zhi else f"{_num(zlo, symbol)}–{_num(zhi, symbol)}"), YEL, True))
    rp = _f(ready_price)
    if rp is not None and y0 < rp < y1:
        block(n - 1, rp, 14.0)
        ax.scatter([n - 1], [rp], s=120, color="#ffffff", edgecolors=BG, linewidths=2, zorder=7)
        if not inset:     # зі вставкою M15 ціна READY підписана на ній (на основному графіку лишається крапка)
            labels.append((rp, f"{'Вхід (навчальний)' if learning else 'READY'}  {_num(rp, symbol)}", "#ffffff", True))
    # підписи справа без накладання: мінімальний крок 6,5% висоти
    gap = rng * (0.10 if inset else 0.065)
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
        ann = ax.annotate(txt, xy=(n + 1, y), xytext=(n + 3.2, yy), color=col, fontsize=(15 if inset else 20), fontweight="bold" if bold else "normal", va="center", annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=col, lw=1.2, alpha=0.8, shrinkA=0, shrinkB=0), zorder=8)
        right_boxes.append((txt, ann))
    if tf_label:
        ax.text(0.012, 0.975, f"{tf_label}", transform=ax.transAxes, color="#8fc2ff", fontsize=24, fontweight="bold", va="top", ha="left", zorder=10,
                bbox=dict(boxstyle="round,pad=0.25", facecolor=BG, edgecolor="none", alpha=0.85))        # таймфрейм на самому графіку
    if inset:
        try:
            _draw_inset(fig, inset, symbol, short, e, zlo, zhi, sl_, t1)
        except Exception as exc_in:  # noqa: BLE001
            skipped.append(f"inset:{type(exc_in).__name__}")
    dot, word = _dir_head(direction)
    fig.text(0.03, 0.935, f"{'Очікуємо падіння' if short else 'Очікуємо зростання'}  {ticker(symbol)}" if learning else f"{word}  {ticker(symbol)}", color=(DOWN if short else UP), fontsize=34 if not learning else 28, fontweight="bold", va="center")
    if story and not learning:
        fig.text(0.03, 0.066, story, color="#c9d6ea", fontsize=15, fontweight="bold", va="bottom")      # шлях сигналу: що було на графіку до READY (лише обчислені факти)
    fig.text(0.03, 0.015, "Навчальний сигнал · без реальних грошей · 15 хв" if learning else (f"{tf_label}{(' + ' + str(inset.get('label') or 'M15')) if inset else ''} · реальні закриті свічки Binance Futures · аналіз, не ордер" if tf_label else "15 хв · аналіз, не ордер"), color="#6b778c", fontsize=14, va="bottom")
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
    if not learning:
        try:
            _compose_telegram_card(path, symbol, direction, e, zlo, zhi, sl_, t1, t2, t3, tf_label)
        except Exception as exc:
            return {"ok": False, "reason": f"telegram_card_compose_failed: {type(exc).__name__}: {exc}"}
    data = open(path, "rb").read()
    return {"ok": True, "path": path, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
            "drawn": {"candles": n, "entry": [zlo, zhi], "sl": sl_, "tps": [t1, t2, t3], "tp3_edge": t3_edge, "tp2_edge": t2_edge, "tf": tf_label, "ready": rp, "key_level": _f(key_level), "evidence": drawn_ev, "label_boxes": boxes, "labels_skipped": skipped, "label_dist_px": label_dist, "ohlc_sha": _ohlc_sha(cs, _tsf), "size_px": [width_px, height_px]}}


def _draw_inset(fig: Any, inset: Dict[str, Any], symbol: str, short: bool, entry: float, zlo: float, zhi: float, sl: float, tp1: Optional[float]) -> None:
    """Збільшена вставка (зазвичай M15) для входу: реальні закриті свічки, зона входу виділена, вхід/SL/TP1, структурні позначки (sweep, зсув структури); ТФ підписано.
    Лише відображення: усі рівні — ті самі, що на основному графіку."""
    from matplotlib.patches import Rectangle
    from office_patterns import _ts as _tsf

    cs = [c for c in (inset.get("candles") or []) if all(_f(c.get(k)) is not None for k in ("open", "high", "low", "close"))][-int(inset.get("bars") or 56):]
    if len(cs) < 8:
        return
    n = len(cs)
    tt = [_tsf(c.get("ts")) for c in cs]
    step = sorted(tt[i + 1] - tt[i] for i in range(n - 1))[(n - 1) // 2] if all(t is not None for t in tt) and n > 2 else None
    xi = (lambda t: (float(t) - tt[0]) / step) if step else (lambda t: None)
    hi_c, lo_c = max(float(c["high"]) for c in cs), min(float(c["low"]) for c in cs)
    core = [hi_c, lo_c, zlo, zhi, entry, sl]
    top, bot = max(core), min(core)
    tp1_edge = False
    if tp1 is not None:
        nt, nb = max(top, tp1), min(bot, tp1)
        if (hi_c - lo_c) / max(nt - nb, 1e-12) >= 0.45:
            top, bot = nt, nb
        else:
            tp1_edge = True       # TP1 далеко: стрілка біля краю, свічки не стискаємо
    pad = (top - bot) * 0.08
    y0, y1 = bot - pad, top + pad
    rng = y1 - y0
    axi = fig.add_axes([0.02, 0.17, 0.64, 0.29], facecolor=BG)
    axi.set_xlim(-1, n + 1)
    axi.set_ylim(y0, y1)
    for sp in axi.spines.values():
        sp.set_visible(False)
    axi.set_xticks([])
    axi.set_yticks([])
    axi.add_patch(Rectangle((-1, zlo), n + 2, max(zhi - zlo, rng * 0.02), facecolor=YEL, alpha=0.30, edgecolor=YEL, linewidth=1.4, zorder=1))     # зона входу
    for i, c in enumerate(cs):
        o, h, l, cl = (float(c[k]) for k in ("open", "high", "low", "close"))
        col = UP if cl >= o else DOWN
        axi.vlines(i, l, h, color=col, linewidth=1.8, zorder=3)
        axi.add_patch(Rectangle((i - 0.34, min(o, cl)), 0.68, max(abs(cl - o), rng * 0.003), facecolor=col, edgecolor=col, zorder=4))
    axi.axhline(entry, color="#ffffff", linestyle="--", linewidth=1.3, zorder=2, alpha=0.85)
    axi.axhline(sl, color=SLC, linewidth=2.0, zorder=2)
    marks_ = [(entry, "ВХІД " + _num(entry, symbol), "#ffffff"), (sl, "SL " + _num(sl, symbol), SLC), ((zlo + zhi) / 2, "ЗОНА", YEL)]
    if tp1 is not None and y0 < tp1 < y1:
        axi.axhline(tp1, color=TPC, linewidth=2.0, zorder=2)
        marks_.append((tp1, "TP1 " + _num(tp1, symbol), TPC))
    elif tp1_edge:
        up_ = tp1 > entry
        axi.annotate("", xy=(n * 0.5, y1 - rng * 0.005 if up_ else y0 + rng * 0.005), xytext=(n * 0.5, y1 - rng * 0.09 if up_ else y0 + rng * 0.09), arrowprops=dict(arrowstyle="-|>", color=TPC, lw=2.5), zorder=6)
        marks_.append((y1 - rng * 0.03 if up_ else y0 + rng * 0.03, "TP1 " + _num(tp1, symbol), TPC))
    for it in inset.get("marks") or []:
        try:
            if it.get("draw") == "sweep" and xi(it["t_sweep"]) is not None:
                xs, xw = max(xi(it["t0"]), -1.0), xi(it["t_sweep"])
                axi.plot([xs, min(xw + 4, n)], [it["price"]] * 2, color=EVC, linewidth=1.6, linestyle="--", zorder=5)
                axi.scatter([xw], [it["extreme"]], s=90, marker="^" if it.get("type") == "low" else "v", color=EVC, edgecolors=BG, zorder=8)
                if y0 < it["price"] < y1:
                    marks_.append((it["price"], "Sweep " + _num(it["price"], symbol), EVC))
            elif it.get("draw") == "break" and xi(it["t_break"]) is not None:
                xs, xb = max(xi(it["t0"]), -1.0), xi(it["t_break"])
                axi.plot([xs, min(xb + 3, n)], [it["price"]] * 2, color=EVC, linewidth=1.6, linestyle="--", zorder=5)
                axi.scatter([xb], [it["close"]], s=80, color=EVC, edgecolors=BG, zorder=8)
                if y0 < it["price"] < y1:
                    marks_.append((it["price"], "Зсув " + _num(it["price"], symbol), EVC))
        except Exception:  # noqa: BLE001
            continue
    gap = rng * 0.11
    marks_.sort(key=lambda m: m[0])
    ys = []
    for y, *_ in marks_:
        ys.append(y if not ys else max(y, ys[-1] + gap))
    over = ys[-1] - (y1 - rng * 0.02)
    if over > 0:
        ys = [v - over for v in ys]
    for (y, txt, col), yy in zip(marks_, ys):
        axi.annotate(txt, xy=(n + 1, y), xytext=(n + 3.0, yy), color=col, fontsize=14, fontweight="bold", va="center", annotation_clip=False,
                     arrowprops=dict(arrowstyle="-", color=col, lw=1.0, alpha=0.7, shrinkA=0, shrinkB=0), zorder=8)
    axi.plot([n - 1], [entry], marker="o", markersize=9, color="#ffffff", markeredgecolor=BG, zorder=9)
    fig.text(0.03, 0.475, f"{inset.get('label') or 'M15'} · збільшено: вхід", color="#8fc2ff", fontsize=20, fontweight="bold", va="center", ha="left")      # ТФ вставки — над нею, не на свічках
    try:
        from office_ready_core import kyiv_stamp

        for idx in (0, n // 2, n - 1):
            if tt[idx] is not None:
                axi.text(idx, y0 - rng * 0.04, kyiv_stamp(tt[idx] + (step or 0))[6:], color="#6b778c", fontsize=11, ha="center", va="top", clip_on=False)      # час закриття свічки, Київ
    except Exception:  # noqa: BLE001
        pass


def _compose_telegram_card(path, symbol, direction, entry, zlo, zhi, sl, tp1, tp2, tp3, tf_label=None):
    """Compose a compact mobile-readable graphic around the existing truthful candle chart.

    No synthetic targets or candles; all numbers come from the frozen signal.
    """
    from PIL import Image, ImageDraw, ImageFont
    import os

    chart = Image.open(path).convert("RGB")
    width = chart.width
    scale = width / 1000.0
    height = int(1230 * scale)
    out = Image.new("RGB", (width, height), "#0c1422")
    d = ImageDraw.Draw(out)
    def u(n):
        return int(n * scale)
    def font(size, bold=False):
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        ]
        for p in candidates:
            if os.path.exists(p):
                return ImageFont.truetype(p, u(size))
        return ImageFont.load_default()
    def label(x, y, txt, size=25, color="#ffffff", bold=False):
        d.text((u(x), u(y)), str(txt), font=font(size, bold), fill=color)
    def box(x0, y0, x1, y1, bg, border=None):
        d.rounded_rectangle((u(x0), u(y0), u(x1), u(y1)), radius=u(20), fill=bg, outline=border, width=max(1,u(2)))
    short = str(direction).upper() == "SHORT"
    if tf_label:
        label(35, 20, f"ГРАФІК {tf_label} · BINANCE FUTURES", 31, "#8fc2ff", True)      # головний ТФ — великим шрифтом
    else:
        label(35, 24, "AI OFFICE  /  BINANCE FUTURES", 24, "#a4b5ce", True)
    label(35, 68, f"{symbol.replace('USDT','')} / USDT", 49, "#ffffff", True)
    box(730, 68, 965, 142, "#42232b" if short else "#103e31")
    label(752, 84, "SHORT" if short else "LONG", 35, "#ff949e" if short else "#64e6a7", True)
    chart_h = u(635)
    out.paste(chart if chart.size == (width, chart_h) else chart.resize((width, chart_h), Image.Resampling.LANCZOS), (0, u(158)))
    d = ImageDraw.Draw(out)
    def fmt(x):
        return _num(x, symbol)
    box(28, 809, 972, 943, "#152235", "#3c526d")
    label(52, 822, "ЗОНА ВХОДУ", 24, "#a8c4e4", True)
    label(52, 858, fmt(zlo) + (" – " + fmt(zhi) if zlo != zhi else ""), 37, "#ffffff", True)
    label(52, 909, "План " + fmt(entry), 22, "#b0bdd1")
    # Display all available take-profit levels in the image, not only TP1.
    targets = [("TP1", tp1), ("TP2", tp2), ("TP3", tp3)]
    visible = [(name, value) for name, value in targets if value is not None]
    if not visible:
        raise ValueError("READY card requires at least one take-profit target")
    gap = 12
    panel_width = (944 - gap * (len(visible) - 1)) // len(visible)
    for idx, (name, value) in enumerate(visible):
        x0 = 28 + idx * (panel_width + gap)
        x1 = x0 + panel_width
        box(x0, 961, x1, 1074, "#103729", "#147b52")
        label(x0 + 16, 975, name + " / TAKE PROFIT", 20 if len(visible) < 3 else 17, "#64e6a7", True)
        label(x0 + 16, 1011, fmt(value), 31 if len(visible) < 3 else 25, "#ffffff", True)
    box(28, 1090, 604, 1181, "#3b1b27", "#a23c4d")
    label(48, 1102, "SL / STOP LOSS", 21, "#ff999f", True)
    label(48, 1135, fmt(sl), 30, "#ffffff", True)
    rr = abs(tp1-entry)/abs(entry-sl) if tp1 is not None and entry != sl else None
    box(620, 1090, 972, 1181, "#152235", "#3c526d")
    label(642, 1102, "R/R ДО TP1", 21, "#a8c4e4", True)
    label(642, 1135, "1:" + (f"{rr:.2f}" if rr is not None else "—"), 30, "#ffcb68", True)
    label(37, 1192, "Деталі та супровід — у Telegram / Mini App", 18, "#9aaec9")
    out.save(path, format="PNG", optimize=True)

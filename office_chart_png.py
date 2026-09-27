"""PNG графіка до SIGNAL_ENTRY: mplfinance, без LLM.

Немає свічок → DATA_UNAVAILABLE, файл не малюємо.
Не змінює ATR 80/90, Edge 85, MIN_RR 1.5. Не ордер.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

DATA_UNAVAILABLE = "DATA_UNAVAILABLE"
DATA_OK = "DATA_OK"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _bars(candles: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(candles, list):
        return out
    for c in candles:
        if not isinstance(c, dict):
            continue
        o, h, l, cl = _f(c.get("open")), _f(c.get("high")), _f(c.get("low")), _f(c.get("close"))
        if None in (o, h, l, cl):
            continue
        ts = c.get("ts") or c.get("time") or ""
        out.append(
            {
                "open": o,
                "high": h,
                "low": l,
                "close": cl,
                "volume": _f(c.get("volume")) or 0.0,
                "ts": ts,
            }
        )
    return out


def _to_frame(rows: List[Dict[str, Any]]):
    import pandas as pd

    idx = []
    recs = []
    for r in rows:
        ts = r.get("ts")
        dt: Optional[datetime] = None
        if isinstance(ts, datetime):
            dt = ts
        elif ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                dt = None
        if dt is None:
            dt = datetime.fromtimestamp(len(idx), tz=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        idx.append(dt)
        recs.append(
            {
                "Open": r["open"],
                "High": r["high"],
                "Low": r["low"],
                "Close": r["close"],
                "Volume": r.get("volume") or 0.0,
            }
        )
    df = pd.DataFrame(recs, index=pd.DatetimeIndex(idx, name="Date"))
    if df.index.duplicated().any():
        df = df[~df.index.duplicated(keep="last")]
    return df.sort_index()


def chart_levels(
    *,
    sl: Any = None,
    tp1: Any = None,
    tp2: Any = None,
    tp3: Any = None,
    entry_low: Any = None,
    entry_high: Any = None,
    sc_low: Any = None,
    sc_high: Any = None,
    sweep: Any = None,
    asian_high: Any = None,
    asian_low: Any = None,
    mo: Any = None,
    bucket_60: Any = None,
    bucket_40: Any = None,
    last_price: Any = None,
    status: str = "",
    footer: str = "",
    scenario_tf: str = "",
    chart_tf: str = "",
    headline: str = "",
    wait_line: str = "",
    why_line: str = "",
    cancel_line: str = "",
    prev_line: str = "",
    demo: bool = False,
    calc_entry: Any = None,
) -> Dict[str, Any]:
    return {
        "sl": _f(sl),
        "tp1": _f(tp1),
        "tp2": _f(tp2),
        "tp3": _f(tp3),
        "entry_low": _f(entry_low),
        "entry_high": _f(entry_high),
        "sc_low": _f(sc_low),
        "sc_high": _f(sc_high),
        "sweep": _f(sweep),
        "asian_high": _f(asian_high),
        "asian_low": _f(asian_low),
        "mo": _f(mo),
        "bucket_60": _f(bucket_60),
        "bucket_40": _f(bucket_40),
        "last_price": _f(last_price),
        "status": str(status or ""),
        "footer": str(footer or ""),
        "scenario_tf": str(scenario_tf or ""),
        "chart_tf": str(chart_tf or ""),
        "headline": str(headline or ""),
        "wait_line": str(wait_line or ""),
        "why_line": str(why_line or ""),
        "cancel_line": str(cancel_line or ""),
        "prev_line": str(prev_line or ""),
        "demo": bool(demo),
        "calc_entry": _f(calc_entry),
    }


def _visible_hlines(levels: Dict[str, Any], y0: float, y1: float) -> Tuple[List[float], List[str], List[str]]:
    """Лише підписані SL/TP у видимому вікні — без безіменних ліній."""
    order = [("sl", "#ef6b7b", "-"), ("tp1", "#3dcf8a", "--")]
    ys: List[float] = []
    colors: List[str] = []
    styles: List[str] = []
    pad = (y1 - y0) * 0.02
    for key, col, st in order:
        v = levels.get(key)
        if v is None:
            continue
        fv = float(v)
        if fv < y0 - pad or fv > y1 + pad:
            continue
        ys.append(fv)
        colors.append(col)
        styles.append(st)
    return ys, colors, styles


def _view_window(
    *,
    candle_lo: float,
    candle_hi: float,
    zone_lo: Optional[float],
    zone_hi: Optional[float],
    sl: Optional[float] = None,
    last: Optional[float] = None,
) -> Tuple[float, float]:
    """Масштаб лише свічки + зона. SL/TP не розтягують вісь Y."""
    del sl, last
    lo = candle_lo
    hi = candle_hi
    if zone_lo is not None:
        lo = min(lo, zone_lo)
        hi = max(hi, zone_lo)
    if zone_hi is not None:
        lo = min(lo, zone_hi)
        hi = max(hi, zone_hi)
    span = max(hi - lo, abs(candle_hi - candle_lo), 1e-12)
    pad = span * 0.16
    return lo - pad, hi + pad


def _zone_band(en_lo: Optional[float], en_hi: Optional[float], y0: float, y1: float) -> Optional[Tuple[float, float]]:
    """Напівпрозора смуга зони. Точковий рівень — вузька, але видима смуга."""
    if en_lo is None and en_hi is None:
        return None
    lo = en_lo if en_lo is not None else en_hi
    hi = en_hi if en_hi is not None else en_lo
    if lo is None or hi is None:
        return None
    a, b = (lo, hi) if lo <= hi else (hi, lo)
    if abs(b - a) <= 1e-12:
        vis = max((y1 - y0) * 0.045, abs(a) * 0.0008, 1e-12)
        return a - vis, a + vis
    return a, b


def _fmt_px(v: Any, symbol: str) -> str:
    from office_price_format import format_px

    return format_px(v, symbol) or ""


def render_signal_chart(
    *,
    symbol: str,
    candles_m15: Any,
    candles_h1: Any = None,
    levels: Optional[Dict[str, Any]] = None,
    direction: str = "",
    out_path: Any = None,
) -> Dict[str, Any]:
    """Малює PNG. Порожні свічки → DATA_UNAVAILABLE."""
    m15 = _bars(candles_m15)
    h1 = _bars(candles_h1)
    empty = {"ok": False, "path": None, "data_status": DATA_UNAVAILABLE, "reason": "немає свічок"}
    if len(m15) < 8 and len(h1) < 8:
        return empty
    try:
        import matplotlib

        matplotlib.use("Agg")
        import mplfinance as mpf
    except Exception as exc:
        return {**empty, "reason": f"mplfinance unavailable: {type(exc).__name__}"}

    lv = dict(levels or {})
    path = str(out_path or "") or os.path.join(
        tempfile.gettempdir(),
        f"office_chart_{str(symbol or 'SYM').upper()}_{os.getpid()}.png",
    )
    try:
        import textwrap

        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec
        from matplotlib.patches import FancyBboxPatch
        from matplotlib.transforms import blended_transform_factory

        from office_price_format import format_level_span

        title_sym = str(symbol or "").upper()
        side = str(direction or "").upper()
        status = str(lv.get("status") or "WATCHING").strip() or "WATCHING"
        if len(m15) >= 8:
            chart_tf, rows, df = "M15", m15[-64:], _to_frame(m15[-64:])
        else:
            chart_tf, rows, df = "H1", h1[-48:], _to_frame(h1[-48:])
        scenario_tf = str(lv.get("scenario_tf") or "").upper() or chart_tf
        chart_tf = str(lv.get("chart_tf") or chart_tf).upper()
        en_lo, en_hi = _f(lv.get("entry_low")), _f(lv.get("entry_high"))
        if en_lo is not None and en_hi is not None and en_lo > en_hi:
            en_lo, en_hi = en_hi, en_lo
        last_px = _f(lv.get("last_price"))
        if last_px is None:
            last_px = rows[-1]["close"]
        sl_v = _f(lv.get("sl"))
        tp1_v = _f(lv.get("tp1"))
        calc_v = _f(lv.get("calc_entry"))
        c_lo = min(r["low"] for r in rows)
        c_hi = max(r["high"] for r in rows)
        y0, y1 = _view_window(candle_lo=c_lo, candle_hi=c_hi, zone_lo=en_lo, zone_hi=en_hi)
        accent = "#3dcf8a" if side == "LONG" else "#ef6b7b"
        panel_bg = "#152018" if side == "LONG" else "#201518"
        fig = plt.figure(figsize=(9.0, 14.4), facecolor="#101218")
        gs = GridSpec(2, 1, height_ratios=[1.55, 1.25], hspace=0.08, left=0.10, right=0.97, top=0.985, bottom=0.045)
        ax_t = fig.add_subplot(gs[0])
        ax = fig.add_subplot(gs[1])
        ax_t.set_facecolor(panel_bg)
        ax_t.axis("off")
        ax_t.add_patch(
            plt.Rectangle((0, 0.90), 1, 0.10, transform=ax_t.transAxes, color=accent, alpha=0.90, clip_on=False)
        )
        head = str(lv.get("headline") or "").strip() or f"{title_sym} · {side}"
        tf_line = f"сценарій {scenario_tf}  ·  графік {chart_tf}"
        wait = str(lv.get("wait_line") or "").strip() or (
            "Чекаю відкату в зону. Входу ще немає."
            if side == "LONG"
            else "Чекаю реакції M5 у зоні. Входу ще немає."
        )
        why = str(lv.get("why_line") or "").strip()
        prev = str(lv.get("prev_line") or "").strip()
        cancel = str(lv.get("cancel_line") or "").strip()
        for pref in ("Що скасує:", "що скасує:"):
            if cancel.lower().startswith(pref.lower()):
                cancel = cancel[len(pref) :].strip()
        demo = bool(lv.get("demo")) or "DEMO" in status.upper()
        zone_txt = format_level_span(en_lo, en_hi, title_sym) if en_lo is not None else ""
        ax_t.text(0.03, 0.95, head, color="#101218", fontsize=16, fontweight="bold", va="center")
        ax_t.text(0.97, 0.95, "WATCHING", color="#101218", fontsize=13, fontweight="bold", va="center", ha="right")
        ax_t.text(0.03, 0.84, tf_line, color="#d7dbe2", fontsize=12, va="center")
        ax_t.text(0.03, 0.75, "ВХОДУ НЕМАЄ", color=accent, fontsize=18, fontweight="bold", va="center")
        for y_slot, title, body in (
            (0.67, "Чого чекаю", wait),
            (0.54, "Чому сценарій", why),
            (0.41, "Що скасує", cancel),
            (0.32, "Що з попереднім", prev),
        ):
            if not body:
                continue
            ax_t.text(0.03, y_slot, title, color=accent, fontsize=10, fontweight="bold", va="center")
            ax_t.text(
                0.03,
                y_slot - 0.048,
                "\n".join(textwrap.wrap(body, width=70)[: (2 if title == "Що з попереднім" else 1)]),
                color="#e8eaed",
                fontsize=11,
                va="top",
                linespacing=1.25,
            )
        plan_lines = ["План після підтвердження — не /position"]
        if zone_txt:
            plan_lines.append(f"Зона {zone_txt}")
        if calc_v is not None:
            plan_lines.append(f"розрахунок від {_fmt_px(calc_v, title_sym)}")
        if sl_v is not None:
            extra = " поза шкалою" if not (y0 <= sl_v <= y1) else ""
            plan_lines.append(f"SL {_fmt_px(sl_v, title_sym)}{extra}")
        if tp1_v is not None:
            extra = " поза шкалою, лише після підтвердження" if not (y0 <= tp1_v <= y1) else ""
            plan_lines.append(f"TP1 {_fmt_px(tp1_v, title_sym)}{extra}")
        ax_t.text(0.03, 0.155, plan_lines[0], color="#b7bec8", fontsize=10, va="center")
        if len(plan_lines) > 1:
            ax_t.text(0.03, 0.11, " · ".join(plan_lines[1:3]), color="#b7bec8", fontsize=10, va="center")
        if len(plan_lines) > 3:
            ax_t.text(0.03, 0.065, " · ".join(plan_lines[3:]), color="#b7bec8", fontsize=10, va="center")
        if demo:
            ax_t.text(
                0.03,
                0.025,
                "DEMO/OFFLINE: синтетичні свічки лише для масштабу, не доказ патерну.",
                color="#8b919c",
                fontsize=9,
                va="center",
            )
        mc = mpf.make_marketcolors(up="#3dcf8a", down="#ef6b7b", inherit=True)
        st = mpf.make_mpf_style(
            base_mpf_style="nightclouds",
            marketcolors=mc,
            gridstyle="",
            facecolor="#0e1014",
            figcolor="#101218",
            y_on_right=False,
        )
        ys, cols, styles = _visible_hlines(lv, y0, y1)
        kw: Dict[str, Any] = dict(
            type="candle",
            ax=ax,
            style=st,
            axtitle="",
            xrotation=14,
            datetime_format="%H:%M",
            ylabel="",
            ylim=(y0, y1),
        )
        if ys:
            kw["hlines"] = dict(hlines=ys, colors=cols, linestyle=styles, linewidths=1.15)
        mpf.plot(df, **kw)
        band = _zone_band(en_lo, en_hi, y0, y1)
        if band is not None:
            span_frac = (band[1] - band[0]) / max(y1 - y0, 1e-12)
            fill_a = 0.14 if span_frac > 0.55 else 0.32
            ax.axhspan(band[0], band[1], color="#c9a227", alpha=fill_a, zorder=0)
            ax.axhline(band[0], color="#c9a227", linewidth=1.6, zorder=3)
            ax.axhline(band[1], color="#c9a227", linewidth=1.6, zorder=3)
            ztrans = blended_transform_factory(ax.transAxes, ax.transData)
            label_y = band[0] + (y1 - y0) * 0.03 if span_frac > 0.55 else band[1] - (y1 - y0) * 0.02
            ax.text(
                0.02,
                label_y,
                "зона спостереження",
                color="#f3e3a6",
                fontsize=9,
                fontweight="bold",
                va="bottom" if span_frac > 0.55 else "top",
                transform=ztrans,
                zorder=5,
            )
        ax.set_facecolor("#0e1014")
        ax.tick_params(colors="#8b919c", labelsize=9)
        for spine_name, spine in ax.spines.items():
            spine.set_color(accent if spine_name == "left" else "#2a2e36")
            if spine_name == "left":
                spine.set_linewidth(3.2)
        ax.grid(False)
        if last_px is not None:
            ax.axhline(last_px, color="#d7dbe2", linewidth=0.7, linestyle=":")
            ax.text(
                0.02,
                0.97,
                f"зараз {_fmt_px(last_px, title_sym)}",
                color="#d7dbe2",
                fontsize=9,
                ha="left",
                va="top",
                transform=ax.transAxes,
                zorder=8,
            )
        box_x, box_y = 0.48, 0.68
        if side == "LONG":
            box_txt = (
                "1) очікую відкат ДО зони — ще не вхід\n"
                "2) LONG лише після підтвердження M15/M5"
            )
        else:
            box_txt = (
                "1) зона спостереження — не продаж\n"
                "2) чекаю реакції M5 (умова лише з даних)\n"
                "3) після підтвердження — можливий SHORT до TP"
            )
        ax.add_patch(
            FancyBboxPatch(
                (box_x, box_y),
                0.46,
                0.22 if side == "LONG" else 0.28,
                boxstyle="round,pad=0.012,rounding_size=0.02",
                transform=ax.transAxes,
                facecolor="#161920",
                edgecolor=accent,
                linewidth=1.2,
                alpha=0.92,
                zorder=6,
            )
        )
        ax.text(
            box_x + 0.02,
            box_y + (0.11 if side == "LONG" else 0.14),
            box_txt,
            color="#e8eaed",
            fontsize=9,
            va="center",
            transform=ax.transAxes,
            zorder=7,
            linespacing=1.35,
        )
        fig.savefig(path, dpi=140, facecolor=fig.get_facecolor())
        plt.close(fig)
    except Exception as exc:
        return {**empty, "reason": f"{type(exc).__name__}: {exc}"}
    if not os.path.isfile(path) or os.path.getsize(path) < 64:
        return {**empty, "reason": "порожній PNG"}
    return {"ok": True, "path": path, "data_status": DATA_OK, "reason": ""}

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
    }


def _hlines(levels: Dict[str, Any]) -> Tuple[List[float], List[str], List[str]]:
    order = [
        ("sl", "#ff3b6b", "-"),
        ("tp1", "#00c853", "--"),
        ("tp2", "#00e5a0", "--"),
        ("tp3", "#f0b429", ":"),
        ("sweep", "#c084fc", "-."),
        ("mo", "#29b6f6", ":"),
        ("asian_high", "#f0b429", ":"),
        ("asian_low", "#f0b429", ":"),
        ("bucket_60", "#ffffff", "-"),
        ("bucket_40", "#f0b429", "--"),
    ]
    ys: List[float] = []
    colors: List[str] = []
    styles: List[str] = []
    seen = set()
    for key, col, st in order:
        v = levels.get(key)
        if v is None:
            continue
        mark = round(float(v), 8)
        if mark in seen:
            continue
        seen.add(mark)
        ys.append(float(v))
        colors.append(col)
        styles.append(st)
    return ys, colors, styles


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
    title = f"{str(symbol or '').upper()} {str(direction or '').upper()}".strip()
    try:
        panels: List[Tuple[str, Any]] = []
        if len(h1) >= 8:
            panels.append(("H1", _to_frame(h1[-48:])))
        if len(m15) >= 8:
            panels.append(("M15", _to_frame(m15[-96:])))
        if not panels:
            return empty
        n = len(panels)
        fig = mpf.figure(figsize=(11.2, 4.2 * n + 0.6), style="nightclouds")
        axes = [fig.add_subplot(n, 1, i + 1) for i in range(n)]
        ys, cols, styles = _hlines(lv)
        hline_kw: Dict[str, Any] = {}
        if ys:
            hline_kw = {
                "hlines": dict(hlines=ys, colors=cols, linestyle=styles, linewidths=1.1),
            }
        fill_kw = None
        sc_lo, sc_hi = _f(lv.get("sc_low")), _f(lv.get("sc_high"))
        en_lo, en_hi = _f(lv.get("entry_low")), _f(lv.get("entry_high"))
        fills = []
        if sc_lo is not None and sc_hi is not None and sc_hi > sc_lo:
            fills.append(dict(y1=sc_lo, y2=sc_hi, alpha=0.18, color="#7c4dff"))
        if en_lo is not None and en_hi is not None and abs(en_hi - en_lo) > 0:
            lo, hi = (en_lo, en_hi) if en_lo <= en_hi else (en_hi, en_lo)
            fills.append(dict(y1=lo, y2=hi, alpha=0.28, color="#00e5a0"))
        for i, (lab, df) in enumerate(panels):
            kw = dict(type="candle", ax=axes[i], axtitle=f"{title} · {lab}", xrotation=20, datetime_format="%m-%d %H:%M")
            if i == n - 1 and hline_kw:
                kw.update(hline_kw)
            if i == n - 1 and fills:
                kw["fill_between"] = fills if len(fills) > 1 else fills[0]
            mpf.plot(df, **kw)
        fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="#0d1117")
        import matplotlib.pyplot as plt

        plt.close(fig)
    except Exception as exc:
        return {**empty, "reason": f"{type(exc).__name__}: {exc}"}
    if not os.path.isfile(path) or os.path.getsize(path) < 64:
        return {**empty, "reason": "порожній PNG"}
    return {"ok": True, "path": path, "data_status": DATA_OK, "reason": ""}

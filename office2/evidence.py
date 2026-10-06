"""Office2 Brain v2: ФАКТИ з усіх підключених модулів для кандидата (READY). Це не голосування: кожен модуль має роль (brain2.REGISTRY),
EVIDENCE/CONTEXT потрапляють у тезу й трасу як ЗА/ПРОТИ/НЕЙТРАЛЬНО, а недоступне чесно позначається UNAVAILABLE / NOT_CONNECTED.
Дорогі мережеві модулі (OI/funding/L:S/ліквідації, M5) викликаються лише для кандидата на READY і тільки в потоці живого циклу."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from office2 import brain as B
from office2 import features as F


def _row(bars: Dict[str, np.ndarray], i: int) -> Dict[str, Any]:
    return {"ts": datetime.fromtimestamp(float(bars["t"][i]), tz=timezone.utc).isoformat(), "open": float(bars["o"][i]), "high": float(bars["h"][i]), "low": float(bars["l"][i]),
            "close": float(bars["c"][i]), "volume": float(bars["v"][i])}


def rows_from_arrays(bars: Dict[str, np.ndarray], k: int, n: int = 160) -> List[Dict[str, Any]]:
    """Лише ЗАКРИТІ бари ≤ k (адаптер numpy → рядки старих модулів Wyckoff/Bulkowski/канал)."""
    return [_row(bars, i) for i in range(max(0, k - n + 1), k + 1)]


def _item(name: str, role: str, status: str, finding: str = "", supports: int = 0, data: Any = None) -> Dict[str, Any]:
    return {"module": name, "role": role, "status": status, "finding": finding, "supports": supports, "data": data}


# ------------------------------------------------------------------ Gerchik mirror level
def mirror_level(ctx: Dict[str, Any], zone: List[float], direction: str, now: float, levels: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Role-flip: рівень, що був опором і став підтримкою (LONG) / навпаки (SHORT), біля зони входу ≤ 1 ATR(M15): ≥12 барів по інший бік → закриття за рівнем → ретест із відбоєм."""
    sg = 1 if direction == "LONG" else -1
    m15r = ctx["m15"]
    m = B.view(m15r, sg)
    k = F.last_closed(m15r, 900, now)
    a = float(ctx["atr15"][k])
    zl, zh = sorted([sg * zone[0], sg * zone[1]])
    out = None
    for x in levels:
        p = sg * x["p"]
        if abs(p - (zl + zh) / 2.0) > 1.0 * a + (zh - zl) / 2.0:
            continue
        c, l = m["c"][max(0, k - 400):k + 1], m["l"][max(0, k - 400):k + 1]
        below = np.flatnonzero(c < p)
        if len(below) < 12:
            continue
        last_below = int(below[-1])
        cross = next((i for i in range(last_below + 1, len(c)) if c[i] > p), None)
        if cross is None or len(c) - cross < 3:
            continue
        retest = [i for i in range(cross + 1, len(c)) if l[i] <= p + 0.5 * a and c[i] > p]
        if retest:
            out = {"level": x["p"], "kind": x["kind"], "bars_below_before": int(len(below)), "cross_bars_ago": int(len(c) - cross), "retests": len(retest)}
            break
    return out or {}


# ------------------------------------------------------------------ збір
def collect(ctx: Dict[str, Any], th: Dict[str, Any], direction: str, now: float, levels: List[Dict[str, Any]], flow_fetch: Optional[Callable[[], Dict[str, Any]]] = None,
            m5_fetch: Optional[Callable[[], Any]] = None) -> List[Dict[str, Any]]:
    sg = 1 if direction == "LONG" else -1
    m15r = ctx["m15"]
    k = F.last_closed(m15r, 900, now)
    items: List[Dict[str, Any]] = []
    zone = th.get("entry_zone") or th.get("zone") or [th.get("entry"), th.get("entry")]
    mid = (float(zone[0]) + float(zone[1])) / 2.0

    # HTF + premium/discount (CONTEXT)
    htf = B.htf_context(ctx, now)
    agree = [name for name in ("D1", "H4", "H1") if isinstance(htf.get(name), dict) and htf[name].get("trend") == sg]
    against = [name for name in ("D1", "H4", "H1") if isinstance(htf.get(name), dict) and htf[name].get("trend") == -sg]
    items.append(_item("HTF MN/W1/D1/H4/H1", "CONTEXT", "USED", f"за напрямом: {','.join(agree) or '—'}; проти: {','.join(against) or '—'}", (1 if len(agree) > len(against) else -1 if len(against) > len(agree) else 0), {k_: (v.get("trend") if isinstance(v, dict) else v) for k_, v in htf.items()}))
    h4 = htf.get("H4") or {}
    if h4.get("last_swing_high") is not None and h4.get("last_swing_low") is not None and h4["last_swing_high"] > h4["last_swing_low"]:
        pos = (mid - h4["last_swing_low"]) / (h4["last_swing_high"] - h4["last_swing_low"])
        good = (pos < 0.5) if sg > 0 else (pos > 0.5)
        items.append(_item("OB / FVG / OTE (premium-discount)", "EVIDENCE", "USED", f"зона в {'discount' if pos < 0.5 else 'premium'} діапазону H4 ({pos * 100:.0f}%): {'ЗА' if good else 'ПРОТИ'} {direction}", 1 if good else -1,
                           {"pos_in_h4_range": float(pos), "zone_parts": th.get("zone_parts")}))
    # mirror level
    ml = mirror_level(ctx, [float(zone[0]), float(zone[1])], direction, now, levels)
    items.append(_item("Gerchik mirror level + люфт", "EVIDENCE", "USED", (f"mirror {ml['kind']} {ml['level']:.6g}: був {'опором' if sg > 0 else 'підтримкою'}, ретестів {ml['retests']}" if ml else "mirror-рівня біля зони немає") + f"; люфт: {(th.get('invalidation') or {}).get('buffer_basis', '—')}", 1 if ml else 0, ml or None))
    # Wyckoff / Bulkowski / канал (H1)
    h1 = ctx["h1"]
    k1 = F.last_closed(h1, 3600, now)
    rows = rows_from_arrays(h1, k1, 160) if k1 > 40 else []
    if rows:
        try:
            import office_wyckoff as W

            ev = W.events(rows, now_ts=now)
            tags = [t for t in W.tags_for(rows, direction, now_ts=now)]
            items.append(_item("Wyckoff (spring/upthrust, тест)", "EVIDENCE", "USED", (f"{ev.get('phase')}; теги: {','.join(str(t.get('kind') or t) for t in tags)}" if tags else f"{ev.get('phase')}"), 1 if tags else 0, {"range": ev.get("range"), "events": ev.get("events")}))
        except Exception as exc:  # noqa: BLE001
            items.append(_item("Wyckoff (spring/upthrust, тест)", "EVIDENCE", "UNAVAILABLE", f"{type(exc).__name__}"))
        try:
            import office_bulkowski as BK

            pats = BK.confirmed_for(rows, direction, now_ts=now)
            items.append(_item("Bulkowski (формалізовані фігури)", "EVIDENCE", "USED", ("підтверджені за напрямом: " + ", ".join(str(p.get("kind")) for p in pats)) if pats else "підтвердженої фігури за напрямом немає", 1 if pats else 0, pats[:3] or None))
        except Exception as exc:  # noqa: BLE001
            items.append(_item("Bulkowski (формалізовані фігури)", "EVIDENCE", "UNAVAILABLE", f"{type(exc).__name__}"))
        try:
            import office_regression_channel as RC

            ch = RC.regression_channel(rows, length=min(100, len(rows) - 1), deviation=2.0)
            if ch.get("ok"):
                edge = float(ch["lower_end"] if sg > 0 else ch["upper_end"])
                sigma = (float(ch["upper_end"]) - float(ch["mid_end"])) / 2.0
                on_edge = abs(edge - mid) <= max(0.5 * sigma, abs(float(zone[1]) - float(zone[0])) / 2.0)
                items.append(_item("regression channel", "CONTEXT", "USED", f"межа каналу {edge:.6g} {'у зоні' if on_edge else 'поза зоною'}; нахил {float(ch['slope']):+.4g}", 1 if on_edge and sg * float(ch["slope"]) >= 0 else 0, {"edge": edge}))
            else:
                items.append(_item("regression channel", "CONTEXT", "UNAVAILABLE", "канал не побудовано"))
        except Exception as exc:  # noqa: BLE001
            items.append(_item("regression channel", "CONTEXT", "UNAVAILABLE", f"{type(exc).__name__}"))
    # volume / taker-delta / CVD (M15, з tbv)
    e_ts = float((th.get("event") or {}).get("ts") or 0.0)
    i0 = int(np.searchsorted(m15r["t"], e_ts)) if e_ts else max(0, k - 20)
    seg_v, seg_b = m15r["v"][i0:k + 1], m15r["tbv"][i0:k + 1]
    if len(seg_v) >= 3 and np.all(np.isfinite(seg_b)):
        delta = 2.0 * seg_b - seg_v
        cvd = float(delta.sum())
        share = float(cvd / seg_v.sum()) if seg_v.sum() > 0 else 0.0
        items.append(_item("volume / taker-delta / CVD", "EVIDENCE", "USED", f"CVD з моменту події {cvd:+.4g} ({share * 100:+.0f}% обсягу): {'ЗА' if sg * share > 0.02 else 'ПРОТИ' if sg * share < -0.02 else 'нейтрально'} {direction}", 1 if sg * share > 0.02 else -1 if sg * share < -0.02 else 0, {"cvd": cvd, "share": share}))
    else:
        items.append(_item("volume / taker-delta / CVD", "EVIDENCE", "UNAVAILABLE", "замало барів"))
    # OI / funding / L:S / ліквідації (RESEARCH)
    if flow_fetch is not None:
        try:
            fl = flow_fetch() or {}
        except Exception as exc:  # noqa: BLE001
            fl = {"error": type(exc).__name__}
        have = [k_ for k_ in ("oi", "funding", "long_short", "liquidations") if fl.get(k_)]
        items.append(_item("OI / funding / L:S / ліквідації", "RESEARCH", "USED" if have else "UNAVAILABLE", ("зібрано: " + ", ".join(have)) if have else "дані недоступні", 0, fl or None))
    else:
        items.append(_item("OI / funding / L:S / ліквідації", "RESEARCH", "UNAVAILABLE", "не запитано"))
    # M5 мікро-тригер (EVIDENCE)
    if m5_fetch is not None:
        try:
            m5 = m5_fetch()
        except Exception:  # noqa: BLE001
            m5 = None
        if isinstance(m5, dict) and len(m5.get("t", [])) >= 6:
            c, h, l = m5["c"], m5["h"], m5["l"]
            micro = bool(sg * (c[-1] - (h[-4:-1].max() if sg > 0 else l[-4:-1].min())) > 0)
            items.append(_item("M5/M1 тригер", "EVIDENCE", "USED", f"M5: закриття {'вище максимуму' if sg > 0 else 'нижче мінімуму'} 3 попередніх барів — {'так' if micro else 'ні'}", 1 if micro else 0, {"micro_bos": micro}))
        else:
            items.append(_item("M5/M1 тригер", "EVIDENCE", "UNAVAILABLE", "M5 недоступні"))
    else:
        items.append(_item("M5/M1 тригер", "EVIDENCE", "UNAVAILABLE", "не запитано"))
    for name, why in (("DOM / order book", "немає надійного джерела"), ("GEX / options", "немає джерела"), ("макро-календар", "office_calendar не підключено до Office2")):
        items.append(_item(name, "NOT_CONNECTED", "NOT_CONNECTED", why))
    return items


def summary(items: List[Dict[str, Any]]) -> Dict[str, int]:
    return {"for": sum(1 for i in items if i["supports"] > 0), "against": sum(1 for i in items if i["supports"] < 0), "neutral": sum(1 for i in items if i["supports"] == 0 and i["status"] == "USED"),
            "unavailable": sum(1 for i in items if i["status"] in ("UNAVAILABLE", "NOT_CONNECTED"))}

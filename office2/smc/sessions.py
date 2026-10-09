"""Сесії, killzones, NYM, PO3/AMD, Judas Swing — з коректним DST (zoneinfo): Europe/Kyiv (Борисполь), America/New_York, UTC.
Вікна джерела (London 03–07, Asia 09–12, NY 14–17, «optimal» 10:00–11:30 / 15:00–17:00) подано як «UTC+3 / KZ»: це НЕ годинник Борисполя і не канонічні NY-вікна (D-02).
Тому: (1) зберігаємо source-clock як є (фіксоване UTC+3); (2) показуємо канонічний профіль ICT у NY-часі з DST; (3) торгового gate на ці вікна НЕМАЄ, поки автор не уточнить.
Час у тексті — завжди Київ першим, UTC у дужках."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np

from office2.smc import core as K
from office2.smc.core import Arr

KYIV = ZoneInfo("Europe/Kyiv")
NY = ZoneInfo("America/New_York")
UTC = timezone.utc

SOURCE_KZ = {"LONDON": (3, 7), "ASIA": (9, 12), "NEW_YORK": (14, 17)}        # «UTC+3 / KZ» як у джерелі
SOURCE_OPTIMAL = [((10, 0), (11, 30)), ((15, 0), (17, 0))]
CANON_NY = {"ASIA": ((20, 0), (24, 0), -1), "LONDON": ((2, 0), (5, 0), 0), "NEW_YORK": ((7, 0), (10, 0), 0)}   # (початок, кінець, зсув дня), NY-час


def _ts(dt: datetime) -> float:
    return dt.timestamp()


def source_window_utc(day: date, name: str) -> Tuple[float, float]:
    """Вікно джерела в припущенні «UTC+3 — фіксоване зміщення» (без DST)."""
    h0, h1 = SOURCE_KZ[name]
    base = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return _ts(base + timedelta(hours=h0 - 3)), _ts(base + timedelta(hours=h1 - 3))


def canonical_window_utc(day: date, name: str) -> Tuple[float, float]:
    """Канонічне вікно (ICT) у НЬЮ-ЙОРКУ з DST для календарної дати NY `day`."""
    (h0, m0), (h1, m1), shift = CANON_NY[name]
    d0 = day + timedelta(days=shift)
    t0 = datetime(d0.year, d0.month, d0.day, h0, m0, tzinfo=NY)
    end_day = d0 + timedelta(days=1) if h1 == 24 else d0
    t1 = datetime(end_day.year, end_day.month, end_day.day, 0 if h1 == 24 else h1, m1, tzinfo=NY)
    return _ts(t0), _ts(t1)


def kyiv_text(ts: float) -> str:
    """«13:45 Київ (UTC 10:45)» — Київ першим, UTC у дужках."""
    d = datetime.fromtimestamp(ts, UTC)
    k = d.astimezone(KYIV)
    return f"{k:%d.%m %H:%M} Київ (UTC {d:%H:%M})"


def nym_utc(ts: float) -> float:
    """Північ Нью-Йорка (True Daily Open) для NY-доби, у яку потрапляє ts, у UTC-секундах. Враховує DST США (не 08:00 завжди!)."""
    n = datetime.fromtimestamp(ts, UTC).astimezone(NY)
    return _ts(datetime(n.year, n.month, n.day, 0, 0, tzinfo=NY))


def source_clock_note() -> str:
    return "Вікна killzone подано джерелом як «UTC+3 / KZ»; це не конвертований час Борисполя, торгового gate немає (D-02)."


def window_view(ts: float) -> Dict[str, Any]:
    """Де зараз ціна відносно обох інтерпретацій вікон; лише інформація."""
    d = datetime.fromtimestamp(ts, UTC)
    ny_day = d.astimezone(NY).date()
    out: Dict[str, Any] = {"now": kyiv_text(ts), "source_clock": source_clock_note(), "source_windows": {}, "canonical_windows": {}, "nym": {"utc": nym_utc(ts), "kyiv": kyiv_text(nym_utc(ts))}}
    for nm in ("LONDON", "ASIA", "NEW_YORK"):
        s0, s1 = source_window_utc(d.date(), nm)
        out["source_windows"][nm] = {"from": kyiv_text(s0), "to": kyiv_text(s1), "inside": s0 <= ts < s1}
        for dd in (ny_day, ny_day + timedelta(days=1)):
            c0, c1 = canonical_window_utc(dd, nm)
            if c0 <= ts < c1:
                out["canonical_windows"][nm] = {"from": kyiv_text(c0), "to": kyiv_text(c1), "inside": True}
                break
        else:
            c0, c1 = canonical_window_utc(ny_day, nm)
            out["canonical_windows"][nm] = {"from": kyiv_text(c0), "to": kyiv_text(c1), "inside": False}
    return out


def session_range(b: Arr, t0: float, t1: float, width: int = 900) -> Optional[Dict[str, Any]]:
    """High/Low сесії за ПОВНІСТЮ закритими барами всередині [t0, t1)."""
    idx = np.flatnonzero((b["t"] >= t0) & (b["t"] + width <= t1))
    if len(idx) == 0:
        return None
    i0, i1 = int(idx[0]), int(idx[-1])
    hi = i0 + int(np.argmax(b["h"][i0:i1 + 1]))
    lo = i0 + int(np.argmin(b["l"][i0:i1 + 1]))
    complete = bool(b["t"][-1] + width >= t1)
    return {"high": float(b["h"][hi]), "low": float(b["l"][lo]), "high_i": hi, "low_i": lo, "i0": i0, "i1": i1, "complete": complete, "t0": float(t0), "t1": float(t1), "bars": len(idx)}


def session_levels(b: Arr, now: float, width: int = 900) -> List[Dict[str, Any]]:
    """Рівні ліквідності: High/Low завершених канонічних сесій (Asia/London/NY) за 2 останні NY-доби. conf = перший бар після завершення сесії."""
    out: List[Dict[str, Any]] = []
    ny_today = datetime.fromtimestamp(now, UTC).astimezone(NY).date()
    for back in (0, 1, 2):
        dd = ny_today - timedelta(days=back)
        for nm in ("ASIA", "LONDON", "NEW_YORK"):
            t0, t1 = canonical_window_utc(dd, nm)
            if t1 > now:
                continue
            r = session_range(b, t0, t1, width)
            if not r or not r["complete"]:
                continue
            conf = int(np.searchsorted(b["t"], t1, side="left"))
            if conf >= len(b["t"]):
                continue
            out.append({"side": "high", "p": r["high"], "kind": f"{nm}_H", "i": r["high_i"], "conf": conf, "strength": 2, "tf": "session"})
            out.append({"side": "low", "p": r["low"], "kind": f"{nm}_L", "i": r["low_i"], "conf": conf, "strength": 2, "tf": "session"})
    return out


def judas(b: Arr, now: float, window_h: float = 4.0, min_exc_atr: float = 0.3, width: int = 900) -> Dict[str, Any]:
    """Judas Swing (схеми/текст S29): хибний рух відносно NYM у вікні після відкриття доби, потім основний рух у протилежний бік.
    Стани: NONE → FORMING (перевищення NYM, ще не повернулась) → JUDAS (повернення за NYM) → CONFIRMED (закриття за протилежним краєм вікна). Лише закриті бари ≤ now."""
    t_nym = nym_utc(now)
    idx0 = int(np.searchsorted(b["t"], t_nym, side="left"))
    if idx0 >= len(b["t"]) or b["t"][idx0] != t_nym:
        return {"state": "NO_DATA", "nym": None, "note": "немає бару на NYM (дані не покривають відкриття доби)"}
    nym = float(b["o"][idx0])
    a = K.atr_arr(b, 14)
    ia = K.atr_at(a, idx0)
    t_end = t_nym + window_h * 3600
    idx1 = int(np.searchsorted(b["t"] + width, min(now, t_end), side="right"))
    out: Dict[str, Any] = {"nym": nym, "nym_kyiv": kyiv_text(t_nym), "window_end_kyiv": kyiv_text(t_end), "state": "NONE", "dir": None}
    if idx1 <= idx0 or ia <= 0:
        return out
    # перший вихід за NYM на ≥ min_exc_atr·ATR задає бік маніпуляції (пізніші рухи в інший бік — вже «основний рух», не Judas)
    side = None
    first = None
    for j in range(idx0, idx1):
        u_, d_ = float(b["h"][j] - nym), float(nym - b["l"][j])
        if max(u_, d_) >= min_exc_atr * ia:
            side = "up" if u_ >= d_ else "down"
            first = j
            break
    if side is None:
        return out
    ret_j = next((j for j in range(first, idx1) if (side == "up" and b["c"][j] < nym) or (side == "down" and b["c"][j] > nym)), None)
    stop = (ret_j + 1) if ret_j is not None else idx1
    exc = float(b["h"][first:stop].max() - nym) if side == "up" else float(nym - b["l"][first:stop].min())
    out.update({"excursion_atr": round(exc / ia, 2), "side": side})
    k_ext = first + int(np.argmax(b["h"][first:stop])) if side == "up" else first + int(np.argmin(b["l"][first:stop]))
    ret = None
    for j in range(k_ext, idx1):
        if (side == "up" and b["c"][j] < nym) or (side == "down" and b["c"][j] > nym):
            ret = j
            break
    if ret is None:
        out.update({"state": "FORMING", "dir": "SHORT" if side == "up" else "LONG"})
        return out
    out.update({"state": "JUDAS", "dir": "SHORT" if side == "up" else "LONG", "returned_kyiv": kyiv_text(float(b["t"][ret]))})
    other = float(b["l"][idx0:ret + 1].min()) if side == "up" else float(b["h"][idx0:ret + 1].max())
    for j in range(ret + 1, len(b["t"])):
        if b["t"][j] + width > now:
            break
        if (side == "up" and b["c"][j] < other) or (side == "down" and b["c"][j] > other):
            out["state"] = "CONFIRMED"
            out["confirmed_kyiv"] = kyiv_text(float(b["t"][j]))
            break
    return out


def amd(b: Arr, now: float, width: int = 900, min_exc_atr: float = 0.15) -> Dict[str, Any]:
    """PO3/AMD (схема S28): Accumulation = діапазон Азії (канонічне NY-вікно), Manipulation = прокол краю з поверненням у діапазон, Distribution = закриття за протилежним краєм.
    Азійське вікно тут — ПРОКСІ (канонічне ICT), не вікно джерела (D-02)."""
    ny_day = datetime.fromtimestamp(now, UTC).astimezone(NY).date()
    t0, t1 = canonical_window_utc(ny_day + timedelta(days=1), "ASIA")
    if t1 > now + 86400:
        t0, t1 = canonical_window_utc(ny_day, "ASIA")
    for dd in (ny_day + timedelta(days=1), ny_day, ny_day - timedelta(days=1)):
        t0, t1 = canonical_window_utc(dd, "ASIA")
        if t1 <= now:
            break
    r = session_range(b, t0, t1, width)
    if not r or not r["complete"]:
        return {"stage": "NO_RANGE", "note": "Азійський діапазон ще не завершений або немає даних"}
    a = K.atr_arr(b, 14)
    ia = K.atr_at(a, r["i1"])
    out: Dict[str, Any] = {"stage": "A", "range": {"high": r["high"], "low": r["low"], "eq": (r["high"] + r["low"]) / 2}, "asia_kyiv": [kyiv_text(t0), kyiv_text(t1)]}
    start = r["i1"] + 1
    man = None
    for j in range(start, len(b["t"])):
        if b["t"][j] + width > now:
            break
        for side, lvl in (("high", r["high"]), ("low", r["low"])):
            exc = (b["h"][j] - lvl) if side == "high" else (lvl - b["l"][j])
            if exc >= min_exc_atr * ia and man is None:
                back = next((q for q in range(j, min(j + 4, len(b["t"]))) if (b["c"][q] < lvl if side == "high" else b["c"][q] > lvl) and b["t"][q] + width <= now), None)
                if back is not None:
                    man = {"side": side, "j": j, "back_j": back, "dir": "SHORT" if side == "high" else "LONG", "extreme": float(b["h"][j] if side == "high" else b["l"][j])}
    if man:
        out.update({"stage": "M", "manipulation": man, "dir": man["dir"]})
        opp = r["low"] if man["side"] == "high" else r["high"]
        for j in range(man["back_j"] + 1, len(b["t"])):
            if b["t"][j] + width > now:
                break
            if (man["side"] == "high" and b["c"][j] < opp) or (man["side"] == "low" and b["c"][j] > opp):
                out["stage"] = "D"
                break
    return out

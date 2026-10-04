"""Докази конкретного READY для картинки: лише те, що реально дало підтвердження (теги gate.confirm.tags), з геометрією з ТИХ САМИХ детекторів Office.

Нічого нового не вигадуємо: фігури (office_bulkowski), рівні (office_levels), FVG/OB/sweep/BOS/OTE (office_smc), регресійний канал (office_regression_channel).
Тег без відтворюваної геометрії на цих свічках не малюємо, а записуємо в `missing` (чесно). На картці максимум MAX_ITEMS елементів: найважливіші за PRIORITY.
Результат зберігається в знімку READY (gate.evidence) і не перераховується потім."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

MAX_ITEMS = 3
PATTERNS = ("head_shoulders", "inverse_head_shoulders", "ascending_triangle", "descending_triangle", "symmetrical_triangle", "rectangle", "rising_wedge",
            "falling_wedge", "flag", "pennant")
LABELS = {"head_shoulders": "голова і плечі", "inverse_head_shoulders": "перевернута голова і плечі", "ascending_triangle": "трикутник", "descending_triangle": "трикутник",
          "symmetrical_triangle": "трикутник", "rectangle": "коридор", "rising_wedge": "клин", "falling_wedge": "клин", "flag": "прапор", "pennant": "вимпел",
          "level_retest": "рівень", "level_hold": "рівень", "level_false_break": "рівень", "fvg_retest": "FVG", "ob_retest": "OB", "breaker_retest": "breaker",
          "sweep_pool": "зняли стопи", "bos": "BOS", "choch": "CHoCH", "channel_edge": "канал", "ote": "OTE", "displacement": "сильна свічка"}
PRIORITY = list(PATTERNS) + ["level_retest", "level_hold", "level_false_break", "channel_edge", "fvg_retest", "ob_retest", "breaker_retest", "sweep_pool", "choch", "bos", "ote", "displacement"]


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


def build(candles: Any, side: str, zone_lo: Any, zone_hi: Any, tags: List[str], now_ts: Optional[float] = None) -> Dict[str, Any]:
    from office_patterns import _ts, closed_only

    side = "SHORT" if str(side).upper() == "SHORT" else "LONG"
    rows = closed_only([r for r in (candles or []) if isinstance(r, dict)], now_ts)
    ts = [str(t) for t in (tags or [])]
    want = [t for t in PRIORITY if t in ts]
    zl, zh = _f(zone_lo), _f(zone_hi)
    if zl is not None and zh is not None and zl > zh:
        zl, zh = zh, zl
    items: List[Dict[str, Any]] = []
    missing: List[str] = []
    if len(rows) < 12:
        return {"items": [], "missing": want, "reason": "мало свічок"}

    def t_at(i: int) -> Optional[float]:
        return _ts(rows[max(0, min(len(rows) - 1, int(i)))].get("ts"))

    import office_smc as smc
    from office_patterns import atr as _atr

    a = _atr(rows[-120:]) or 0.0
    for kind in want:
        if len(items) >= MAX_ITEMS:
            break
        it: Optional[Dict[str, Any]] = None
        try:
            if kind in PATTERNS:
                from office_bulkowski import confirmed_for

                for p in confirmed_for(candles, side, now_ts=now_ts):
                    if p["kind"] == kind and p.get("lines"):
                        it = {"kind": kind, "draw": "lines", "lines": p["lines"], "level": p.get("level")}
                        break
            elif kind in ("level_retest", "level_hold", "level_false_break"):
                import office_levels as lv

                zs = [z for z in lv.zones(candles, now_ts) if zl is not None and z["hi"] >= zl and z["lo"] <= zh]
                if zs:
                    e = (zl + zh) / 2
                    z = min(zs, key=lambda z: abs((z["lo"] + z["hi"]) / 2 - e))
                    it = {"kind": kind, "draw": "band", "lo": z["lo"], "hi": z["hi"], "touches": z["touches"]}
            elif kind == "channel_edge":
                from office_regression_channel import regression_channel

                ch = regression_channel(candles, length=min(100, len(rows) - 1), deviation=2.0)
                if ch.get("ok") and ch.get("start_ts") and ch.get("end_ts"):
                    t0, t1 = _ts(ch["start_ts"]), _ts(ch["end_ts"])
                    if t0 is not None and t1 is not None:
                        it = {"kind": kind, "draw": "lines", "lines": [{"t0": t0, "p0": ch[k + "_start"], "t1": t1, "p1": ch[k + "_end"], "role": k} for k in ("upper", "mid", "lower")]}
            elif kind == "fvg_retest":
                lo_, hi_ = float(rows[-1]["low"]), float(rows[-1]["high"])
                r120 = rows[-120:]
                for g in smc.fvgs(r120, a)[-6:]:
                    if g["side"] == side and g["state"] == "MITIGATED" and lo_ <= g["hi"] and hi_ >= g["lo"] and g["idx"] < len(r120) - 3:
                        it = {"kind": kind, "draw": "band", "lo": g["lo"], "hi": g["hi"], "t0": _ts(r120[max(0, g["idx"] - 1)].get("ts"))}
                        break
            elif kind in ("ob_retest", "breaker_retest"):
                lo_, hi_ = float(rows[-1]["low"]), float(rows[-1]["high"])
                r120 = rows[-120:]
                for ob in smc.order_blocks(r120, a)[-4:]:
                    if ob["side"] == side and lo_ <= ob["hi"] and hi_ >= ob["lo"] and ob["idx"] < len(r120) - 3 and (ob["kind"] == "ob") == (kind == "ob_retest"):
                        it = {"kind": kind, "draw": "band", "lo": ob["lo"], "hi": ob["hi"], "t0": _ts(r120[ob["idx"]].get("ts"))}
                        break
            elif kind == "sweep_pool":
                r120 = rows[-120:]
                for s_ in smc.sweeps(r120, smc.liquidity_pools(r120, a), since=len(r120) - 6):
                    if s_["side"] == side:
                        it = {"kind": kind, "draw": "hline", "price": s_["level"], "t0": _ts(r120[max(0, s_["idx"] - 15)].get("ts")), "mark_t": _ts(r120[s_["idx"]].get("ts"))}
                        break
            elif kind in ("bos", "choch"):
                r120 = rows[-120:]
                for e in smc.structure(r120)["events"]:
                    if e["side"] == side and e["kind"] == kind and e["idx"] >= len(r120) - 4:
                        it = {"kind": kind, "draw": "hline", "price": e["level"], "t0": _ts(r120[max(0, e["idx"] - 12)].get("ts"))}
                        break
            elif kind == "ote":
                rng = smc.dealing_range(rows[-120:])
                if rng:
                    span = rng["high"] - rng["low"]
                    if side == "SHORT":
                        b0, b1 = rng["low"] + span * smc.OTE_LO, rng["low"] + span * smc.OTE_HI
                    else:
                        b0, b1 = rng["high"] - span * smc.OTE_HI, rng["high"] - span * smc.OTE_LO
                    it = {"kind": kind, "draw": "band", "lo": min(b0, b1), "hi": max(b0, b1)}
            elif kind == "displacement":
                r120 = rows[-120:]
                for d in smc.displacement(r120, a):
                    if d["side"] == side and d["idx"] >= len(r120) - 4:
                        r = r120[d["idx"]]
                        it = {"kind": kind, "draw": "marker", "t": _ts(r.get("ts")), "price": float(r["high"] if side == "LONG" else r["low"])}
                        break
        except Exception:  # noqa: BLE001
            it = None
        if it:
            it["label"] = LABELS.get(kind, kind)
            items.append(it)
        else:
            missing.append(kind)
    return {"items": items, "missing": missing}

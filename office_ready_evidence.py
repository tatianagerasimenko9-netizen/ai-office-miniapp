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
                        it = {"kind": kind, "draw": "lines", "lines": p["lines"], "level": p.get("level"), "detector": "office_bulkowski.detect_all", "rule": str(p.get("why") or ""),
                              "anchors": [{"t": ln[k], "price": ln["p" + k[1]], "role": "кінець лінії межі"} for ln in p["lines"] for k in ("t0", "t1")],
                              "proof_complete": False, "proof_note": "детектор віддає лише кінці ліній; свінги/дотики, через які їх проведено, не збережені (Pattern Engine 2.0)"}
                        break
            elif kind in ("level_retest", "level_hold", "level_false_break"):
                import office_levels as lv

                zs = [z for z in lv.zones(candles, now_ts) if zl is not None and z["hi"] >= zl and z["lo"] <= zh]
                if zs:
                    e = (zl + zh) / 2
                    z = min(zs, key=lambda z: abs((z["lo"] + z["hi"]) / 2 - e))
                    it = {"kind": kind, "draw": "band", "lo": z["lo"], "hi": z["hi"], "touches": z["touches"], "detector": "office_levels.zones",
                          "rule": f"кластер свінгів шириною ≤0,5×ATR, дотиків {z['touches']}", "anchors": [], "proof_complete": False,
                          "proof_note": "зона рівня збережена як межі; індекси свінгів-дотиків детектор не віддає"}
            elif kind == "channel_edge":
                from office_regression_channel import regression_channel

                ch = regression_channel(candles, length=min(100, len(rows) - 1), deviation=2.0)
                if ch.get("ok") and ch.get("start_ts") and ch.get("end_ts"):
                    t0, t1 = _ts(ch["start_ts"]), _ts(ch["end_ts"])
                    if t0 is not None and t1 is not None:
                        it = {"kind": kind, "draw": "lines", "lines": [{"t0": t0, "p0": ch[k + "_start"], "t1": t1, "p1": ch[k + "_end"], "role": k} for k in ("upper", "mid", "lower")],
                              "detector": "office_regression_channel.regression_channel", "rule": f"лінійна регресія по закриттях, довжина {ch.get('length')}, відхилення {ch.get('deviation')}σ",
                              "anchors": [{"t": t0, "price": ch["mid_start"], "role": "початок каналу (центр)"}, {"t": t1, "price": ch["mid_end"], "role": "кінець каналу (центр)"}],
                              "proof_complete": True}
            elif kind == "fvg_retest":
                lo_, hi_ = float(rows[-1]["low"]), float(rows[-1]["high"])
                r120 = rows[-120:]
                for g in smc.fvgs(r120, a)[-6:]:
                    if g["side"] == side and g["state"] == "MITIGATED" and lo_ <= g["hi"] and hi_ >= g["lo"] and g["idx"] < len(r120) - 3:
                        it = {"kind": kind, "draw": "band", "lo": g["lo"], "hi": g["hi"], "t0": _ts(r120[max(0, g["idx"] - 1)].get("ts")), "t1": _ts(r120[-1].get("ts")),
                              "direction": g["side"], "status": g["state"], "detector": "office_smc.fvgs",
                              "rule": "розрив між свічками i-1 та i+1 ≥0,25×ATR; стан за наступними свічками",
                              "anchors": [{"t": _ts(r120[max(0, g["idx"] - 1)].get("ts")), "price": float(r120[max(0, g["idx"] - 1)]["high" if g["side"] == "LONG" else "low"]),
                                           "role": "свічка 1 (край розриву)"},
                                          {"t": _ts(r120[g["idx"]].get("ts")), "price": float(r120[g["idx"]]["close"]), "role": "свічка 2 (імпульс)"},
                                          {"t": _ts(r120[min(len(r120) - 1, g["idx"] + 1)].get("ts")), "price": float(r120[min(len(r120) - 1, g["idx"] + 1)]["low" if g["side"] == "LONG" else "high"]),
                                           "role": "свічка 3 (край розриву)"}], "proof_complete": True}   # t0 — свічка 1 трійки, t1 — остання закрита свічка (ретест)
                        break
            elif kind in ("ob_retest", "breaker_retest"):
                lo_, hi_ = float(rows[-1]["low"]), float(rows[-1]["high"])
                r120 = rows[-120:]
                for ob in smc.order_blocks(r120, a)[-4:]:
                    if ob["side"] == side and lo_ <= ob["hi"] and hi_ >= ob["lo"] and ob["idx"] < len(r120) - 3 and (ob["kind"] == "ob") == (kind == "ob_retest"):
                        it = {"kind": kind, "draw": "band", "lo": ob["lo"], "hi": ob["hi"], "t0": _ts(r120[ob["idx"]].get("ts")), "detector": "office_smc.order_blocks",
                              "rule": "остання протилежна свічка перед displacement; пробите закриттям → breaker",
                              "anchors": [{"t": _ts(r120[ob["idx"]].get("ts")), "price": float(ob["hi"] if side == "SHORT" else ob["lo"]), "role": "свічка блоку"}], "proof_complete": True}
                        break
            elif kind == "sweep_pool":
                r120 = rows[-120:]
                pools = smc.liquidity_pools(r120, a)
                for s_ in smc.sweeps(r120, pools, since=len(r120) - 6):
                    if s_["side"] == side:
                        pool = next((p_ for p_ in pools.get(s_["pool"], []) if p_["level"] == s_["level"]), None)
                        c_ = r120[s_["idx"]]
                        high_ = s_["pool"] == "BSL"
                        it = {"kind": kind, "draw": "sweep", "price": s_["level"], "pool": s_["pool"], "type": "high" if high_ else "low",
                              "t0": _ts(r120[pool["first"]].get("ts")) if pool else _ts(r120[max(0, s_["idx"] - 15)].get("ts")),
                              "t_sweep": _ts(c_.get("ts")), "extreme": float(c_["high"] if high_ else c_["low"]), "close": float(c_["close"]),
                              "touches": pool["touches"] if pool else None, "detector": "office_smc.sweeps",
                              "rule": "тінь за рівень пулу ліквідності, закриття повернулось назад",
                              "anchors": [{"t": _ts(r120[pool["first"]].get("ts")), "price": s_["level"], "role": "перший дотик рівня"}] if pool else [],
                              "proof_complete": bool(pool)}
                        it["anchors"] += [{"t": _ts(c_.get("ts")), "price": float(c_["high"] if high_ else c_["low"]), "role": "екстремум тіні"},
                                          {"t": _ts(c_.get("ts")), "price": float(c_["close"]), "role": "закриття назад"}]
                        break
            elif kind in ("bos", "choch"):
                r120 = rows[-120:]
                hi_sw, lo_sw = smc.swings(r120)
                for e in smc.structure(r120)["events"]:
                    if e["side"] == side and e["kind"] == kind and e["idx"] >= len(r120) - 4:
                        sw = hi_sw[-1] if side == "LONG" else lo_sw[-1]   # структурний свінг, за який закрилась свічка (як у office_smc.structure)
                        if abs(sw[1] - e["level"]) > 1e-12:
                            break
                        it = {"kind": kind, "draw": "break", "price": e["level"], "t0": _ts(r120[sw[0]].get("ts")), "t_break": _ts(r120[e["idx"]].get("ts")),
                              "close": float(r120[e["idx"]]["close"]), "detector": "office_smc.structure", "rule": "закриття за останнім свінгом (BOS — у бік тренду, CHoCH — проти)",
                              "anchors": [{"t": _ts(r120[sw[0]].get("ts")), "price": e["level"], "role": "структурний свінг"},
                                          {"t": _ts(r120[e["idx"]].get("ts")), "price": float(r120[e["idx"]]["close"]), "role": "закриття за свінгом"}], "proof_complete": True}
                        break
            elif kind == "ote":
                rng = smc.dealing_range(rows[-120:])
                if rng:
                    span = rng["high"] - rng["low"]
                    if side == "SHORT":
                        b0, b1 = rng["low"] + span * smc.OTE_LO, rng["low"] + span * smc.OTE_HI
                    else:
                        b0, b1 = rng["high"] - span * smc.OTE_HI, rng["high"] - span * smc.OTE_LO
                    it = {"kind": kind, "draw": "band", "lo": min(b0, b1), "hi": max(b0, b1), "detector": "office_smc.dealing_range", "rule": "OTE 0,62–0,79 діапазону останніх свінгів",
                          "anchors": [], "proof_complete": False, "proof_note": "межі діапазону (свінги) не збережені окремо"}
            elif kind == "displacement":
                r120 = rows[-120:]
                for d in smc.displacement(r120, a):
                    if d["side"] == side and d["idx"] >= len(r120) - 4:
                        r = r120[d["idx"]]
                        it = {"kind": kind, "draw": "marker", "t": _ts(r.get("ts")), "price": float(r["high"] if side == "LONG" else r["low"]), "detector": "office_smc.displacement",
                              "rule": "тіло ≥ порогу ATR із закриттям біля краю", "anchors": [{"t": _ts(r.get("ts")), "price": float(r["high"] if side == "LONG" else r["low"]), "role": "сильна свічка"}],
                              "proof_complete": True}
                        break
        except Exception:  # noqa: BLE001
            it = None
        if it:
            it["label"] = LABELS.get(kind, kind)
            items.append(it)
        else:
            missing.append(kind)
    return {"items": items, "missing": missing}


# ------------------------------------------------------------------ знімок графіка та аудит
CHART_BARS = 96


def freeze_chart(candles: Any, decided_ts: float, tf: str = "15m") -> Dict[str, Any]:
    """Свічки, на яких прийнято рішення READY: точні OHLCV із часом і джерелом. Картка малює ТІЛЬКИ їх; доказ рахується з них же."""
    import hashlib
    import json

    from office_patterns import _ts

    rows = [r for r in (candles or []) if isinstance(r, dict) and _ts(r.get("ts")) is not None and all(_f(r.get(k)) is not None for k in ("open", "high", "low", "close"))][-CHART_BARS:]
    data = [[_ts(r["ts"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), _f(r.get("volume"))] for r in rows]
    srcs = sorted({str(r.get("src")) for r in rows if r.get("src")})
    return {"tf": tf, "source": ",".join(srcs) or "unknown", "decided_ts": float(decided_ts), "n": len(data), "range": [data[0][0], data[-1][0]] if data else None,
            "candles": data, "sha256": ohlc_sha(data)}


def ohlc_sha(data: Any) -> str:
    import hashlib
    import json

    return hashlib.sha256(json.dumps([[round(float(x), 10) if x is not None else None for x in row[:6]] for row in data], separators=(",", ":")).encode()).hexdigest()


def candles_from_chart(chart: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Свічки зі знімка назад у формат детекторів/картки (без жодних змін значень)."""
    from datetime import datetime, timezone

    out = []
    for t, o, h, l, c, v in ((row + [None])[:6] for row in (chart or {}).get("candles") or []):
        out.append({"ts": datetime.fromtimestamp(float(t), tz=timezone.utc).isoformat(), "open": o, "high": h, "low": l, "close": c, "volume": v})
    return out


def audit(gate: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Для кожного елемента картки: елемент → детектор → правило → опорні свічки (час, ціна) → чи збігаються з frozen-свічками. proof_complete=False — доказ неповний (чесно)."""
    chart = (gate or {}).get("chart") or {}
    by_t = {round(float(r[0]), 3): r for r in chart.get("candles") or []}
    out = []
    for it in (gate or {}).get("evidence") or []:
        rows = []
        for a in it.get("anchors") or []:
            c = by_t.get(round(float(a["t"]), 3)) if a.get("t") is not None else None
            on_candle = c is not None
            in_range = bool(c is not None and a.get("price") is not None and c[3] - 1e-9 <= float(a["price"]) <= c[2] + 1e-9)
            rows.append({"t": a.get("t"), "price": a.get("price"), "role": a.get("role"), "candle_exists": on_candle, "price_within_candle": in_range})
        out.append({"element": it.get("kind"), "label": it.get("label"), "detector": it.get("detector"), "rule": it.get("rule"), "anchors": rows,
                    "proof_complete": bool(it.get("proof_complete")), "proof_note": it.get("proof_note"),
                    "anchors_on_real_candles": all(r["candle_exists"] for r in rows) if rows else None})
    return out


def verify(gate: Dict[str, Any], direction: str, zone: Any, tags: List[str]) -> Dict[str, Any]:
    """Перевірка узгодженості: (1) sha свічок у знімку = sha свічок, які реально малює картка; (2) докази = вихід детекторів, перерахований на тих самих frozen-свічках на момент рішення."""
    chart = (gate or {}).get("chart") or {}
    problems: List[str] = []
    if chart.get("sha256") != ohlc_sha(chart.get("candles") or []):
        problems.append("sha свічок у знімку не збігається з їхнім вмістом")
    zl, zh = (zone or [None, None])[:2] if zone else (None, None)
    again = build(candles_from_chart(chart), direction, zl, zh, list(tags or []), now_ts=chart.get("decided_ts"))
    keep = lambda items: [{k: v for k, v in it.items() if k not in ("label",)} for it in items]  # noqa: E731
    import json

    if json.dumps(keep(again["items"]), sort_keys=True, default=str) != json.dumps(keep((gate or {}).get("evidence") or []), sort_keys=True, default=str):
        problems.append("докази у знімку не збігаються з виходом детекторів на frozen-свічках")
    return {"ok": not problems, "problems": problems}

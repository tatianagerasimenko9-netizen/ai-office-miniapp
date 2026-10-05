"""Популяція B для досліджень потоку: DISPLACEMENT-бар H1 (рішучий рух у напрямі угоди), вхід у напрямі руху.
Premise: початок руху (протилежний екстремум бару) тримається; структурна інвалідація = екстремум бару ∓ 0,5 ATR_H1. Лише закриті бари; майбутнє — тільки outcome."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from office2 import features as F
from office2 import outcome as O
from office2.narrative import _mirror, _session
from office2.pipeline import _entry_index
from office2.zone import _market, _room


@dataclass(frozen=True)
class DParams:
    body_atr: float = 1.5      # (close−open) у напрямі ≥ 1,5 ATR_H1 попереднього бару
    close_loc: float = 0.7     # закриття у верхніх 30% діапазону (у напрямі угоди)
    sl_buf: float = 0.5
    horizon_sec: int = 48 * 3600


DISP_OHLCV = ("body_atr", "range_atr", "close_loc", "vol_ratio", "prior_ret4", "prior_ret24", "atr_pct", "rel4", "reld", "btc_al", "room", "sess_asia", "sess_london", "sess_ny", "risk_atr", "adv_wick")


def candle_flow(h1: Dict[str, np.ndarray], j: int, sg: float, k0: Optional[int] = None) -> Dict[str, float]:
    """Taker-потік зі свічок (tbv): дельта бару, середня за 3 бари, CVD за 6 барів, дельта попередніх 6 — у напрямі угоди."""
    v, tbv = h1["v"], h1["tbv"]
    d = lambda a, b: float(sg * np.sum(2 * tbv[a:b] - v[a:b]) / max(np.sum(v[a:b]), 1e-12))
    out = {"tdelta_bar": d(j, j + 1), "tdelta_3": d(max(j - 2, 0), j + 1), "cvd6": d(max(j - 5, 0), j + 1), "tdelta_prior6": d(max(j - 11, 0), max(j - 5, 1))}
    return out


def build_records(symbol: str, ctx: Dict[str, Any], btc: Optional[Dict[str, Any]], p: DParams = DParams(), stats: Optional[Dict[str, int]] = None) -> List[dict]:
    st = stats if stats is not None else {}
    m1 = ctx["m1"]
    h1 = ctx.get("h1")
    if h1 is None:
        h1 = ctx["h1"] = F.resample(m1, 3600)
        ctx["atr1h"] = F.atr(h1, 14)
    atr = ctx["atr1h"]
    out: List[dict] = []
    for direction, bars in (("LONG", h1), ("SHORT", _mirror(h1))):
        sg = 1.0 if direction == "LONG" else -1.0
        o, h, l, c, v = bars["o"], bars["h"], bars["l"], bars["c"], bars["v"]
        n = len(c)
        last_j = -100
        for j in range(30, n - 1):
            a_prev = atr[j - 1]
            if np.isnan(a_prev) or a_prev <= 0 or j - last_j < 6:     # не частіше одного displacement на 6 барів (залежність подій)
                continue
            body = c[j] - o[j]
            rng = h[j] - l[j]
            if body < p.body_atr * a_prev or rng <= 0 or (c[j] - l[j]) / rng < p.close_loc:
                continue
            last_j = j
            t_open = float(h1["t"][j])
            t_dec = t_open + 3600.0
            ie = _entry_index(m1, t_dec)
            if ie is None:
                continue
            entry = float(m1["o"][ie])
            sl_t = float(l[j]) - p.sl_buf * float(atr[j])
            rec = O.outcome_record(m1, ie, direction, entry, sg * sl_t, float(atr[j]), p.horizon_sec)
            if rec is None:
                st["no_outcome"] = st.get("no_outcome", 0) + 1
                continue
            mk = _market(ctx, btc, symbol, t_dec, t_open, sg)
            sess = _session(t_dec)
            vr = float(v[j] / max(np.mean(v[j - 20:j]), 1e-12))
            feat = {"body_atr": float(body / a_prev), "range_atr": float(rng / a_prev), "close_loc": float((c[j] - l[j]) / rng), "vol_ratio": vr,
                    "prior_ret4": float((c[j - 1] - c[j - 5]) / a_prev), "prior_ret24": float((c[j - 1] - c[j - 25]) / a_prev), "atr_pct": float(atr[j] / abs(c[j]) * 100.0),
                    "rel4": float(mk["r4"]), "reld": float(mk["rd"]), "btc_al": float(np.clip((mk["btc4"] or 0.0) * sg, -3, 3)),
                    "room": float(_room(ctx, sg * float(c[j]), float(atr[j]), t_dec, sg)), "sess_asia": float(sess == 0), "sess_london": float(sess == 1), "sess_ny": float(sess == 2),
                    "risk_atr": float(rec["risk_atr"]), "adv_wick": float((h[j] - c[j]) / rng)}
            feat.update(candle_flow(h1, j, sg))
            r4_rel = float(sg * (h1["c"][j] - h1["c"][j - 4]) / a_prev)
            out.append({"pop": "DISP", "symbol": symbol, "dir": direction, "day": int(t_dec // 86400), "t_dec": t_dec, "feat": feat, "r4_rel": r4_rel, "j": j, **rec})
            st["events"] = st.get("events", 0) + 1
    return out

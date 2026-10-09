"""Блоки SM Trader: Order Block, Breaker, Mitigation (2 профілі), Rejection Block, Sponsored Candle (2 варіанти), StB/BtS.

Усі детектори працюють у координатах LONG на масиві b; SHORT — виклик на дзеркалі (core.mirror) і зворотне відображення зон (public-обгортки *_both).
OB без поглинання — не OB (S18). Блок «працює», поки тіло не закріпилось за MT (50% тіла блоку); тінь через MT — не злам. Один блок — один якісний тест (повторні — позначаються)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from office2.smc import core as K
from office2.smc.core import Arr

ENGULF_WINDOW = 3          # скільки барів після OB шукаємо закриття тілом за high свічки-блоку
OB_IMPULSE_ATR = 0.8       # імпульс поглинання (тіло свічки або серії), у ATR
WICK_MODE_BELOW = 0.40     # тіло/діапазон < 0.4 → блок по фітилях
BODY_MODE_ABOVE = 0.60     # ≥ 0.6 → по тілу; між — по тілу (за методичкою «спочатку по фітилях» — окремий параметр wick_first)
RJB_WICK_RATIO = 0.5       # частка тіні в діапазоні (калібрується історично)
RJB_MIN_WICK_ATR = 0.5
BB_DISP_ATR = 0.8
BB_MAX_BARS = 80           # вікно від формування блоку до його пробою


def _life(b: Arr, zone: List[float], mt: float, conf: int) -> Dict[str, Any]:
    """Життєвий цикл блоку-попиту: FRESH → TESTED_ONCE → RETESTED(≥2) ; INVALIDATED при закритті ТІЛА нижче MT. Тінь через MT — не злам."""
    lo, hi = zone
    N = len(b["t"])
    tests = 0
    inside_prev = False
    first_test = None
    for j in range(conf + 1, N):
        if b["c"][j] < mt:
            return {"state": "INVALIDATED", "tests": tests, "invalidated_i": int(j), "first_test_i": first_test}
        inside = b["l"][j] <= hi
        if inside and not inside_prev:
            tests += 1
            first_test = first_test if first_test is not None else int(j)
        inside_prev = inside
    st = "FRESH" if tests == 0 else ("TESTED_ONCE" if tests == 1 else "RETESTED")
    return {"state": st, "tests": tests, "invalidated_i": None, "first_test_i": first_test}


def order_blocks_bull(b: Arr, a: np.ndarray, sweeps: Optional[List[Dict[str, Any]]] = None, fvgs: Optional[List[Dict[str, Any]]] = None,
                      wick_first: bool = False) -> List[Dict[str, Any]]:
    """Бичачий OB: остання ведмежа свічка перед імпульсним поглинанням (закриття ТІЛОМ вище її high за ≤ ENGULF_WINDOW барів)."""
    out: List[Dict[str, Any]] = []
    o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    N = len(o)
    used_k = set()
    for k in range(1, N):
        ia = K.atr_at(a, k)
        if ia <= 0 or k in used_k:
            continue
        for i in range(k - 1, max(-1, k - 1 - ENGULF_WINDOW), -1):
            if c[i] < o[i] and c[k] > h[i]:
                move = float(c[k] - min(o[i + 1:k + 1].min(), c[i + 1:k + 1].min())) if k > i else 0.0
                body_k = float(c[k] - o[k])
                if max(body_k, float(c[k] - c[i])) < OB_IMPULSE_ATR * ia:
                    continue
                if np.any(c[i + 1:k] < l[i]):          # між блоком і поглинанням ціна вже закрилась нижче блоку → це не він
                    continue
                rng = float(h[i] - l[i])
                ratio = float(abs(c[i] - o[i]) / rng) if rng > 0 else 1.0
                mode = "wick" if (wick_first or ratio < WICK_MODE_BELOW) else "body"
                zone = [float(l[i]), float(h[i])] if mode == "wick" else [float(c[i]), float(o[i])]
                mt = float((o[i] + c[i]) / 2.0)
                liq = any(s["dir"] == "LONG" and i - 3 <= s["reclaim_j"] <= k + 1 for s in (sweeps or []))
                fvg_ov = any(f["dir"] == "LONG" and i + 1 <= f["conf"] <= k + 1 for f in (fvgs or []))
                life = _life(b, zone, mt, k)
                out.append({"kind": "OB", "dir": "LONG", "i": int(i), "conf": int(k), "zone": zone, "mode": mode, "wick_low": float(l[i]), "open": float(o[i]), "mt": mt,
                            "body_ratio": round(ratio, 3), "engulf_k": int(k), "impulse_atr": round(max(body_k, float(c[k] - c[i])) / ia, 2),
                            "liquidity_taken": bool(liq), "fvg": bool(fvg_ov), **life, "times": [float(b["t"][i]), float(b["t"][k])]})
                used_k.add(k)
                break
    # якщо кілька поглинань прив'язались до одного блоку — лишаємо найраніше
    seen = set()
    uniq = []
    for ob in sorted(out, key=lambda x: x["conf"]):
        if ob["i"] in seen:
            continue
        seen.add(ob["i"])
        uniq.append(ob)
    return uniq


def mirror_zone(z: List[float]) -> List[float]:
    return [float(-z[1]), float(-z[0])]


def unmirror_events(evs: List[Dict[str, Any]], dir_key: str = "dir") -> List[Dict[str, Any]]:
    """Дзеркальні події → реальні ціни (SHORT)."""
    out = []
    for e in evs:
        x = dict(e)
        x[dir_key] = "SHORT" if e[dir_key] == "LONG" else "LONG"
        for k in ("zone",):
            if x.get(k):
                x[k] = mirror_zone(x[k])
        for k in ("mt", "open", "wick_low", "extreme", "level", "sl_ref", "mid"):
            if x.get(k) is not None:
                x[k] = float(-x[k])
        if "wick_low" in x:
            x["wick_high"] = x.pop("wick_low")
        out.append(x)
    return out


def order_blocks(b: Arr, a: np.ndarray, sweeps_long=None, sweeps_short=None, fvgs_long=None, fvgs_short=None) -> List[Dict[str, Any]]:
    bull = order_blocks_bull(b, a, sweeps_long, fvgs_long)
    m = K.mirror(b)
    bear = unmirror_events(order_blocks_bull(m, a, sweeps_short, fvgs_short))
    return sorted(bull + bear, key=lambda x: x["conf"])


def breakers_bull(b: Arr, a: np.ndarray, supply_obs: List[Dict[str, Any]], ssl_sweeps: List[Dict[str, Any]], struct_events: List[Dict[str, Any]],
                  fvgs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Бичачий Breaker/Mitigation: ведмежий OB (попит→пропозиція) пробито ВГОРУ імпульсом.
    BB: перед пробоєм знято SSL (захват ліквідності) + MSS вгору. MB_SCHEME: MSS є, ліквідність НЕ знята («нет обновления минимума»).
    MB_TEXT: за текстом методички — продовження структури (BMS) без MSS і без зняття ліквідності. Профілі не зливаються (D-03)."""
    out: List[Dict[str, Any]] = []
    c, h, l = b["c"], b["h"], b["l"]
    N = len(c)
    for ob in supply_obs:
        zl, zh = ob["zone"]
        for j in range(ob["conf"] + 1, N):
            ia = K.atr_at(a, j)
            if c[j] > zh and ia > 0 and (c[j] - b["o"][j]) >= BB_DISP_ATR * ia:
                sw = [s for s in ssl_sweeps if ob["conf"] <= s["reclaim_j"] <= j]
                mss = [e for e in struct_events if e["kind"] == "MSS" and e["dir"] == "LONG" and ob["conf"] <= e["j"] <= j + 1]
                bms = [e for e in struct_events if e["kind"] == "BMS" and e["dir"] == "LONG" and ob["conf"] <= e["j"] <= j + 1]
                if sw and mss:
                    kind, prof = "BB", "BB"
                elif mss and not sw:
                    kind, prof = "MB", "MB_SCHEME"
                elif bms and not sw and not mss:
                    kind, prof = "MB", "MB_TEXT"
                else:
                    continue
                fvg = any(f["dir"] == "LONG" and j - 1 <= f["conf"] <= j + 1 for f in (fvgs or []))
                mt = (zl + zh) / 2.0
                st = "CREATED"
                retest = None
                for q in range(j + 1, N):
                    if c[q] < zl:
                        st = "INVALIDATED"
                        break
                    if l[q] <= zh and retest is None:
                        retest = int(q)
                        st = "RETESTED"
                out.append({"kind": kind, "profile": prof, "dir": "LONG", "i": ob["i"], "conf": int(j), "zone": [float(zl), float(zh)], "mt": float(mt), "state": st, "retest_i": retest,
                            "source_ob": ob["i"], "swept": [s["reclaim_j"] for s in sw], "mss_j": mss[0]["j"] if mss else None, "fvg_on_break": bool(fvg), "times": [float(b["t"][ob["i"]]), float(b["t"][j])]})
                break
            if j - ob["conf"] > BB_MAX_BARS:
                break
    return out


def rejection_blocks_bull(b: Arr, a: np.ndarray, ssl_sweeps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Бичачий RJB: довга нижня тінь, що проколола SSL/EQL, з реакцією вгору. Зона = тінь (від low до нижнього краю тіла), MT = 50% тіні (схеми 28–31)."""
    out: List[Dict[str, Any]] = []
    o, h, l, c = b["o"], b["h"], b["l"], b["c"]
    N = len(o)
    for s in ssl_sweeps:
        i = s["j"]
        if i >= N:
            continue
        ia = K.atr_at(a, i)
        rng = float(h[i] - l[i])
        wick = float(min(o[i], c[i]) - l[i])
        if rng <= 0 or ia <= 0 or wick / rng < RJB_WICK_RATIO or wick < RJB_MIN_WICK_ATR * ia:
            continue
        zone = [float(l[i]), float(min(o[i], c[i]))]
        mt = float((zone[0] + zone[1]) / 2.0)
        react = None
        for q in range(i + 1, min(N, i + 4)):
            if c[q] > h[i] or (c[q] - zone[1]) >= 1.0 * ia:
                react = int(q)
                break
        st = "REACTED" if react is not None else "UNCONFIRMED"
        if np.any(c[i + 1:] < mt):
            st = "INVALIDATED"
        out.append({"kind": "RJB", "dir": "LONG", "i": int(i), "conf": int(i), "zone": zone, "mt": mt, "wick_ratio": round(wick / rng, 3), "wick_atr": round(wick / ia, 2), "level": s["level"]["p"], "level_kind": s["level"]["kind"],
                    "reaction_i": react, "state": st, "times": [float(b["t"][i])]})
    return out


def sponsored_bull(b: Arr, a: np.ndarray, obs: List[Dict[str, Any]], ssl_sweeps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sponsored Candle (бичача): OB-свічка, яка зняла SSL. Два варіанти закриття тілом (D-04): SC_BODY_ABOVE — усе тіло над рівнем; SC_CLOSE_ABOVE — лише закриття над рівнем."""
    out: List[Dict[str, Any]] = []
    for ob in obs:
        i = ob["i"]
        for s in ssl_sweeps:
            if s["j"] <= i <= s["reclaim_j"] or s["j"] == i:
                lvl = s["level"]["p"]
                body_lo = float(min(b["o"][i], b["c"][i]))
                variant = "SC_BODY_ABOVE" if body_lo > lvl else "SC_CLOSE_ABOVE"
                out.append({"kind": "SC", "variant": variant, "verified": False, "dir": "LONG", "i": i, "conf": ob["conf"], "zone": ob["zone"], "mt": ob["mt"], "level": lvl, "level_kind": s["level"]["kind"],
                            "state": ob["state"], "times": ob["times"]})
                break
    return out


def stb_bull(b: Arr, a: np.ndarray, ssl_sweeps: List[Dict[str, Any]], struct_events: List[Dict[str, Any]], obs: List[Dict[str, Any]], max_gap_bars: int = 20) -> List[Dict[str, Any]]:
    """Sell-to-Buy: зняття SSL → MSS вгору. Зона = [екстремум проколу, зламаний MSS рівень]; POI всередині = бичачий OB/BB, що сформувався між проколом і MSS (схеми 34–36). Не доказ дій великих гравців."""
    out: List[Dict[str, Any]] = []
    for s in ssl_sweeps:
        mss = [e for e in struct_events if e["kind"] == "MSS" and e["dir"] == "LONG" and s["reclaim_j"] - 1 <= e["j"] <= s["reclaim_j"] + max_gap_bars]
        if not mss:
            continue
        e = mss[0]
        zone = [float(s["extreme"]), float(max(e["level"], s["extreme"]))]
        poi = [ob for ob in obs if ob["dir"] == "LONG" and s["j"] - 2 <= ob["conf"] <= e["j"] + 1]
        mt = float((zone[0] + zone[1]) / 2.0)
        st = "FORMED"
        for q in range(e["j"] + 1, len(b["c"])):
            if b["c"][q] < zone[0]:
                st = "INVALIDATED"
                break
            if b["l"][q] <= zone[1] and st == "FORMED":
                st = "RETESTED"
        out.append({"kind": "STB", "dir": "LONG", "i": int(s["j"]), "conf": int(e["j"]), "zone": zone, "mt": mt, "state": st, "sweep_j": int(s["reclaim_j"]), "mss_j": int(e["j"]),
                    "poi": [{"kind": p["kind"], "zone": p["zone"], "i": p["i"]} for p in poi[:2]], "level": s["level"]["p"], "times": [float(b["t"][s["j"]]), float(b["t"][e["j"]])]})
    return out

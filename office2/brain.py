"""Office 2.0 LIVE BRAIN: послідовність подій → тезa → структурна інвалідація → SL → цілі від реальних рівнів. Без score-голосування.

Стани сценарію: WATCH (область знайдена, атак ще нема) → WAIT (ціна в області/пробій триває, умови ще не виконані) → READY → далі життя плану (TP/SL) веде office_signal_track.
Завершення без READY: NO_TRADE (теза є, але чогось критичного бракує) / MISSED (рух пішов, входити пізно) / INVALIDATED (теза зламана).

Теза A «імпульс → відкат → стиснення → зона тримається → злам локальної структури → displacement → утримання» (MOVR-тип; дзеркально SHORT).
Теза B «sweep + reclaim ключового рівня + утримання».
Усе — лише за ЗАКРИТИМИ барами на момент now. Статус доказовості: UNPROVEN (N2/FLOW-1/v0 не показали OOS-переваги) — тому продукт позначений LIVE BETA.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from office2 import features as F

VERSION = "o2-brain-1"
EVIDENCE_STATUS = "UNPROVEN"
MIN_RISK_PCT, MAX_RISK_PCT = 0.15, 6.0
MIN_TP1_R = 1.0            # як у старому гейті «RR до цілі 1 ≥ 1,0»: ціль ближче за ризик — не угода
MAX_CHASE_R = 0.6          # входити не далі 0.6 ризику від рівня пробою/reclaim
IMPULSE_ATR = 3.0          # N2-визначення «сильного імпульсу» на H1
SESSIONS = (("ASIA", 0, 7), ("LONDON", 7, 13), ("NEW_YORK", 13, 21))

MODULES = {
    # Аудит фактичного production-коду (office2/brain.py, live.py, engine.py), а не документації. ACTIVE = бере участь у рішенні READY/SL/TP/ризику.
    "active": ["MN: PMH/PML (рівні попереднього місяця)", "W1/D1/H4/H1/M15 структура й тренд (htf_context)", "підтримка/опір: swing-рівні H1/M15/H4/D1", "PDH/PDL/PWH/PWL",
               "сесійні рівні (Asia/London/NY high/low)", "ліквідність BSL/SSL/EQH/EQL", "sweep + reclaim + утримання (acceptance за ≥1 бар)", "BOS/CHoCH (лише за наявності тренду)",
               "displacement (тіло ≥1.2 ATR, закриття в 35%)", "послідовність імпульс→відкат→зона→атаки→стиснення→злам (теза A, дзеркально SHORT)", "структурний SL + доказовий буфер",
               "цілі від реальних рівнів + перешкоди до TP1", "fixed-$ розмір позиції", "Risk Manager сценаріїв (ємність: ≤40$, ALT ≤30$, ≤3 альти в напрямі, 1 символ, 1 ідея/рівень, 3 SL/добу, ≤8 READY/добу)",
               "BTC/ETH контекст, breadth альтів, relative strength", "узгодженість ЗА/ПРОТИ/НЕЙТРАЛЬНО (align.py)"],
    "context_only": ["FVG (описова, у трасі)", "RSI (описовий; дивергенція не рахується)", "taker-дельта останнього бару (одна свічка, не CVD)", "режим волатильності 7д"],
    "research": ["OI/funding/L:S (office2/flowdata.py; FLOW-1 FAIL, у живому циклі не підключено)", "narrative/zone/disp-дослідження (research-пайплайн, не в живому рішенні)",
                 "Bulkowski / Wyckoff / regression channel (є у старому Леві: office_bulkowski/office_wyckoff/office_regression_channel — у трасі Office2 не використовуються)"],
    "unavailable_today": ["M5/M1 тригери (цикл на M15)", "3D/4D таймфрейми", "mirror levels (flip опір↔підтримка як окрема сутність)", "MSS як окрема подія (є лише BOS/CHoCH)", "OB / breaker / BPR (код відсутній)",
                          "OTE / premium-discount", "CVD / повна дельта", "ліквідації/heatmap (є office_liq_map/office_btc_liquidations у старому контурі; у Office2 не підключено)",
                          "DOM/order book", "BTC dominance/ринковий контекст за межами BTC/ETH/breadth", "GEX/options", "макро-календар (office_calendar є; у трасі Office2 не підключено)"],
}


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ допоміжне
def session_of(ts: float) -> str:
    import datetime as dt

    h = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).hour
    for name, a, b in SESSIONS:
        if a <= h < b:
            return name
    return "LATE"


def view(bars: Dict[str, np.ndarray], sg: int) -> Dict[str, np.ndarray]:
    """sg=+1 → як є. sg=-1 → дзеркало цін (p → −p, high↔low): теза LONG працює і для SHORT без дублювання коду."""
    if sg > 0:
        return bars
    return {"t": bars["t"], "o": -bars["o"], "h": -bars["l"], "l": -bars["h"], "c": -bars["c"], "v": bars["v"], "tbv": bars["tbv"], "n": bars.get("n", np.ones(len(bars["t"])))}


def complete_h1(m15: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """H1 з M15 лише повні години (по 4 бари): перший і останній (що формується) відкидаємо."""
    h1 = F.resample(m15, 3600)
    keep = np.flatnonzero(h1["n"] >= 4)
    return {k: v[keep] for k, v in h1.items()}


def noise_buffer(m15: Dict[str, np.ndarray], atr15: float) -> Tuple[float, str]:
    """Доказовий буфер за стоп: медіана глибини «проколів» локальних мінімумів M15, що закрилися назад (власні дані монети, останні ≤500 барів).
    Менше 5 прикладів → запасний 0.2·ATR(M15), позначено fallback."""
    l, c = m15["l"], m15["c"]
    depths: List[float] = []
    for j in range(10, len(l)):
        prev_min = float(l[j - 8:j].min())
        if l[j] < prev_min and c[j] > prev_min:
            depths.append(prev_min - float(l[j]))
    if len(depths) >= 5:
        return float(np.median(depths)), f"медіана {len(depths)} проколів M15"
    return 0.2 * atr15, "fallback 0.2·ATR(M15): мало проколів"


def htf_context(ctx: Dict[str, Any], now: float) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, bars, width in (("W1", ctx["w1"], 7 * F.DAY), ("D1", ctx["d1"], F.DAY), ("H4", ctx["h4"], 4 * 3600), ("H1", ctx["h1"], 3600), ("M15", ctx["m15"], 900)):
        k = F.last_closed(bars, width, now)
        if k < 5:
            out[name] = {"status": "UNAVAILABLE"}
            continue
        reg = F.regime_by_bar(bars)
        a = F.atr(bars, 14)
        sh, sl = F.swings(bars, 2)
        sh = [s for s in sh if s[1] <= k][-2:]
        sl = [s for s in sl if s[1] <= k][-2:]
        out[name] = {"trend": int(reg[k]), "atr": _f(a[k]), "close": float(bars["c"][k]), "last_swing_high": sh[-1][2] if sh else None, "last_swing_low": sl[-1][2] if sl else None,
                     "range_pos": _f((bars["c"][k] - bars["l"][max(0, k - 20):k + 1].min()) / max(1e-12, bars["h"][max(0, k - 20):k + 1].max() - bars["l"][max(0, k - 20):k + 1].min()))}
    for name in ("MN", "3D"):
        b = ctx.get(name.lower())
        out[name] = {"status": "CONTEXT"} if b is not None else {"status": "UNAVAILABLE"}
    out["4D"] = {"status": "UNAVAILABLE"}
    return out


def session_levels(m15: Dict[str, np.ndarray], now: float) -> List[Dict[str, Any]]:
    """H/L сесій (Азія/Лондон/Нью-Йорк) поточної та попередньої доби — рівні ліквідності, відомі на now."""
    import datetime as dt

    out: List[Dict[str, Any]] = []
    t = m15["t"]
    day0 = int(now // 86400) * 86400
    for dayoff in (0, -86400):
        for name, a, b in SESSIONS:
            lo_t, hi_t = day0 + dayoff + a * 3600, day0 + dayoff + b * 3600
            msk = (t >= lo_t) & (t + 900 <= min(hi_t, now))
            if msk.sum() >= 3 and hi_t <= now or (dayoff == 0 and msk.sum() >= 3):
                out.append({"p": float(m15["h"][msk].max()), "side": "high", "kind": f"{name}_H", "known": float(min(hi_t, now)), "strength": 1})
                out.append({"p": float(m15["l"][msk].min()), "side": "low", "kind": f"{name}_L", "known": float(min(hi_t, now)), "strength": 1})
    return out


def swing_levels(bars: Dict[str, np.ndarray], now: float, width: int, kind: str, n: int = 2, last: int = 6) -> List[Dict[str, Any]]:
    k = F.last_closed(bars, width, now)
    sh, sl = F.swings(bars, n)
    out = [{"p": s[2], "side": "high", "kind": kind, "known": float(bars["t"][s[1]] + width), "strength": 1} for s in sh if s[1] <= k][-last:]
    out += [{"p": s[2], "side": "low", "kind": kind, "known": float(bars["t"][s[1]] + width), "strength": 1} for s in sl if s[1] <= k][-last:]
    return out


def all_levels(ctx: Dict[str, Any], now: float) -> List[Dict[str, Any]]:
    lv = [x for x in ctx["levels"] if x["known"] <= now]
    lv += session_levels(ctx["m15"], now)
    lv += swing_levels(ctx["h1"], now, 3600, "H1SW")
    lv += swing_levels(ctx["m15"], now, 900, "M15SW", last=4)
    mn = ctx.get("mn")
    if mn is not None and len(mn["t"]) >= 2:   # PMH/PML: попередній (закритий) місяць
        lv.append({"p": float(mn["h"][-2]), "side": "high", "kind": "PMH", "known": float(mn["t"][-1]), "strength": 1})
        lv.append({"p": float(mn["l"][-2]), "side": "low", "kind": "PML", "known": float(mn["t"][-1]), "strength": 1})
    return lv


def liquidity_map(levels: List[Dict[str, Any]], price: float, atr: float) -> Dict[str, Any]:
    """BSL/SSL найближчі над/під ціною та EQH/EQL (рівні з strength ≥2 — кілька майже рівних екстремумів)."""
    up = sorted([x for x in levels if x["side"] == "high" and x["p"] > price], key=lambda x: x["p"])[:4]
    dn = sorted([x for x in levels if x["side"] == "low" and x["p"] < price], key=lambda x: -x["p"])[:4]
    f = lambda L: [{"p": x["p"], "kind": x["kind"], "strength": int(x.get("strength", 1)), "dist_atr": _f(abs(x["p"] - price) / atr) if atr else None, "eq": int(x.get("strength", 1)) >= 2} for x in L]  # noqa: E731
    return {"bsl_above": f(up), "ssl_below": f(dn)}


def targets_for(direction: str, entry: float, risk: float, levels: List[Dict[str, Any]], min_tp1_r: float = MIN_TP1_R) -> Dict[str, Any]:
    """TP — РЕАЛЬНІ перешкоди за напрямом (рівні/свінги), не від RR. TP1 — найближча перешкода від min_tp1_r ризику; ближчі (≥0.25 R) не губимо, а повертаємо як obstacles
    (трасується в знімку: ціна може зупинитись там). TP2/TP3 — наступні, ≥0.5 R від попередньої."""
    long_ = direction == "LONG"
    cand = [x for x in levels if (x["side"] == "high") == long_ and ((x["p"] - entry) if long_ else (entry - x["p"])) >= 0.25 * risk]
    cand.sort(key=lambda x: x["p"] if long_ else -x["p"])
    obstacles: List[Dict[str, Any]] = []
    out: List[Dict[str, Any]] = []
    for x in cand:
        d = abs(x["p"] - entry)
        item = {"p": float(x["p"]), "kind": x["kind"], "r": float(d / risk), "pct": float(d / entry * 100.0)}
        if not out and d < min_tp1_r * risk:
            if not obstacles or abs(x["p"] - obstacles[-1]["p"]) >= 0.1 * risk:
                obstacles.append(item)
            continue
        if out and abs(x["p"] - out[-1]["p"]) < 0.5 * risk:
            continue
        out.append(item)
        if len(out) == 3:
            break
    return {"targets": out, "obstacles_before_tp1": obstacles[:4]}


def local_structure(bars: Dict[str, np.ndarray], now: float, width: int = 900) -> Dict[str, Any]:
    """BOS/CHoCH лише при наявному тренді (HH+HL або LH+LL): без тренду жоден злам не називається CHoCH."""
    k = F.last_closed(bars, width, now)
    sh, sl = F.swings(bars, 2)
    sh = [s for s in sh if s[1] <= k]
    sl = [s for s in sl if s[1] <= k]
    trend = 0
    if len(sh) >= 2 and len(sl) >= 2:
        if sh[-1][2] > sh[-2][2] and sl[-1][2] > sl[-2][2]:
            trend = 1
        elif sh[-1][2] < sh[-2][2] and sl[-1][2] < sl[-2][2]:
            trend = -1
    c = float(bars["c"][k])
    ev = None
    if trend == 1 and sl and c < sl[-1][2]:
        ev = {"type": "CHoCH", "dir": "bearish", "level": sl[-1][2]}
    elif trend == -1 and sh and c > sh[-1][2]:
        ev = {"type": "CHoCH", "dir": "bullish", "level": sh[-1][2]}
    elif trend == 1 and sh and c > sh[-1][2]:
        ev = {"type": "BOS", "dir": "bullish", "level": sh[-1][2]}
    elif trend == -1 and sl and c < sl[-1][2]:
        ev = {"type": "BOS", "dir": "bearish", "level": sl[-1][2]}
    return {"trend": trend, "event": ev, "last_high": sh[-1][2] if sh else None, "last_low": sl[-1][2] if sl else None}


def fvg_list(bars: Dict[str, np.ndarray], now: float, width: int, last: int = 3) -> List[Dict[str, Any]]:
    k = F.last_closed(bars, width, now)
    out = []
    for j in range(max(2, k - 40), k + 1):
        if bars["l"][j] > bars["h"][j - 2]:
            out.append({"dir": "bullish", "lo": float(bars["h"][j - 2]), "hi": float(bars["l"][j])})
        elif bars["h"][j] < bars["l"][j - 2]:
            out.append({"dir": "bearish", "lo": float(bars["h"][j]), "hi": float(bars["l"][j - 2])})
    return out[-last:]


def rsi(c: np.ndarray, n: int = 14) -> Optional[float]:
    if len(c) < n + 2:
        return None
    d = np.diff(c[-(n * 3):])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    ru, rd = up[-n:].mean(), dn[-n:].mean()
    return float(100.0 - 100.0 / (1.0 + ru / rd)) if rd > 0 else 100.0


def context_pack(ctx: Dict[str, Any], now: float) -> Dict[str, Any]:
    m15 = ctx["m15"]
    k = F.last_closed(m15, 900, now)
    a15 = F.atr(m15, 14)
    price = float(m15["c"][k])
    lv = all_levels(ctx, now)
    return {"htf": htf_context(ctx, now), "structure_m15": local_structure(m15, now, 900), "structure_h1": local_structure(ctx["h1"], now, 3600),
            "liquidity": liquidity_map(lv, price, float(a15[k]) if np.isfinite(a15[k]) else 0.0), "fvg_m15": fvg_list(m15, now, 900), "rsi_m15": rsi(m15["c"][:k + 1]),
            "taker_delta_last_bar": _f(2 * m15["tbv"][k] - m15["v"][k]) if np.isfinite(m15["tbv"][k]) else None, "session": session_of(now),
            "session_levels": [x for x in lv if str(x["kind"]).endswith(("_H", "_L"))], "modules": MODULES}


# ------------------------------------------------------------------ теза A
def pullback_break(ctx: Dict[str, Any], direction: str, now: float) -> Optional[Dict[str, Any]]:
    """Повертає тезу з полем state ∈ WATCH/WAIT/READY_CANDIDATE/INVALIDATED або None. Ціни у реальних координатах."""
    sg = 1 if direction == "LONG" else -1
    h1r, m15r = ctx["h1"], ctx["m15"]
    h1, m15 = view(h1r, sg), view(m15r, sg)
    k1 = F.last_closed(h1r, 3600, now)
    k15 = F.last_closed(m15r, 900, now)
    if k1 < 40 or k15 < 100:
        return None
    a1 = F.atr(h1r, 14)
    a15 = F.atr(m15r, 14)
    lo_i = max(0, k1 - 40)
    ih = lo_i + int(np.argmax(h1["h"][lo_i:k1 - 1]))     # вершина імпульсу (у «LONG-координатах»), мін. 2 бари після неї
    if ih > k1 - 2 or not np.isfinite(a1[ih]):
        return None
    st = max(0, ih - 24)
    io = st + int(np.argmin(h1["l"][st:ih + 1]))
    imp = float(h1["h"][ih] - h1["l"][io])
    if io >= ih or imp < IMPULSE_ATR * a1[ih]:
        return None
    a_o = a1[io] if np.isfinite(a1[io]) else a1[ih]
    z_lo = float(h1["l"][io])
    z_hi = z_lo + float(np.clip(h1["h"][io:min(io + 3, ih + 1)].max() - z_lo, 0.5 * a_o, 2.0 * a_o))
    ipb = ih + 1 + int(np.argmin(h1["l"][ih + 1:k1 + 1]))   # дно відкату
    pb_low = float(h1["l"][ipb])
    retr = (float(h1["h"][ih]) - pb_low) / imp
    sid = "O2|" + hashlib.sha256(f"{direction}|{round(float(h1r['t'][io]))}|{round(abs(float(h1['h'][ih])), 8)}|A".encode()).hexdigest()[:12]
    base = {"id": sid, "kind": "PULLBACK_BREAK", "dir": direction, "impulse": {"origin_ts": float(h1r["t"][io]), "top_ts": float(h1r["t"][ih]), "size_atr": float(imp / a1[ih]),
                                                                             "size_pct": float(imp / abs(h1["h"][ih]) * 100.0)},
            "zone": sorted([sg * z_lo, sg * z_hi]), "retrace": float(retr)}
    if pb_low < z_lo - 0.25 * a_o:   # зона зламана → теза мертва
        return dict(base, state="INVALIDATED", reason=f"зона {sg * z_lo:.6g} зламана: дно відкату {sg * pb_low:.6g}")
    if retr < 0.25 or pb_low > z_hi + 0.5 * a_o:   # відкат має дійти до origin-зони (глибокий відкат до ~100% — норма для зони origin)
        return None
    # атаки в зону (H1): епізоди підряд барів з low ≤ z_hi; глибина = z_hi − мін. low епізоду
    eps: List[Tuple[float, int]] = []
    j = ih + 1
    while j <= k1:
        if h1["l"][j] <= z_hi:
            e = j
            lows = []
            while e <= k1 and h1["l"][e] <= z_hi:
                lows.append(float(h1["l"][e]))
                e += 1
            eps.append((z_hi - min(lows), j))
            j = e
        else:
            j += 1
    n_att = len(eps)
    depth_first = eps[0][0] / a_o if eps else None
    depth_last = eps[-1][0] / a_o if eps else None
    weakening = bool(n_att >= 2 and eps[-1][0] <= eps[0][0])
    leg = h1["h"][ih + 1:ipb + 1] - h1["l"][ih + 1:ipb + 1]
    recent = h1["h"][max(ipb, k1 - 3):k1 + 1] - h1["l"][max(ipb, k1 - 3):k1 + 1]
    compression = bool(len(leg) >= 2 and recent.mean() <= 0.75 * leg.mean())
    base.update({"attacks": {"n": n_att, "depth_first_atr": depth_first, "depth_last_atr": depth_last, "weakening": weakening}, "compression": compression,
                 "defended_low": sg * pb_low})
    if n_att == 0:
        return dict(base, state="WATCH", reason="відкат до зони ще не атакував її")
    # локальна структура на M15: перший злам локального lower-high після дна відкату
    t_pb = float(h1r["t"][ipb])
    ipb15 = int(np.searchsorted(m15r["t"], t_pb, side="left"))
    sh15, _ = F.swings(m15, 2)
    sh15 = [s for s in sh15 if s[0] >= ipb15 and s[1] <= k15 and s[2] < float(h1["h"][ih])]
    brk = None
    for jb in range(max(ipb15 + 3, k15 - 12), k15 + 1):
        cand = [s for s in sh15 if s[1] < jb]
        if not cand:
            continue
        lh = cand[-1][2]
        if m15["c"][jb] > lh and all(m15["c"][x] <= lh for x in range(cand[-1][1] + 1, jb)):
            body = float(m15["c"][jb] - m15["o"][jb])
            rng = float(m15["h"][jb] - m15["l"][jb])
            disp = bool(np.isfinite(a15[jb]) and body >= 1.2 * a15[jb] and rng > 0 and m15["c"][jb] >= m15["l"][jb] + 0.65 * rng)
            if disp:
                brk = {"jb": jb, "level": float(lh), "body_atr": float(body / a15[jb])}
                break
    if brk is None:
        return dict(base, state="WAIT", reason="чекаємо злам локального lower-high на M15 з displacement")
    jb, lh = brk["jb"], brk["level"]
    held = k15 > jb and bool(np.all(m15["c"][jb:k15 + 1] > lh))
    base.update({"break": {"ts": float(m15r["t"][jb]), "level": sg * lh, "body_atr": brk["body_atr"], "bars_held": int(k15 - jb)}, "trigger_level": sg * lh, "stale": bool(k15 - jb > 8)})
    if k15 > jb and not np.all(m15["c"][jb:k15 + 1] > lh):
        return dict(base, state="WAIT", reason="пробій не втримано: ціна повернулась під рівень")
    if not held:
        return dict(base, state="WAIT", reason="пробій є; чекаємо утримання ще одного закритого бару")
    # структурна інвалідація: найглибша атака (дно відкату); SL = дно − доказовий буфер
    buf, buf_why = noise_buffer({kk: vv[:k15 + 1] for kk, vv in m15r.items()}, float(a15[k15]))
    sl_v = pb_low - buf
    return dict(base, state="READY_CANDIDATE", reason="пробій локальної структури втримано", sl=sg * sl_v, invalidation={"price": sg * pb_low, "why": "дно відкату (найглибша атака в зону) — нижче ідея імпульс→відкат неправильна",
                "buffer": float(buf), "buffer_basis": buf_why})


# ------------------------------------------------------------------ теза B
def reclaim_thesis(ctx: Dict[str, Any], direction: str, now: float, levels: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """sweep ключового рівня тінню/закриттям і повернення за рівень (M15) + утримання ≥1 бару. Дзеркально для SHORT."""
    sg = 1 if direction == "LONG" else -1
    m15r = ctx["m15"]
    m15 = view(m15r, sg)
    k = F.last_closed(m15r, 900, now)
    a15 = F.atr(m15r, 14)
    if k < 60 or not np.isfinite(a15[k]):
        return None
    side = "low" if sg > 0 else "high"
    px = float(m15r["c"][k])
    lvl = [x for x in levels if x["side"] == side and abs(x["p"] - px) <= 6.0 * float(a15[k])]
    best = None
    for x in sorted(lvl, key=lambda x: -x.get("strength", 1)):
        p = sg * x["p"]
        for r in range(k, max(k - 6, 20), -1):    # reclaim-бар r: sweep на r або ≤2 бари до нього, закриття повернулось за рівень
            s = None
            for s_ in range(r, max(r - 3, 1), -1):
                if m15["l"][s_] < p:
                    s = s_
                    break
            if s is None or not (m15["c"][r] > p):
                continue
            ext = float(m15["l"][s:r + 1].min())
            held = r < k and bool(np.all(m15["c"][r:k + 1] > p))
            best = {"x": x, "p": p, "s": s, "r": r, "ext": ext, "held": held}
            break
        if best:
            break
    if best is None:
        # WATCH: ключовий рівень поруч, sweep ще не було
        near = [x for x in lvl if abs(x["p"] - px) <= 1.5 * float(a15[k]) and (px > x["p"]) == (sg > 0)]
        if near:
            x = min(near, key=lambda z: abs(z["p"] - px))
            sid = "O2|" + hashlib.sha256(f"{direction}|{x['kind']}|{round(x['p'], 8)}|B".encode()).hexdigest()[:12]
            return {"id": sid, "kind": "SWEEP_RECLAIM", "dir": direction, "state": "WATCH", "reason": f"ціна біля {x['kind']} {x['p']:.6g}: чекаємо sweep і повернення", "zone": [x["p"], x["p"]], "level": {"p": x["p"], "kind": x["kind"]}}
        return None
    x = best["x"]
    sid = "O2|" + hashlib.sha256(f"{direction}|{x['kind']}|{round(x['p'], 8)}|B".encode()).hexdigest()[:12]
    base = {"id": sid, "kind": "SWEEP_RECLAIM", "dir": direction, "level": {"p": x["p"], "kind": x["kind"], "strength": int(x.get("strength", 1))}, "zone": [x["p"], x["p"]],
            "sweep": {"ts": float(m15r["t"][best["s"]]), "extreme": sg * best["ext"], "depth_atr": float(abs(best["p"] - best["ext"]) / a15[k])},
            "reclaim": {"ts": float(m15r["t"][best["r"]]), "close": float(m15r["c"][best["r"]])}, "bars_held": int(k - best["r"]), "trigger_level": x["p"], "stale": bool(k - best["r"] > 8)}
    if not best["held"]:
        return dict(base, state="WAIT", reason="sweep і повернення були; чекаємо утримання ще одного закритого бару" if best["r"] == k else "повернення не втримано")
    buf, buf_why = noise_buffer({kk: vv[:k + 1] for kk, vv in m15r.items()}, float(a15[k]))
    return dict(base, state="READY_CANDIDATE", reason="рівень повернуто й утримано", sl=sg * (best["ext"] - buf), invalidation={"price": sg * best["ext"], "why": "екстремум sweep — нижче/вище рівень не повернуто, ідея хибна",
                                                                                                                "buffer": float(buf), "buffer_basis": buf_why})


# ------------------------------------------------------------------ рішення
def decide(thesis: Dict[str, Any], ctx: Dict[str, Any], now: float, risk_usd: float = 10.0) -> Dict[str, Any]:
    """Для READY_CANDIDATE: вхід, структурний SL, цілі, no-chase, межі ризику. Повертає {'state': READY|NO_TRADE|MISSED, ...}. Інші стани проходять без змін."""
    if thesis.get("state") != "READY_CANDIDATE":
        return thesis
    m15 = ctx["m15"]
    k = F.last_closed(m15, 900, now)
    entry = float(m15["c"][k])
    long_ = thesis["dir"] == "LONG"
    sl = float(thesis["sl"])
    risk = (entry - sl) if long_ else (sl - entry)
    if risk <= 0:
        return dict(thesis, state="NO_TRADE", reason="ціна вже за структурною інвалідацією")
    risk_pct = risk / entry * 100.0
    if not (MIN_RISK_PCT <= risk_pct <= MAX_RISK_PCT):
        return dict(thesis, state="NO_TRADE", reason=f"структурний стоп {risk_pct:.2f}% поза допустимим {MIN_RISK_PCT}–{MAX_RISK_PCT}%")
    trig = float(thesis["trigger_level"])
    chase = ((entry - trig) if long_ else (trig - entry)) / risk
    if thesis.get("stale"):
        return dict(thesis, state="MISSED", reason="пробій/reclaim були понад 2 год тому")
    if chase > MAX_CHASE_R:
        return dict(thesis, state="MISSED", reason=f"ціна пішла на {chase:.2f} R від рівня {trig:.6g}: вхід пізній", chase_r=float(chase))
    lv = all_levels(ctx, now)
    tgd = targets_for(thesis["dir"], entry, risk, lv)
    tg = tgd["targets"]
    if not tg:
        near = tgd["obstacles_before_tp1"]
        why = f"; найближча перешкода {near[0]['kind']} {near[0]['p']:.6g} лише {near[0]['r']:.2f} R" if near else ""
        return dict(thesis, state="NO_TRADE", reason=f"немає реальної цілі ≥{MIN_TP1_R} R за напрямом{why}")
    size = risk_usd / (risk / entry) if risk > 0 else 0.0
    return dict(thesis, state="READY", entry=entry, risk=float(risk), risk_pct=float(risk_pct), chase_r=float(chase), targets=tg, obstacles_before_tp1=tgd["obstacles_before_tp1"],
                sizing={"risk_usd": risk_usd, "notional_usd": float(size), "stop_pct": float(risk_pct), "fee_slip_note": "комісія+slippage ≈0.15% кола не входять у стоп"})


def build_full_ctx(m15: Dict[str, np.ndarray], h4: Dict[str, np.ndarray], d1: Dict[str, np.ndarray], w1: Dict[str, np.ndarray], mn: Optional[Dict[str, np.ndarray]] = None) -> Dict[str, Any]:
    """Єдиний контекст символу для мозку: усі ТФ, ATR, режими, рівні (без майбутнього: фільтр known ≤ now застосовується при читанні)."""
    return {"m15": m15, "h1": complete_h1(m15), "h4": h4, "d1": d1, "w1": w1, "mn": mn, "atr15": F.atr(m15, 14), "reg4": F.regime_by_bar(h4), "regd": F.regime_by_bar(d1),
            "levels": F.build_levels(h4, d1, w1)}

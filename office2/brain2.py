"""Office 2.0 BRAIN v2: ОДИН послідовний конвеєр замість двох окремих «тез».

READY більше НЕ виникає зі схеми «sweep → reclaim → 1 бар». Sweep / відбій від origin-зони — лише ПОДІЯ. READY потребує повного ланцюга:

  контекст (HTF + рівень/POI) → ПОДІЯ (sweep ключового рівня або захист origin-зони імпульсу) → ЗСУВ СТРУКТУРИ (MSS/BOS: закриття за останнім локальним swing з displacement)
  → НОГА зміщення → зона входу (OTE 62–79% ноги ∪ OB/FVG, що її перекривають) → КОНТРОЛЬОВАНИЙ РЕТРЕЙС у зону → ТРИГЕР (відбій на M15 у зоні) → READY.

Ціна пішла без ретрейсу → WAIT (з числовою умовою), далі MISSED. Ретрейс зламав структуру → INVALIDATED. Не гонимося за сильною свічкою.
SL: структурна інвалідація (екстремум події) → доказовий люфт (медіана проколів саме цього рівня/символу) → SL; ATR — лише перевірка шуму (стоп < 1 ATR(M15) → NO TRADE, стоп не розширюємо).
TP: наступні реальні структурні/ліквідні рівні; немає значущого простору ≥ 1 R → NO TRADE. Далі fixed-$ розмір і портфельний ризик (engine).
Лише закриті бари ≤ now. Усі ціни в реальних координатах; SHORT = дзеркало (view).
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from office2 import brain as B
from office2 import features as F

VERSION = "o2-brain-2.1"
OTE_LO, OTE_HI, DEEP = 0.62, 0.79, 0.90        # ретрейс ноги: OTE-діапазон і межа глибокого ретрейсу
DISP_BODY_ATR = 1.2                              # displacement: тіло ≥ 1.2 ATR(M15) і закриття в верхніх 35% діапазону
DISP_WINDOW = 3                                  # displacement може бути на барі злому або в наступних DISP_WINDOW-1 барах (закриття лишаються над зламаним swing)
MAX_EVENTS = 10                                  # скільки подій на напрям оцінюємо за цикл (раніше 4 найновіших: просунутий старий сценарій витіснявся новими sweep-ами)
MIN_LEG_ATR = 2.0                                # нога зміщення ≥ 2 ATR(M15): менше — не структура
MISS_R = 3.0                                     # ціна відійшла від зони на > 3 R (від верху зони до інвалідації) без ретрейсу → MISSED
MAX_WAIT_BARS = 32                               # 8 год після зсуву: ретрейс не прийшов → MISSED
SWEEP_LOOKBACK = 64                              # бари M15 (16 год), у яких шукаємо sweep ключового рівня; сценарій живе до зсуву+MAX_WAIT_BARS

# Роль кожного модуля у рішенні (GATE = блокує/дозволяє READY; EVIDENCE = факти в тезі й трасі; CONTEXT = пояснення; RESEARCH = лише збір; NOT_CONNECTED = даних/коду немає)
REGISTRY: Dict[str, Dict[str, str]] = {
    "HTF MN/W1/4D/3D/D1/H4/H1": {"role": "CONTEXT", "note": "тренд/діапазон; ЗА/ПРОТИ у трасі; не блокує (немає доведеного edge)"},
    "BTC/ETH/breadth/relative strength": {"role": "EVIDENCE", "note": "ЗА/ПРОТИ у трасі; не блокує"},
    "ключові рівні PDH/PDL/PWH/PWL/PMH/PML, H4/D1 swing, сесії, EQH/EQL": {"role": "GATE", "note": "POI події (sweep) і цілі; значущі рівні перед TP1 блокують"},
    "Gerchik mirror level + люфт": {"role": "EVIDENCE", "note": "role-flip рівня біля зони; люфт = медіана проколів рівня → буфер SL"},
    "sweep / failed attack": {"role": "GATE", "note": "подія-початок; сама по собі READY не дає"},
    "MSS/BOS + displacement": {"role": "GATE", "note": "обов'язковий зсув структури після події"},
    "OB / FVG / OTE (premium-discount)": {"role": "GATE", "note": "зона входу = OTE ∪ OB/FVG; premium/discount — EVIDENCE"},
    "retrace + тригер M15": {"role": "GATE", "note": "READY лише при ретрейсі в зону + відбій"},
    "структурна інвалідація + люфт → SL": {"role": "GATE", "note": "SL; ATR лише перевіряє шум"},
    "реальні TP + простір ≥ 1R": {"role": "GATE", "note": "TP1/2/3 від рівнів; значущої перешкоди < 1R немає"},
    "fixed-$ розмір + portfolio risk": {"role": "GATE", "note": "engine.portfolio_gate (ємність сценаріїв)"},
    "Wyckoff (spring/upthrust, тест)": {"role": "EVIDENCE", "note": "H1; факт у трасі"},
    "Strong Candle (наша реалізація sc-ours-1)": {"role": "EVIDENCE", "note": "OUR_IMPLEMENTATION (Pine ict_smc_hunter_v9_9); авторську формулу документа Tester не розкрито; Fibonacci OTE/розширення — факти"},
    "Bulkowski (формалізовані фігури)": {"role": "EVIDENCE", "note": "H1; підтверджена фігура за напрямом"},
    "regression channel": {"role": "CONTEXT", "note": "H1; межа каналу в зоні"},
    "volume / taker-delta / CVD": {"role": "EVIDENCE", "note": "M15, з tbv"},
    "OI / funding / L:S / ліквідації": {"role": "RESEARCH", "note": "FLOW-1 FAIL; збираємо для кандидата, не блокує"},
    "M5/M1 тригер": {"role": "EVIDENCE", "note": "мікро-підтвердження на M5, якщо дані є"},
    "DOM / order book": {"role": "NOT_CONNECTED", "note": "немає надійного історичного/живого джерела"},
    "GEX / options": {"role": "NOT_CONNECTED", "note": "немає джерела"},
    "макро-календар": {"role": "NOT_CONNECTED", "note": "office_calendar не підключено до Office2"},
}


def _sid(direction: str, kind: str, e_ts: float) -> str:
    return "O2|" + hashlib.sha256(f"{direction}|{kind}|{int(e_ts)}|v2".encode()).hexdigest()[:12]


# ------------------------------------------------------------------ люфт (доказовий буфер) рівня
def level_luft(m15: Dict[str, np.ndarray], level: Optional[float], atr15: float) -> Tuple[float, str]:
    """Люфт = медіана глибини ПРОКОЛІВ саме цього рівня (бари, що пробили його тінню й закрились назад) у M15-історії; <3 прикладів → медіана проколів символу (brain.noise_buffer)."""
    if level is not None and len(m15["t"]) > 40:
        l, c = m15["l"][-800:], m15["c"][-800:]
        tol = 1.5 * atr15
        depths = [float(level - l[i]) for i in range(len(l)) if l[i] < level <= c[i] and level - l[i] <= tol]
        if len(depths) >= 3:
            return float(np.median(depths)), f"медіана {len(depths)} проколів цього рівня"
    return B.noise_buffer(m15, atr15)


# ------------------------------------------------------------------ події
POI_KINDS = B.MAJOR_OBSTACLE_KINDS + ("ASIA_H", "ASIA_L", "LONDON_H", "LONDON_L", "NEW_YORK_H", "NEW_YORK_L")   # POI sweep: добові/тижневі/місячні, H4/D1 свінги, сесійні; H1SW/M15SW — лише якщо EQ (strength ≥ 2)


def _poi_level(x: Dict[str, Any]) -> bool:
    return str(x.get("kind")) in POI_KINDS or int(x.get("strength", 1)) >= 2


def _sweep_events(m15: Dict[str, np.ndarray], a15: np.ndarray, k: int, levels: List[Dict[str, Any]], sg: int) -> List[Dict[str, Any]]:
    """LONG-координати. Sweep рівня-підтримки: low пробив рівень, закриття в ≤3 барах повернулось вище. Повертає події від найсвіжішої."""
    out = []
    side = "low" if sg > 0 else "high"
    for x in sorted([x for x in levels if x["side"] == side and _poi_level(x)], key=lambda z: -z.get("strength", 1)):
        p = sg * x["p"]
        for s in range(k, max(k - SWEEP_LOOKBACK, 20), -1):
            if m15["l"][s] < p:
                r = next((rr for rr in range(s, min(s + 4, k + 1)) if m15["c"][rr] > p), None)
                if r is None:
                    continue
                seg = m15["l"][s:r + 1]
                e = s + int(np.argmin(seg))
                out.append({"src": "SWEEP", "e": e, "extreme": float(m15["l"][e]), "level": {"p": x["p"], "kind": x["kind"], "strength": int(x.get("strength", 1))}, "level_c": p, "reclaim_idx": r})
                break
    out.sort(key=lambda z: -z["e"])
    return out


def _origin_events(ctx: Dict[str, Any], direction: str, now: float, sg: int, m15: Dict[str, np.ndarray]) -> List[Dict[str, Any]]:
    """Захист origin-зони імпульсу (теза A: імпульс ≥3 ATR(H1) → відкат → атаки в зону): подія = дно найглибшої атаки."""
    th = B.pullback_break(ctx, direction, now)
    if not th or th.get("state") == "INVALIDATED" or "defended_low" not in th:
        return []
    ext = sg * float(th["defended_low"])
    top_ts = float(th["impulse"]["top_ts"])
    i0 = int(np.searchsorted(ctx["m15"]["t"], top_ts))
    lows = m15["l"][i0:]
    if len(lows) == 0:
        return []
    e = i0 + int(np.argmin(np.abs(lows - ext)))
    return [{"src": "ORIGIN", "e": e, "extreme": float(m15["l"][e]), "level": None, "level_c": None, "origin": {"zone": th["zone"], "impulse": th["impulse"], "attacks": th.get("attacks"), "compression": th.get("compression"), "retrace": th.get("retrace")}}]


# ------------------------------------------------------------------ зсув структури
def _ev_txt(ev: Dict[str, Any], sg: int) -> str:
    lv = ev.get("level")
    if lv:
        return f"sweep {lv['kind']} {lv['p']:.6g} (екстремум {sg * ev['extreme']:.6g})"
    return f"захист origin-зони (екстремум {sg * ev['extreme']:.6g})"


def _shift(m15: Dict[str, np.ndarray], a15: np.ndarray, k: int, e: int, swings: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Зсув структури (MSS/BOS): ПЕРШЕ закриття за останнім локальним swing-high, сформованим після події (j = злам), + displacement:
    свічка з тілом ≥ DISP_BODY_ATR·ATR і закриттям у верхніх 35% діапазону на барі зламу або в наступних DISP_WINDOW-1 барах, поки закриття лишаються над зламаним рівнем.
    (Раніше displacement вимагався саме на барі першого закриття над swing: якщо перший злам був звичайною свічкою, цей swing назавжди ставав «неможливим» — суперечність між ґейтами.)"""
    sh = swings if swings is not None else F.swings(m15, 2)[0]
    sh = [s for s in sh if s[0] > e and s[1] <= k]
    for j in range(e + 3, k + 1):
        cand = [s for s in sh if s[1] < j]
        if not cand:
            continue
        lh = cand[-1][2]
        if m15["c"][j] > lh and all(m15["c"][x] <= lh for x in range(cand[-1][1] + 1, j)):
            for d in range(j, min(j + DISP_WINDOW, k + 1)):
                if m15["c"][d] <= lh:
                    break
                body = float(m15["c"][d] - m15["o"][d])
                rng = float(m15["h"][d] - m15["l"][d])
                if np.isfinite(a15[d]) and body >= DISP_BODY_ATR * a15[d] and rng > 0 and m15["c"][d] >= m15["l"][d] + 0.65 * rng:
                    return {"j": j, "jd": d, "level": float(lh), "body_atr": float(body / a15[d])}
    return None


def _entry_zone(m15: Dict[str, np.ndarray], e: int, j: int, k: int, lo: float, hi: float) -> Dict[str, Any]:
    leg = hi - lo
    ote = [hi - OTE_HI * leg, hi - OTE_LO * leg]
    lim = [hi - DEEP * leg, hi - 0.5 * leg]
    parts = ["OTE 62–79%"]
    zl, zh = ote
    # OB: остання ведмежа свічка перед displacement
    ob = None
    for x in range(j - 1, max(e, j - 7), -1):
        if m15["c"][x] < m15["o"][x]:
            ob = [float(m15["c"][x]), float(m15["o"][x])]
            break
    # FVG бичачі в нозі
    fvgs = [[float(m15["h"][x - 2]), float(m15["l"][x])] for x in range(max(e + 2, 2), k + 1) if m15["l"][x] > m15["h"][x - 2]]
    for name, zone in (("OB", ob),) + tuple(("FVG", f) for f in fvgs):
        if zone and zone[1] >= ote[0] and zone[0] <= ote[1]:
            zl, zh = min(zl, zone[0]), max(zh, zone[1])
            if name not in parts:
                parts.append(name)
    zl, zh = max(zl, lim[0]), min(zh, lim[1])
    return {"zone": [float(zl), float(zh)], "ote": [float(ote[0]), float(ote[1])], "ob": ob, "fvg": fvgs[-2:], "composition": parts, "deep_limit": float(lim[0])}


# ------------------------------------------------------------------ оцінка однієї події
def _evaluate(ctx: Dict[str, Any], ev: Dict[str, Any], direction: str, now: float, sg: int, m15: Dict[str, np.ndarray], m15r: Dict[str, np.ndarray],
              a15: np.ndarray, k: int, levels: List[Dict[str, Any]], risk_usd: float, swings: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    e = ev["e"]
    lo = ev["extreme"]
    kind = "SWEEP_SEQ" if ev["src"] == "SWEEP" else "ORIGIN_SEQ"
    base: Dict[str, Any] = {"id": _sid(direction, kind, float(m15r["t"][e])), "kind": kind, "dir": direction, "brain": VERSION, "event": {"src": ev["src"], "ts": float(m15r["t"][e]), "extreme": sg * lo, "level": ev["level"], "origin": ev.get("origin")},
                            "level": ev["level"] or {"p": sg * lo, "kind": "ORIGIN_LOW"}, "invalidation": {"price": sg * lo, "why": "екстремум події (sweep/захист origin): закриття M15 за ним — теза хибна"}}
    base["trigger_level"] = sg * lo
    sh = _shift(m15, a15, k, e, swings)
    seq = [{"step": "подія", "ok": True, "value": f"{ev['src']} {sg * lo:.6g}"}]
    if sh is None:
        hs = [s for s in (swings if swings is not None else F.swings(m15, 2)[0]) if s[0] > e and s[1] <= k]
        need = f"закриття M15 {'вище' if sg > 0 else 'нижче'} {sg * hs[-1][2]:.6g} з displacement (тіло ≥ {DISP_BODY_ATR:g} ATR)" if hs else f"локальний swing-{'high' if sg > 0 else 'low'} після події, потім його злам з displacement"
        return dict(base, state="WAIT", reason=f"WAIT 1/3 · зсув структури: {_ev_txt(ev, sg)}; потрібен зсув структури: {need}; зараз {sg * float(m15['c'][k]):.6g}; скасування — закриття M15 {'нижче' if sg > 0 else 'вище'} {sg * lo:.6g}", sequence=seq + [{"step": "зсув структури (MSS/BOS)", "ok": False}], zone=[sg * lo, sg * lo], entry_zone=None)
    j = sh["j"]
    hi = float(m15["h"][j:k + 1].max())
    leg = hi - lo
    leg_atr = leg / float(a15[k]) if np.isfinite(a15[k]) and a15[k] > 0 else 0.0
    seq.append({"step": "зсув структури (MSS/BOS)", "ok": True, "value": f"закриття {'вище' if sg > 0 else 'нижче'} {sg * sh['level']:.6g}, тіло {sh['body_atr']:.2f} ATR"})
    base["break"] = {"ts": float(m15r["t"][j]), "level": sg * sh["level"], "body_atr": sh["body_atr"], "bars_held": int(k - j), "disp_ts": float(m15r["t"][sh["jd"]])}
    if leg_atr < MIN_LEG_ATR:
        return dict(base, state="WAIT", reason=f"WAIT 1/3 · зсув структури: нога зміщення {leg_atr:.1f} ATR < {MIN_LEG_ATR:g}: структура замала", sequence=seq + [{"step": "нога зміщення", "ok": False, "value": f"{leg_atr:.2f} ATR"}], zone=[sg * lo, sg * lo], entry_zone=None)
    ez = _entry_zone(m15, e, j, k, lo, hi)
    zl, zh = ez["zone"]
    seq.append({"step": "нога зміщення і зона входу", "ok": True, "value": f"нога {sg * lo:.6g}→{sg * hi:.6g} ({leg_atr:.1f} ATR); зона {'+'.join(ez['composition'])}"})
    px, lk, ck, ok_ = float(m15["c"][k]), float(m15["l"][k]), float(m15["c"][k]), float(m15["o"][k])
    zone_real = sorted([sg * zl, sg * zh])
    base["trigger_level"] = zone_real[1] if sg > 0 else zone_real[0]   # межа «не доганяємо»: край зони входу в бік руху (delivery._late_reason міряє пізній вхід від неї, а не від екстремуму події)
    base.update({"zone": zone_real, "entry_zone": zone_real, "leg": {"from": sg * lo, "to": sg * hi, "atr": leg_atr}, "zone_parts": ez["composition"], "impulse": (ev.get("origin") or {}).get("impulse")})
    if np.any(m15["c"][j:k + 1] < lo) or px < ez["deep_limit"]:
        return dict(base, state="INVALIDATED", reason=f"ретрейс зламав структуру: закриття {sg * px:.6g} за інвалідацією/глибоким ретрейсом {sg * min(lo, ez['deep_limit']):.6g}", sequence=seq + [{"step": "ретрейс", "ok": False}])
    bars_since = k - j
    run = (px - zh) / max(zh - lo, 1e-12)
    in_zone = lk <= zh and px >= zl - 1e-12
    if not in_zone:
        if px > zh:
            if run > MISS_R or bars_since > MAX_WAIT_BARS:
                return dict(base, state="MISSED", reason=f"ціна {sg * px:.6g} пішла без ретрейсу в зону {zone_real[0]:.6g}–{zone_real[1]:.6g} ({run:.1f} R від зони, {bars_since} барів): не доганяємо", sequence=seq + [{"step": "ретрейс", "ok": False, "value": "не прийшов"}])
            return dict(base, state="WAIT", reason=f"WAIT 2/3 · ретрейс: ціна {sg * px:.6g}; чекаємо контрольований ретрейс у зону {zone_real[0]:.6g}–{zone_real[1]:.6g} ({'+'.join(ez['composition'])}); MISSED якщо без ретрейсу далі {sg * (zh + MISS_R * (zh - lo)):.6g}; інвалідація — закриття M15 за {sg * lo:.6g}", sequence=seq + [{"step": "ретрейс", "ok": False, "value": "очікуємо"}])
        return dict(base, state="WAIT", reason=f"WAIT 2/3 · ретрейс: ціна {sg * px:.6g} {'нижче' if sg > 0 else 'вище'} зони (глибокий ретрейс); потрібне закриття M15 назад у зону {zone_real[0]:.6g}–{zone_real[1]:.6g}", sequence=seq + [{"step": "ретрейс", "ok": False, "value": "глибше зони"}])
    seq.append({"step": "ретрейс у зону", "ok": True, "value": f"low {sg * lk:.6g} у зоні {zone_real[0]:.6g}–{zone_real[1]:.6g}"})
    mid = (zl + zh) / 2.0
    bullish = ck > ok_ and ck >= mid
    if not bullish:
        return dict(base, state="WAIT", reason=f"WAIT 3/3 · ARMED (зона досягнута, чекаємо тригер M15): ціна в зоні {zone_real[0]:.6g}–{zone_real[1]:.6g}; потрібне {'бичаче' if sg > 0 else 'ведмеже'} закриття M15 {'вище' if sg > 0 else 'нижче'} {sg * mid:.6g}", sequence=seq + [{"step": "тригер M15", "ok": False}])
    seq.append({"step": "тригер M15", "ok": True, "value": f"закриття {sg * ck:.6g} {'≥' if sg > 0 else '≤'} середини зони {sg * mid:.6g}"})
    return _finalize(ctx, base, m15, a15, k, now, lo, px, levels, risk_usd, sg, ev, seq)


def _finalize(ctx, base, m15, a15, k, now, lo, px, levels, risk_usd, sg, ev, seq):
    """READY-кандидат: люфт → SL → ATR-перевірка шуму → цілі від реальних рівнів → простір ≥ 1R → розмір."""
    luft, luft_why = level_luft(m15, ev.get("level_c"), float(a15[k]))
    sl = lo - luft
    risk = px - sl
    entry = px
    inv = {"price": sg * lo, "why": base["invalidation"]["why"], "buffer": float(luft), "buffer_basis": luft_why}
    base["invalidation"] = inv
    base["sl"] = sg * sl
    if risk <= 0:
        return dict(base, state="NO_TRADE", reason="ціна вже за структурною інвалідацією", sequence=seq)
    risk_pct = risk / abs(entry) * 100.0
    if not (B.MIN_RISK_PCT <= risk_pct <= B.MAX_RISK_PCT):
        return dict(base, state="NO_TRADE", reason=f"структурний стоп {risk_pct:.2f}% поза допустимим {B.MIN_RISK_PCT}–{B.MAX_RISK_PCT}%", sequence=seq)
    risk_atr = risk / float(a15[k]) if a15[k] > 0 else None
    if risk_atr is not None and risk_atr < B.MIN_STOP_ATR15:
        return dict(base, state="NO_TRADE", reason=f"структурна інвалідація всередині нормального шуму: стоп {risk_atr:.2f} ATR(M15) < {B.MIN_STOP_ATR15:g}; стоп не розширюємо", quality={"risk_atr15": float(risk_atr), "risk_pct": float(risk_pct)}, sequence=seq)
    # цілі й простір — у реальних координатах (levels реальні)
    entry_r, risk_r = sg * entry, risk
    tgd = B.targets_for("LONG" if sg > 0 else "SHORT", entry_r, risk_r, levels, near_r=0.0)   # жодна перешкода не зникає мовчки через близькість
    tg = tgd["targets"]
    major = [o for o in tgd["obstacles_before_tp1"] if o["kind"] in B.MAJOR_OBSTACLE_KINDS]
    seq_sl = {"step": "SL", "ok": True, "value": f"інвалідація {sg * lo:.6g} − люфт {luft:.6g} ({luft_why}) = {sg * sl:.6g}; {risk_atr:.2f} ATR(M15)" if risk_atr else f"{sg * sl:.6g}"}
    if major:
        o = major[0]
        return dict(base, state="NO_TRADE", reason=f"до першої реальної цілі {o['kind']} {o['p']:.6g} лише {o['r']:.2f} R (< {B.MIN_TP1_R:g}); ціль не пропускаємо, стоп не стискаємо",
                    quality={"risk_atr15": float(risk_atr) if risk_atr else None, "first_target_r": float(o["r"]), "obstacles_before_tp1": tgd["obstacles_before_tp1"]}, sequence=seq + [seq_sl, {"step": "простір до цілі", "ok": False, "value": f"{o['kind']} {o['r']:.2f} R"}])
    if not tg:
        return dict(base, state="NO_TRADE", reason=f"немає реальної цілі ≥{B.MIN_TP1_R} R за напрямом", sequence=seq + [seq_sl, {"step": "цілі", "ok": False}])
    size = risk_usd / (risk / abs(entry))
    seq += [seq_sl, {"step": "цілі від реальних рівнів", "ok": True, "value": ", ".join(f"TP{i + 1} {t['kind']} {t['p']:.6g} ({t['r']:.1f}R)" for i, t in enumerate(tg))}]
    return dict(base, state="READY", reason="повна послідовність: подія → зсув структури → ретрейс у зону → тригер", entry=sg * entry, risk=float(risk), risk_pct=float(risk_pct), chase_r=0.0, targets=tg, obstacles_before_tp1=tgd["obstacles_before_tp1"],
                quality={"risk_atr15": float(risk_atr) if risk_atr else None, "first_target_r": float(tg[0]["r"]), "min_stop_atr15": B.MIN_STOP_ATR15, "min_tp1_r": B.MIN_TP1_R},
                sizing={"risk_usd": risk_usd, "notional_usd": float(size), "stop_pct": float(risk_pct), "fee_slip_note": "комісія+slippage ≈0.15% кола не входять у стоп"}, sequence=seq)


# ------------------------------------------------------------------ ЦІЛІСНА ТЕЗА: карта TF + докази ДО рішення
HTF_LOCATION_KINDS = ("D1SW", "H4SW", "W1SW", "PDH", "PDL", "PWH", "PWL", "PMH", "PML", "D1H", "D1L", "W1H", "W1L")


def _location(th: Dict[str, Any]) -> Tuple[str, str]:
    """Де сталася подія: HTF (старша локація/ліквідність) чи LOCAL (сесійний/M15/H1 рівень)."""
    ev, lv = th.get("event") or {}, th.get("level") or {}
    if ev.get("src") == "ORIGIN":
        return "HTF", "origin-зона імпульсу H1 (≥3 ATR)"
    kind, st = str(lv.get("kind")), int(lv.get("strength", 1))
    p = lv.get("p")
    if kind in HTF_LOCATION_KINDS:
        return "HTF", f"{kind} {p:.6g}"
    if kind == "H1SW" and st >= 2:
        return "HTF", f"EQ-рівень H1SW {p:.6g} (strength {st})"
    return "LOCAL", f"{kind} {p:.6g} — сесійний/локальний рівень (strength {st}); старшого рівня в точці події немає"


def build_map(ctx: Dict[str, Any], now: float, sg: int, entry: float, risk: float, atr15: float, levels: List[Dict[str, Any]], htf: Dict[str, Any]) -> Dict[str, Any]:
    """Карта ринку зверху вниз для знімка: кожен TF (стан/діапазон/свінги/відстань) + живі (не зняті) пули ліквідності над/під ціною з відстанню в $, %, ATR і R."""
    rows: List[Dict[str, Any]] = []
    for tf in htf.get("_order", []):
        r = htf.get(tf) or {}
        if r.get("status") != "USED":
            rows.append({"tf": tf, "status": "UNAVAILABLE"})
            continue
        rows.append({"tf": tf, "status": "USED", "trend": r["trend"], "trend_eff": r["trend_eff"], "broken": r["broken"], "zone": r["zone"], "range_pos": r["range_pos"], "outside_range": r["outside_range"],
                     "range": r["range"], "last_swing_high": r["last_swing_high"], "last_swing_low": r["last_swing_low"], "with_trade": bool(r["trend_eff"] == sg), "against_trade": bool(r["trend_eff"] == -sg), "note": r.get("note")})

    def dist(x: Dict[str, Any]) -> Dict[str, Any]:
        d = abs(float(x["p"]) - entry)
        return {"kind": x["kind"], "p": float(x["p"]), "strength": int(x.get("strength", 1)), "dist_usd": d, "dist_pct": d / entry * 100.0, "dist_atr": (d / atr15 if atr15 > 0 else None), "dist_r": (d / risk if risk > 0 else None)}

    live = B.untouched(levels)
    above = sorted([x for x in live if x["p"] > entry], key=lambda x: x["p"])[:5]
    below = sorted([x for x in live if x["p"] < entry], key=lambda x: -x["p"])[:5]
    return {"tfs": rows, "pools_above": [dist(x) for x in above], "pools_below": [dist(x) for x in below]}


def assess(ctx: Dict[str, Any], th: Dict[str, Any], direction: str, now: float, levels: List[Dict[str, Any]], mc: Optional[Dict[str, Any]], rel: Optional[Dict[str, Any]], hooks: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Кандидат READY читає ВСІ підключені факти ДО рішення (HTF-карта, локація, ліквідність, ринок BTC, докази модулів) і формує цілісну тезу ЗА/ПРОТИ.
    Докази самі нічого не блокують. Єдина умова, що змінює рішення: КОНТРТРЕНД без доказу — старша структура (H4, або D1 коли H4 не за напрямом) проти напряму, подія на ЛОКАЛЬНОМУ
    рівні (не HTF) і немає доказу повернення (H1 вже в напрямі або H1 CHoCH/BOS у напрямі). Тоді READY → WAIT 3/3 з числовою умовою; за доказу або HTF-локації — READY."""
    from office2 import align as AL
    from office2 import evidence as EV

    sg = 1 if direction == "LONG" else -1
    m15r = ctx["m15"]
    k = F.last_closed(m15r, 900, now)
    a15 = float(F.atr(m15r, 14)[k])
    entry, risk = float(th["entry"]), float(th["risk"])
    htf = B.htf_context(ctx, now)
    hooks = hooks or {}
    ev_items = EV.collect(ctx, th, direction, now, levels, flow_fetch=hooks.get("flow"), m5_fetch=hooks.get("m5"))
    al = AL.alignment(direction, mc or {}, rel or {}, htf)
    loc, loc_txt = _location(th)
    eff = {tf: (htf.get(tf) or {}).get("trend_eff") if (htf.get(tf) or {}).get("status") == "USED" else None for tf in ("W1", "D1", "H4", "H1")}
    counter = bool(eff["H4"] == -sg or (eff["D1"] == -sg and eff["H4"] != sg))
    h1_row = htf.get("H1") or {}
    h1_struct = B.local_structure(ctx["h1"], now, 3600)
    proof_h1 = bool(eff["H1"] == sg or (h1_struct.get("event") and h1_struct["event"]["dir"] == ("bullish" if sg > 0 else "bearish")))
    need = h1_row.get("last_swing_high") if sg > 0 else h1_row.get("last_swing_low")
    fors = [i["finding"] for i in ev_items if i["supports"] > 0 and i["status"] == "USED"] + [x["text"] for x in al if x["verdict"].startswith("ЗА")]
    agns = [i["finding"] for i in ev_items if i["supports"] < 0 and i["status"] == "USED"] + [x["text"] for x in al if x["verdict"].startswith("ПРОТИ")]
    tfs_txt = ", ".join(f"{tf} {'вгору' if (v or 0) > 0 else 'вниз' if (v or 0) < 0 else 'діапазон'}" for tf, v in eff.items() if v is not None)
    if counter and loc == "LOCAL" and not proof_h1:
        cls, verdict = "COUNTER_NO_PROOF", "BLOCK"
        broken = [f"{tf} зламано {'вниз' if sg > 0 else 'вгору'} (ціна {(htf[tf]['last_swing_low'] if sg > 0 else htf[tf]['last_swing_high']):.6g})" for tf in ("H4", "D1") if (htf.get(tf) or {}).get("broken") == ("down" if sg > 0 else "up")]
        why = (f"контртренд без доказу: старша структура проти {direction} ({tfs_txt}{'; ' + '; '.join(broken) if broken else ''}); локація — {loc_txt}; "
               f"доказу повернення немає (H1 {'вгору' if eff['H1'] == sg else 'не в напрямі'}"
               + (f", потрібне закриття H1 {'вище' if sg > 0 else 'нижче'} {need:.6g}" if need is not None else "") + ") — або подія від HTF-рівня")
    elif counter and proof_h1 and loc == "LOCAL":
        cls, verdict, why = "COUNTER_WITH_PROOF", "ALLOW", f"контртренд ({tfs_txt}) з доказом повернення: H1 уже в напрямі/CHoCH у напрямі; локація {loc_txt}"
    elif loc == "HTF":
        cls, verdict, why = "HTF_LOCATION", "ALLOW", f"подія на старшій локації: {loc_txt}; стан TF: {tfs_txt}"
    else:
        cls, verdict, why = "WITH_TREND", "ALLOW", f"старша структура не проти {direction} ({tfs_txt}); локація {loc_txt}"
    inputs = [{"name": "старша структура H4/D1 (trend_eff)", "role": "GATE (умовно)", "did_affect_decision": True, "value": {k_: v for k_, v in eff.items()}},
              {"name": "локація події (HTF/LOCAL)", "role": "GATE (умовно)", "did_affect_decision": True, "value": loc_txt},
              {"name": "доказ повернення H1", "role": "GATE (умовно)", "did_affect_decision": counter and loc == "LOCAL", "value": bool(proof_h1)}]
    inputs += [{"name": i["module"], "role": i["role"], "did_affect_decision": False, "status": i["status"], "value": i["finding"]} for i in ev_items]
    inputs += [{"name": f"BTC/ринок: {x['factor']}", "role": "EVIDENCE", "did_affect_decision": False, "value": x["verdict"]} for x in al]
    integral = {"classification": cls, "verdict": verdict, "why": why, "for": fors, "against": agns, "location": {"class": loc, "text": loc_txt}, "counter_trend": counter, "proof_h1": proof_h1, "inputs": inputs}
    out = dict(th, evidence=ev_items, evidence_counts=EV.summary(ev_items), alignment=al, integral=integral, map=build_map(ctx, now, sg, entry, risk, a15, levels, htf))
    if verdict == "BLOCK":
        out.update(state="WAIT", reason=f"WAIT 3/3 · ARMED, але {why}", blocked_ready=True)
    return out


def thesis(ctx: Dict[str, Any], direction: str, now: float, levels: List[Dict[str, Any]], risk_usd: float = 10.0, mc: Optional[Dict[str, Any]] = None,
           rel: Optional[Dict[str, Any]] = None, hooks: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Найрозвиненіша теза напряму (READY > WAIT(зона/ретрейс) > WAIT(зсув) > WATCH) або None."""
    sg = 1 if direction == "LONG" else -1
    m15r = ctx["m15"]
    m15 = B.view(m15r, sg)
    a15 = F.atr(m15r, 14)
    k = F.last_closed(m15r, 900, now)
    if k < 100 or not np.isfinite(a15[k]):
        return None
    events = _sweep_events(m15, a15, k, levels, sg) + _origin_events(ctx, direction, now, sg, m15)
    best, rank = None, -1
    swings_all = F.swings(m15, 2)[0]
    order = {"READY": 5, "NO_TRADE": 4, "WAIT": 3, "MISSED": 2, "INVALIDATED": 1}
    for ev in sorted(events, key=lambda z: -z["e"])[:MAX_EVENTS]:
        th = _evaluate(ctx, ev, direction, now, sg, m15, m15r, a15, k, levels, risk_usd, swings_all)
        if th is None:
            continue
        if th["state"] == "READY":
            th = assess(ctx, th, direction, now, levels, mc, rel, hooks)
        r = order.get(th["state"], 0) * 10 + (1 if th.get("entry_zone") else 0)
        if r > rank:
            best, rank = th, r
    if best is not None:
        return best
    # WATCH: ключовий рівень поруч, події ще не було
    px = float(m15r["c"][k])
    side = "low" if sg > 0 else "high"
    near = [x for x in levels if x["side"] == side and abs(x["p"] - px) <= 1.5 * float(a15[k]) and (px > x["p"]) == (sg > 0)]
    if near:
        x = min(near, key=lambda z: abs(z["p"] - px))
        return {"id": _sid(direction, "WATCH", float(round(x["p"] * 1e6))), "kind": "SWEEP_SEQ", "dir": direction, "brain": VERSION, "state": "WATCH", "reason": f"ціна біля {x['kind']} {x['p']:.6g}: чекаємо sweep, зсув структури і ретрейс у зону", "zone": [x["p"], x["p"]],
                "level": {"p": x["p"], "kind": x["kind"]}, "sequence": []}
    return None

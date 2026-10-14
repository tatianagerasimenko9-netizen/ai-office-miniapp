#!/usr/bin/env python3
"""Розбір одного READY за реальними свічками Binance Futures: чи був вхід передчасним, де стояв старший ТФ, що було після SL, альтернативні входи/стопи.
Альтернативи задано НАПЕРЕД з даних, відомих на момент READY (не підбираються за подальшим рухом): див. ENTRIES/STOPS. Нічого не пише в production.
Вхід: каталог з m1.json, m15.json, h1.json, h4.json (формат /api/v2/candles: {candles:[{time,open,high,low,close}]}) і spec.json.
Використання: python scripts/case_ready_study.py <dir>"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FEE_RT = 0.10      # % кола (taker x2) — як office2.sim.FEE_RT_DEFAULT
SLIP_BPS = 5.0     # кола, б.п. — як у replay
LIMIT_WINDOW_SEC = 8 * 900   # лімітна заявка діє 8 M15-барів — те саме, що T3 у replay (зафіксовано раніше)
HORIZON_SEC = 72 * 3600


def u(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%d.%m %H:%M")


def load(d, name):
    j = json.loads((Path(d) / name).read_text())
    bars = [b for b in j.get("candles", j.get("bars", [])) if b.get("time")]
    bars.sort(key=lambda b: b["time"])
    return [{"t": int(b["time"]), "o": float(b["open"]), "h": float(b["high"]), "l": float(b["low"]), "c": float(b["close"])} for b in bars], j.get("source")


def swings(bars, k=2):
    hi, lo = [], []
    for i in range(k, len(bars) - k):
        if all(bars[i]["h"] > bars[i + j]["h"] and bars[i]["h"] >= bars[i - j]["h"] for j in range(1, k + 1) if True):
            hi.append(bars[i])
        if all(bars[i]["l"] < bars[i + j]["l"] and bars[i]["l"] <= bars[i - j]["l"] for j in range(1, k + 1)):
            lo.append(bars[i])
    return hi, lo


def simulate(m1, t0, direction, limit, sl, tp, window):
    """Вхід: market (limit=None) з першого M1 після t0 за open, або лімітом (торкання) у вікні window сек. SL перед TP в одному барі. Повертає словник."""
    sg = 1 if direction == "LONG" else -1
    fill_i, fill_px = None, None
    for i, b in enumerate(m1):
        if b["t"] < t0:
            continue
        if limit is None:
            fill_i, fill_px = i, b["o"]
            break
        if b["t"] > t0 + window:
            break
        if (sg > 0 and b["l"] <= limit) or (sg < 0 and b["h"] >= limit):
            fill_i, fill_px = i, limit
            break
    if fill_i is None:
        return {"fill": None, "outcome": "NOT_FILLED", "r_net": 0.0}
    risk = abs(fill_px - sl)
    if risk <= 0 or (sg > 0 and not (sl < fill_px < tp)) or (sg < 0 and not (tp < fill_px < sl)):
        return {"fill": fill_px, "outcome": "INVALID", "r_net": None}
    out, tt = "OPEN", None
    mfe = mae = 0.0
    for b in m1[fill_i:]:
        if b["t"] > t0 + HORIZON_SEC:
            break
        hit_sl = b["l"] <= sl if sg > 0 else b["h"] >= sl
        hit_tp = b["h"] >= tp if sg > 0 else b["l"] <= tp
        fav = (b["h"] - fill_px) / risk if sg > 0 else (fill_px - b["l"]) / risk
        adv = (fill_px - b["l"]) / risk if sg > 0 else (b["h"] - fill_px) / risk
        mfe, mae = max(mfe, fav), max(mae, adv)
        if hit_sl:
            out, tt = "SL", b["t"]
            break
        if hit_tp:
            out, tt = "TP1", b["t"]
            break
    rg = -1.0 if out == "SL" else abs(tp - fill_px) / risk if out == "TP1" else 0.0
    cost = (FEE_RT + SLIP_BPS / 100.0) / (risk / fill_px * 100.0)
    return {"fill": fill_px, "outcome": out, "at": tt, "r_gross": round(rg, 2), "r_net": round(rg - cost, 2), "mfe_r": round(mfe, 2), "mae_r": round(mae, 2), "risk_pct": round(risk / fill_px * 100, 2)}


def main():
    d = sys.argv[1]
    sp = json.loads((Path(d) / "spec.json").read_text())
    m1, s1 = load(d, "m1.json")
    m15, _ = load(d, "m15.json")
    h1, _ = load(d, "h1.json")
    h4, _ = load(d, "h4.json")
    t0, dr = sp["ready_ts"], sp["dir"]
    sg = 1 if dr == "LONG" else -1
    print(f"## {sp['symbol']} {dr} · READY {u(t0)} UTC · джерело M1: {s1} · M1 {len(m1)} барів {u(m1[0]['t'])}–{u(m1[-1]['t'])}")
    print(f"План: вхід {sp['entry']} · зона {sp['zone']} · екстремум події {sp['extreme']} · SL {sp['sl']} · TP1 {sp['tp1']} · рівень події {sp['level']}")

    print("\n### 1. Старші ТФ ДО READY (лише закриті бари)")
    for name, bars, sec in (("H4", h4, 14400), ("H1", h1, 3600)):
        past = [b for b in bars if b["t"] + sec <= t0]
        hi, lo = swings(past[-(20 if name == "H4" else 72):], 2)
        below = sorted([b for b in lo if b["l"] < sp["entry"]], key=lambda b: -b["t"])[:4]
        above = sorted([b for b in hi if b["h"] > sp["entry"]], key=lambda b: -b["t"])[:3]
        print(f"{name}: свінг-мінімуми під входом: " + ", ".join(f"{b['l']} ({u(b['t'])}, {abs(b['l']/sp['entry']-1)*100:.2f}% від входу)" for b in below))
        print(f"{name}: свінг-максимуми над входом: " + ", ".join(f"{b['h']} ({u(b['t'])})" for b in above))
    zl, zh = sp["zone"]
    print(f"Зона входу Brain {zl}–{zh} — це OTE імпульсної ноги M15 ({sp['leg'][0]}→{sp['leg'][1]}), а не рівень H1/H4; сторона LONDON_L {sp['level']} (сесійний мінімум, strength 1).")

    print("\n### 2. Шлях після READY (M1)")
    base = simulate(m1, t0, dr, None, sp["sl"], sp["tp1"], 0)
    sub = [b for b in m1 if t0 <= b["t"] <= (base.get("at") or t0 + HORIZON_SEC)]
    lo_b = min(sub, key=lambda b: b["l"]); hi_b = max(sub, key=lambda b: b["h"])
    print(f"Фактичний план: вхід ~{base['fill']} (M1-open після READY) → {base['outcome']} {u(base['at']) if base.get('at') else ''} · MFE {base.get('mfe_r')}R · MAE {base.get('mae_r')}R · net {base['r_net']}R")
    print(f"До результату: мінімум {lo_b['l']} о {u(lo_b['t'])}, максимум {hi_b['h']} о {u(hi_b['t'])}")
    touched_zone_low = next((b for b in sub if b["l"] <= zl), None)
    print(f"Ціна зайшла до нижньої межі зони {zl} ДО результату: " + (f"так, {u(touched_zone_low['t'])}" if touched_zone_low else "ні"))
    touched_lvl = next((b for b in sub if b["l"] <= sp["level"]), None)
    print(f"Ціна торкнулась рівня події {sp['level']} (LONDON_L): " + (f"так, {u(touched_lvl['t'])}" if touched_lvl else "ні"))
    if base["outcome"] == "SL":
        after = [b for b in m1 if b["t"] > base["at"]]
        tp = next((b for b in after if (b["h"] >= sp["tp1"] if sg > 0 else b["l"] <= sp["tp1"])), None)
        low_after = min(after, key=lambda b: b["l"]) if after else None
        print(f"ПІСЛЯ SL: початковий TP1 {sp['tp1']} " + (f"ДОСЯГНУТО {u(tp['t'])} (через {(tp['t']-base['at'])/3600:.1f} год після SL)" if tp else "НЕ досягнуто до кінця даних") + (f" · мінімум після SL {low_after['l']} о {u(low_after['t'])}" if low_after else ""))
        hi_after = max(after, key=lambda b: b["h"]) if after else None
        if hi_after:
            print(f"Максимум після SL {hi_after['h']} о {u(hi_after['t'])}")

    print("\n### 3. Альтернативи (задано наперед із даних READY; TP1 той самий; лімітне вікно 8 M15-барів; net R: комісія 0,10% + прослизання 5 б.п.)")
    pre = [b for b in m15 if b["t"] + 900 <= t0][-15:]
    atr = sum(max(b["h"] - b["l"], abs(b["h"] - p["c"]), abs(b["l"] - p["c"])) for b, p in zip(pre[1:], pre[:-1])) / max(1, len(pre) - 1)
    ext = sp["extreme"]
    mid = (zl + zh) / 2
    entries = [("E0 як видано (ринок після READY)", None), (f"E1 ліміт середина зони {mid:.5f}", mid), (f"E2 ліміт нижня межа зони {zl}", zl), (f"E3 ліміт рівень події {sp['level']}", sp["level"])]
    def stops(entry_px):
        st = abs(entry_px - ext)
        return [("S0 як видано", sp["sl"]), ("S1 за екстремумом без люфту", ext), (f"S2 Герчик-подібний: екстремум − 20% розрахункового стопа", ext - sg * 0.2 * st), (f"S3 екстремум − 1 ATR(M15)={atr:.5f}", ext - sg * atr)]
    rows = []
    for en, lim in entries:
        ref = lim if lim is not None else sp["entry"]
        for sn, slp in stops(ref):
            r = simulate(m1, t0, dr, lim, slp, sp["tp1"], LIMIT_WINDOW_SEC)
            rows.append((en, sn, round(slp, 5), r))
    print(f"{'вхід':<42}{'стоп':<58}{'SL ціна':>9}  {'fill':>8} {'ризик%':>7} {'результат':<10}{'net R':>7}")
    for en, sn, slp, r in rows:
        print(f"{en:<42}{sn:<58}{slp:>9}  {str(r.get('fill')):>8} {str(r.get('risk_pct','')):>7} {r['outcome']:<10}{str(r['r_net']):>7}")
    print("\nПримітка: це ОДИН випадок. Він ілюструє механізм, але не доводить, що будь-яка альтернатива краща: для цього потрібна частота на незалежній вибірці (replay-entry-quality).")


if __name__ == "__main__":
    main()

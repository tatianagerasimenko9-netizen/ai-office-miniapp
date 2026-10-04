#!/usr/bin/env python3
"""Market Brain v2: РАННІ ознаки без вигаданих порогів. BTC, 13 місяців, без look-ahead.
Відмінності від v1: (1) виноси лише значущих рівнів — PDH/PDL, PWH/PWL, PMH/PML і підтверджені 4h-свінги; (2) OI, funding, співвідношення покупців/продавців —
через перцентиль/z-score від ВЛАСНОЇ історії за попередні 30 днів; (3) OI разом із ціною — квадранти (ціна↑/↓/стоїть × OI↑/↓); (4) ETH проти BTC і ширина — окремо;
(5) момент ПОЧАТКУ руху (старт ноги), а не лише досягнення порога; (6) для кожної ознаки: скільки подій, ПРАВИЛЬНИХ, ХИБНИХ, медіана випередження початку руху;
(7) комбінації 2–3 ознак відбираються ЛИШЕ на навчальній частині, потім показується перевірочна.
Рух: за 60 хв ціна пройшла ≥ 2σ·√60 (σ — 1m за попередні 24 год) в один бік і більше, ніж у протилежний. Початок руху — мінімум (максимум) ціни до моменту першого проходу порога.
Дані: data.binance.vision (1m BTC/ETH, 5m кошика, metrics: OI і співвідношення рахунків кроком 5 хв, funding). Ознаки доступні із запізненням 5 хв."""
import itertools
import math
import statistics
import sys
import time
from datetime import datetime, timezone

import numpy as np

import brain_study as S1

K = 2.0
H = 60
STEP = 15
WIN = 2880          # 30 днів кроків по 15 хв
LEVEL_NEAR = 1.5    # % — значущі рівні далі не розглядаємо
SWEEP_MIN = 0.03    # % — виніс за рівень не менше
SWEEP_WIN = 12      # свічок 5m


def day_key(t):
    return int(t // 86400)


def week_key(t):
    return int((t // 86400 + 3) // 7)    # тиждень починається в понеділок (1970-01-01 — четвер)


def month_key(t):
    d = datetime.fromtimestamp(t, tz=timezone.utc)
    return d.year * 12 + d.month - 1


def main():
    t0 = time.time()
    btc = S1.klines("BTCUSDT", "1m", S1.MONTHS)
    eth = S1.klines("ETHUSDT", "1m", S1.MONTHS)
    first = datetime.fromtimestamp(btc[0, 0], tz=timezone.utc)
    last = datetime.fromtimestamp(btc[-1, 0], tz=timezone.utc)
    from datetime import timedelta
    days = [(first + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((last - first).days + 1)]
    met = S1.metrics("BTCUSDT", days)
    fund = S1.funding("BTCUSDT", S1.MONTHS)
    bask = {}
    for s in ("SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC", "TRX"):
        a = S1.klines(s + "USDT", "5m", S1.MONTHS)
        if len(a):
            bask[s] = {int(r[0]): r[4] for r in a}
    bask["ETH"] = {int(r[0]): r[4] for r in S1.agg(eth, 300)}
    print(f"[data] BTC {len(btc)}, ETH {len(eth)}, metrics {len(met)}, funding {len(fund)}, кошик {len(bask)}; {time.time() - t0:.0f} с", flush=True)

    ts1, hi1, lo1, cl1 = btc[:, 0], btc[:, 2], btc[:, 3], btc[:, 4]
    r1 = np.r_[0.0, np.diff(cl1) / cl1[:-1]]
    cs, cs2 = np.cumsum(r1), np.cumsum(r1 ** 2)
    eth_c = {int(r[0]): r[4] for r in eth}
    # денні / тижневі / місячні екстремуми з 1m
    day_hi, day_lo, wk_hi, wk_lo, mo_hi, mo_lo = {}, {}, {}, {}, {}, {}
    for t, h, l_ in zip(ts1, hi1, lo1):
        for dct_h, dct_l, k in ((day_hi, day_lo, day_key(t)), (wk_hi, wk_lo, week_key(t)), (mo_hi, mo_lo, month_key(t))):
            dct_h[k] = max(dct_h.get(k, -1e18), h)
            dct_l[k] = min(dct_l.get(k, 1e18), l_)
    # 4h-свічки для підтверджених свінгів
    c4 = S1.agg(btc, 4 * 3600)
    sw4_hi = [(c4[j, 0] + 3 * 4 * 3600, c4[j, 2]) for j in range(2, len(c4) - 2) if all(c4[j, 2] > c4[j + d, 2] for d in (-2, -1, 1, 2))]   # доступний після 2 наступних свічок
    sw4_lo = [(c4[j, 0] + 3 * 4 * 3600, c4[j, 3]) for j in range(2, len(c4) - 2) if all(c4[j, 3] < c4[j + d, 3] for d in (-2, -1, 1, 2))]
    oi_ts = np.array([m[0] + 300 for m in met])
    oi_v = np.array([m[1] for m in met])
    ls_v = np.array([m[2] for m in met])
    f_ts = np.array([f[0] for f in fund])
    f_v = np.array([f[1] for f in fund])

    grid = list(range(1440 * 8, len(btc) - H - 2, STEP))
    G = len(grid)
    P30 = np.full(G, np.nan)
    SG30 = np.full(G, np.nan)
    OI30 = np.full(G, np.nan)
    LS = np.full(G, np.nan)
    FU = np.full(G, np.nan)
    ETHREL = np.full(G, np.nan)
    BR_UP = np.full(G, np.nan)
    BR_DN = np.full(G, np.nan)
    SW_UP = np.zeros(G, bool)
    SW_DN = np.zeros(G, bool)
    NEAR_WH = np.zeros(G, bool)
    NEAR_WL = np.zeros(G, bool)
    for g, i in enumerate(grid):
        now = ts1[i] + 60
        P30[g] = cl1[i] / cl1[i - 30] - 1
        n = 1440
        m = (cs[i] - cs[i - n]) / n
        v = (cs2[i] - cs2[i - n]) / n - m * m
        SG30[g] = math.sqrt(max(v, 0)) * math.sqrt(30)
        k = np.searchsorted(oi_ts, now, side="right")
        if k > 7:
            base = np.searchsorted(oi_ts, now - 1800, side="right") - 1
            if base >= 0 and oi_v[base]:
                OI30[g] = oi_v[k - 1] / oi_v[base] - 1
            LS[g] = ls_v[k - 1]
        kf = np.searchsorted(f_ts, now, side="right")
        if kf:
            FU[g] = f_v[kf - 1]
        e_now, e_60 = eth_c.get(int(ts1[i])), eth_c.get(int(ts1[i - 60]))
        if e_now and e_60:
            ETHREL[g] = ((e_now / e_60 - 1) - (cl1[i] / cl1[i - 60] - 1))
        sl = int(now // 300) * 300 - 300
        up = dn = nn = 0
        for s, mp in bask.items():
            a_, b_ = mp.get(sl), mp.get(sl - 3600)
            if a_ and b_:
                nn += 1
                up += a_ > b_
                dn += a_ < b_
        if nn >= 8:
            BR_UP[g], BR_DN[g] = up / nn, dn / nn
        # значущі рівні
        px = cl1[i]
        dk, wk, mk = day_key(now), week_key(now), month_key(now)
        lv = []
        for dct_h, dct_l, key in ((day_hi, day_lo, dk - 1), (wk_hi, wk_lo, wk - 1), (mo_hi, mo_lo, mk - 1)):
            if key in dct_h:
                lv += [dct_h[key], dct_l[key]]
        lv += [x for tt, x in sw4_hi if now - 30 * 86400 <= tt <= now] + [x for tt, x in sw4_lo if now - 30 * 86400 <= tt <= now]
        w5 = slice(max(0, i - 5 * SWEEP_WIN), i + 1)
        mx, mn = hi1[w5].max(), lo1[w5].min()
        for L in lv:
            if abs(L / px - 1) * 100 > LEVEL_NEAR + 1.0:
                continue
            if mx >= L * (1 + SWEEP_MIN / 100) and px < L and cl1[i - 5 * SWEEP_WIN] < L:
                SW_UP[g] = True
            if mn <= L * (1 - SWEEP_MIN / 100) and px > L and cl1[i - 5 * SWEEP_WIN] > L:
                SW_DN[g] = True
        wh, wl = wk_hi.get(wk), wk_lo.get(wk)
        if wh and 0 <= (wh / px - 1) * 100 <= 0.5:
            NEAR_WH[g] = True
        if wl and 0 <= (1 - wl / px) * 100 <= 0.5:
            NEAR_WL[g] = True
    print(f"[features] сітка {G}, {time.time() - t0:.0f} с", flush=True)

    def roll_pct(x):
        out = np.full(G, np.nan)
        for g in range(WIN, G):
            w = x[g - WIN:g]
            w = w[~np.isnan(w)]
            if len(w) > 500 and not np.isnan(x[g]):
                out[g] = (w < x[g]).mean()
        return out

    def roll_z(x):
        out = np.full(G, np.nan)
        for g in range(WIN, G):
            w = x[g - WIN:g]
            w = w[~np.isnan(w)]
            if len(w) > 500 and not np.isnan(x[g]):
                sd = w.std()
                out[g] = (x[g] - w.mean()) / sd if sd > 0 else np.nan
        return out

    zOI, pFU, pLS, zETH = roll_z(OI30), roll_pct(FU), roll_pct(LS), roll_z(ETHREL)
    pmove = P30 / SG30      # рух ціни за 30 хв у σ
    feats = {}
    mv_up, mv_dn, flat = pmove >= 0.5, pmove <= -0.5, np.abs(pmove) < 0.5
    oi_up, oi_dn = zOI >= 1, zOI <= -1
    feats["виніс угору над значущим рівнем"] = SW_UP
    feats["виніс униз під значущим рівнем"] = SW_DN
    feats["ціна↑ / OI↑"] = mv_up & oi_up
    feats["ціна↑ / OI↓"] = mv_up & oi_dn
    feats["ціна↓ / OI↑"] = mv_dn & oi_up
    feats["ціна↓ / OI↓"] = mv_dn & oi_dn
    feats["ціна стоїть / OI↑"] = flat & oi_up
    feats["ціна стоїть / OI↓"] = flat & oi_dn
    feats["funding у верхніх 10%"] = pFU >= 0.9
    feats["funding у нижніх 10%"] = pFU <= 0.1
    feats["покупців/продавців у верхніх 10%"] = pLS >= 0.9
    feats["покупців/продавців у нижніх 10%"] = pLS <= 0.1
    feats["ETH слабший за BTC (z≤−1)"] = zETH <= -1
    feats["ETH сильніший за BTC (z≥1)"] = zETH >= 1
    feats["ширина: ≥65% монет вниз"] = BR_DN >= 0.65
    feats["ширина: ≥65% монет вгору"] = BR_UP >= 0.65
    feats["біля тижневого максимуму (≤0,5%)"] = NEAR_WH
    feats["біля тижневого мінімуму (≤0,5%)"] = NEAR_WL
    names = list(feats)
    Fm = np.array([feats[n] for n in names]).T.astype(bool)   # G × F

    # мітки руху (60 хв), початок руху
    lab = np.zeros(G, int)      # +1 вгору, −1 вниз
    onset = np.full(G, -1)      # індекс 1m початку руху
    for g, i in enumerate(grid):
        sg = SG30[g] * math.sqrt(2)     # σ за 60 хв
        px = cl1[i]
        hs = hi1[i + 1:i + 1 + H] / px - 1
        ls_ = 1 - lo1[i + 1:i + 1 + H] / px
        hi_, lo_ = hs.max(), ls_.max()
        thr = K * sg
        if hi_ >= thr and hi_ > lo_:
            lab[g] = 1
            hit = int(np.argmax(hs >= thr))
            onset[g] = i + 1 + int(np.argmin(lo1[i + 1:i + 2 + hit]))
        elif lo_ >= thr and lo_ > hi_:
            lab[g] = -1
            hit = int(np.argmax(ls_ >= thr))
            onset[g] = i + 1 + int(np.argmax(hi1[i + 1:i + 2 + hit]))
    valid = ~np.isnan(zOI) & ~np.isnan(pFU) & ~np.isnan(zETH) & ~np.isnan(BR_UP)
    idx = np.flatnonzero(valid)
    cut = idx[int(len(idx) * 0.67)]
    tr = idx[idx < cut]
    te = idx[idx >= cut]
    print(f"[study] зразків {len(idx)} (навчальних {len(tr)}, перевірочних {len(te)}); подій вгору {int((lab[idx] == 1).sum())}, вниз {int((lab[idx] == -1).sum())}", flush=True)

    def rates(mask, sel):
        n = int(mask[sel].sum())
        if n == 0:
            return None
        l_ = lab[sel][mask[sel]]
        base_dn, base_up = (lab[sel] == -1).mean(), (lab[sel] == 1).mean()
        return {"n": n, "dn": (l_ == -1).mean(), "up": (l_ == 1).mean(), "base_dn": base_dn, "base_up": base_up}

    def fmt(r, side):
        if not r or r["n"] < 30:
            return "—"
        p, b, w = (r["dn"], r["base_dn"], r["up"]) if side == "down" else (r["up"], r["base_up"], r["dn"])
        return f"n={r['n']:>5} вірно {p * 100:4.1f}% (база {b * 100:4.1f}%) lift {p / b:4.2f} хибно {w * 100:4.1f}%"

    print("\n=== ОЗНАКИ ПО ОДНІЙ: після неї за 60 хв сильний рух вниз / вгору (навчальна | перевірочна) ===")
    for j, nm in enumerate(names):
        m_ = Fm[:, j]
        mask = np.zeros(G, bool)
        mask[:] = False
        mask[idx] = m_[idx]
        a, b = rates(mask, tr), rates(mask, te)
        print(f"{nm:<38}ВНИЗ  {fmt(a, 'down')} | {fmt(b, 'down')}")
        print(f"{'':<38}ВГОРУ {fmt(a, 'up')} | {fmt(b, 'up')}")

    # випередження початку руху
    print("\n=== ВИПЕРЕДЖЕННЯ: події (початки сильних рухів) і коли ознака вже була активна ===")
    for side, sgn, lbl in (("ВНИЗ", -1, "down"), ("ВГОРУ", 1, "up")):
        evs = {}
        for g in idx:
            if lab[g] == sgn and onset[g] > 0:
                key = (int(onset[g]) // (15 * 60))
                evs.setdefault(key, onset[g])
        onsets = sorted(evs.values())
        print(f"\n-- рухи {side}: {len(onsets)} подій (унікальних початків) --")
        gt = np.array(grid)
        for j, nm in enumerate(names):
            leads, hit = [], 0
            for O in onsets:
                gi = int(np.searchsorted(gt, O, side="right")) - 1
                if gi < 12:
                    continue
                if not Fm[gi, j]:
                    continue
                hit += 1
                s = gi
                while s - 1 >= 0 and Fm[s - 1, j] and (gi - (s - 1)) <= 12:   
                    s -= 1
                leads.append(int(O - gt[s]))
            base_rate = float(Fm[idx, j].mean())
            rec = hit / max(1, len(onsets))
            med = statistics.median(leads) if leads else None
            print(f"{nm:<38} подій з ознакою {hit:>4}/{len(onsets):<4} recall {rec * 100:4.1f}% (ознака активна у {base_rate * 100:4.1f}% часу) lift {rec / base_rate if base_rate else float('nan'):4.2f} медіана випередження {('%.0f хв' % med) if med is not None else '—'}")

    # комбінації 2–3 ознак: відбір ТІЛЬКИ на навчальній частині
    print("\n=== КОМБІНАЦІЇ 2–3 ознак: відбір лише за навчальною частиною (n≥150), далі перевірочна ===")
    F = len(names)
    for side, lbl in (("ВНИЗ", "down"), ("ВГОРУ", "up")):
        cands = []
        for r_ in (2, 3):
            for comb in itertools.combinations(range(F), r_):
                mask = np.zeros(G, bool)
                mask[idx] = Fm[idx][:, list(comb)].all(axis=1)
                a = rates(mask, tr)
                if a and a["n"] >= 150:
                    p, b = (a["dn"], a["base_dn"]) if lbl == "down" else (a["up"], a["base_up"])
                    cands.append((p / b, comb, mask))
        cands.sort(key=lambda x: -x[0])
        print(f"\n-- {side}: перевірено {len(cands)} комбінацій; найкращі 8 за навчальною --")
        for lf, comb, mask in cands[:8]:
            print(f"lift(навч) {lf:4.2f}: " + " + ".join(names[c] for c in comb))
            print(f"      НАВЧ {fmt(rates(mask, tr), lbl)}\n      ПЕРЕВІР {fmt(rates(mask, te), lbl)}")
    print("\nЗауваження: комбінацій багато (множинні перевірки) — лише перевірочна частина чесна. Не більше ніж напрям для гіпотези.")


if __name__ == "__main__":
    main()

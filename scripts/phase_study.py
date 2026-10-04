#!/usr/bin/env python3
"""Фаза руху: що відбувається ПІСЛЯ входу залежно від того, наскільки монета вже пройшла в бік угоди (рано / формується / зона / пішов / пізно).
Незалежна від Office вибірка: ~60 ліквідних ф'ючерсних монет × 6 місяців, вхід кожну годину в обидва боки. Без look-ahead: ознаки лише з минулих свічок 5m.
Результат угоди нейтральний (SL = TP = 1σ за годину, горизонт 4 год, перший дотик; однакова свічка — виключена): якби руху не було залежності від фази, виграш = 50%.
a = рух монети за 60 (30) хв У БІК угоди в одиницях σ (σ — 5m-зміни за попередні 24 год × √(хв/5)). a<0 — вхід проти імпульсу; велике a — наздоганяємо.
Також a_rel — власний рух монети понад BTC. Навчальна частина — перші 3 місяці, перевірочна — останні 3. Лише читання (data.binance.vision)."""
import io
import json
import math
import sys
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor

import numpy as np

B = "https://data.binance.vision/data/futures/um/monthly/klines/"
MONTHS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
COINS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "BCH", "TRX", "NEAR", "APT", "ARB", "OP", "SUI", "INJ", "ATOM", "AAVE", "UNI", "FIL",
         "ETC", "HBAR", "ICP", "TIA", "SEI", "WLD", "1000PEPE", "1000SHIB", "FET", "RENDER", "ENA", "ONDO", "JUP", "PENDLE", "STX", "ALGO", "XLM", "VET", "GALA", "SAND", "MANA",
         "AXS", "CRV", "LDO", "MKR", "SNX", "COMP", "DYDX", "EGLD", "THETA", "JASMY", "ZEC", "DASH", "XMR", "TAO", "HYPE", "VVV", "SYRUP", "TRUMP", "WIF", "BONK"]
H = 48          # горизонт, свічок 5m (4 год)
STEP = 12       # вхід раз на годину


def fetch(sym, ym):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(f"{B}{sym}USDT/5m/{sym}USDT-5m-{ym}.zip", headers={"User-Agent": "x"}), timeout=90).read()
        z = zipfile.ZipFile(io.BytesIO(raw))
        t = z.read(z.namelist()[0]).decode()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ln in t.splitlines():
        p = ln.split(",")
        if p and p[0].isdigit():
            out.append((int(p[0]) // 1000, float(p[2]), float(p[3]), float(p[4])))
    return out


def load(sym):
    with ThreadPoolExecutor(3) as ex:
        parts = list(ex.map(lambda m: fetch(sym, m), MONTHS))
    rows = sorted({r[0]: r for p in parts for r in p}.values())
    return np.array(rows, dtype=float) if len(rows) > 5000 else None


def main():
    with ThreadPoolExecutor(8) as ex:
        data = dict(zip(COINS, ex.map(load, COINS)))
    data = {k: v for k, v in data.items() if v is not None}
    print(f"[data] монет із даними: {len(data)} з {len(COINS)}: {sorted(data)[:80]}", flush=True)
    btc = data["BTC"]
    bmap = {int(t): c for t, _, _, c in btc}
    rows = []   # (coin, t, a60, a30, arel30, outcome_up_first: 1 up / -1 down / 0 none/tie)
    for coin, a in data.items():
        t, hi, lo, cl = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
        r5 = np.r_[0.0, np.diff(cl) / cl[:-1]]
        cs, cs2 = np.cumsum(r5), np.cumsum(r5 ** 2)
        for i in range(300, len(a) - H - 1, STEP):
            W = 288
            m = (cs[i] - cs[i - W]) / W
            v = (cs2[i] - cs2[i - W]) / W - m * m
            s5 = math.sqrt(max(v, 0.0))
            if s5 <= 0:
                continue
            ret60 = cl[i] / cl[i - 12] - 1
            ret30 = cl[i] / cl[i - 6] - 1
            s60, s30 = s5 * math.sqrt(12), s5 * math.sqrt(6)
            b_now, b_30 = bmap.get(int(t[i])), bmap.get(int(t[i - 6]))
            brel = None
            if b_now and b_30:
                brel = (ret30 - (b_now / b_30 - 1)) / s30
            D = s60
            up, dn = cl[i] * (1 + D), cl[i] * (1 - D)
            hh = hi[i + 1:i + 1 + H] >= up
            ll = lo[i + 1:i + 1 + H] <= dn
            iu = int(np.argmax(hh)) if hh.any() else 10 ** 9
            idn = int(np.argmax(ll)) if ll.any() else 10 ** 9
            out = 0 if (iu == idn) else (1 if iu < idn else -1)   # ніч: нічия (однакова свічка) або жодного дотику
            rows.append((coin, float(t[i]), ret60 / s60, ret30 / s30, brel, out))
    print(f"[study] зразків: {len(rows)}", flush=True)
    t_all = sorted(r[1] for r in rows)
    cut = t_all[len(t_all) // 2]
    train = [r for r in rows if r[1] < cut]
    test = [r for r in rows if r[1] >= cut]

    def wil(k, n, z=1.96):
        if n == 0:
            return (0, 0)
        p = k / n
        d = 1 + z * z / n
        c = p + z * z / (2 * n)
        mm = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
        return ((c - mm) / d, (c + mm) / d)

    def table(title, idx, side, edges, subset):
        print(f"\n=== {title} — угода {side}: a = рух У БІК угоди ===")
        print(f"{'a (σ)':<14}{'n':>8}{'виграш':>9}{'програш':>9}{'без дотику/нічия':>18}   виграш CI95 | НАВЧ виграш | ПЕРЕВІР виграш")
        sgn = 1.0 if side == "LONG" else -1.0
        for lo_, hi_ in zip(edges[:-1], edges[1:]):
            def pick(rs):
                return [r for r in rs if r[idx] is not None and lo_ <= sgn * r[idx] < hi_]
            g = pick(subset)
            if not g:
                continue
            w = sum(1 for r in g if r[5] == (1 if side == "LONG" else -1))
            l_ = sum(1 for r in g if r[5] == (-1 if side == "LONG" else 1))
            n = len(g)
            decided = w + l_
            ci = wil(w, decided)

            def wr(rs):
                p_ = pick(rs)
                ww = sum(1 for r in p_ if r[5] == (1 if side == "LONG" else -1))
                ll_ = sum(1 for r in p_ if r[5] == (-1 if side == "LONG" else 1))
                return f"{ww / (ww + ll_) * 100:5.1f}% (n={ww + ll_})" if ww + ll_ >= 30 else "  —"
            print(f"{lo_:>5.1f}…{hi_:<7.1f}{n:>8}{(w / decided * 100 if decided else float('nan')):>8.1f}%{(l_ / decided * 100 if decided else float('nan')):>8.1f}%{(n - decided) / n * 100:>17.1f}%   [{ci[0] * 100:.1f}–{ci[1] * 100:.1f}] | {wr(train)} | {wr(test)}")

    INF = 1e9
    E = [-INF, -3, -2, -1.5, -1, -0.5, 0, 0.5, 1, 1.5, 2, 3, INF]
    for side in ("SHORT", "LONG"):
        table("Рух за 60 хв", 2, side, E, rows)
        table("Рух за 30 хв", 3, side, E, rows)
        table("Власний рух понад BTC за 30 хв", 4, side, E, rows)
    print("\nВиграш = перший дотик +1σ(год) у бік угоди до −1σ проти неї за 4 год. 50% — «випадкове блукання»; відхилення = залежність від фази.")


if __name__ == "__main__":
    main()

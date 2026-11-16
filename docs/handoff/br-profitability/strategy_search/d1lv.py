"""Денні рівні (мислення Герчика: рівень з D1, скільки разів ціна підходила, чи був пробій) — спільний код. ГІПОТЕЗА щодо параметрів N (фрактал) і TOL (допуск підходу в ATR D1); перевіряються на історії, а не задаються як правила."""
import numpy as np, pandas as pd

def build(a, per=86400):
    day = (a["open_time"] // per).astype(int); u, st = np.unique(day, return_index=True); en = np.r_[st[1:], len(day)]
    hi = np.array([a["high"][x:y].max() for x, y in zip(st, en)]); lo = np.array([a["low"][x:y].min() for x, y in zip(st, en)]); cl = np.array([a["close"][y - 1] for y in en])
    atr = pd.Series(hi - lo).rolling(14).mean().shift(1).to_numpy()
    return dict(u=u, hi=hi, lo=lo, cl=cl, atr=atr)

def levels(D, N=3, tol=0.25, life=150):  # life: у барах ТФ
    """Фрактальні рівні + історія підходів. Підхід = день, коли ціна дійшла на tol*ATR до рівня (епізод починається, якщо вчора підходу не було). Пробій = закриття дня за рівнем більш ніж на tol*ATR."""
    hi, lo, cl, atr = D["hi"], D["lo"], D["cl"], D["atr"]; n = len(hi); out = []
    for i in range(N, n - N):
        for t, p, ok in (("H", hi[i], hi[i] > hi[i - N:i].max() and hi[i] > hi[i + 1:i + N + 1].max()), ("L", lo[i], lo[i] < lo[i - N:i].min() and lo[i] < lo[i + 1:i + N + 1].min())):
            if not ok: continue
            conf = i + N; eps = []; broke = None; prev = False
            for d in range(conf + 1, min(n, conf + 1 + life)):
                a_ = atr[d]
                if not a_ == a_: prev = False; continue
                brk = (cl[d] > p + tol * a_) if t == "H" else (cl[d] < p - tol * a_)
                if brk: broke = d; break
                app = (hi[d] >= p - tol * a_) if t == "H" else (lo[d] <= p + tol * a_)
                if app and not prev: eps.append(d)
                prev = app
            out.append(dict(i=i, conf=conf, p=float(p), t=t, eps=eps, broke=broke))
    return out

LIFE = {86400: 150, 14400: 300, 3600: 600}

def state(L, di, life=150):
    """Стан рівня на початок дня di: (живий?, кількість підходів до di)."""
    if L["conf"] >= di or di - L["conf"] > life: return None
    if L["broke"] is not None and L["broke"] < di: return None
    return sum(1 for e in L["eps"] if e < di)

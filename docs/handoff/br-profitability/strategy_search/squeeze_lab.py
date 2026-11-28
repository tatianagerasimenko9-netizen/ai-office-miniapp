"""READ-ONLY. «ЦІНА ТРИМАЄТЬСЯ БІЛЯ РІВНЯ І НЕ ВІДКОЧУЄ — ЗНАЧИТЬ ПРОБ'Є» (підтискання до рівня) на історії (28.11.2026, правило назвала власниця).
Джерело ідеї: власниця («я знаю, що працює…»); у її матеріалах окремого опису з числами немає → самі числа нижче — ГІПОТЕЗА (наша автоматизація), записані ДО запуску.
Бари H1, 42 монети (пошук, група A) + 30 інших (контроль, група B), 2020–2026. Періоди: P1 ≤2022, P2 2023–2024, P3 2025–2026. Ризик $10, комісія 0,10%.
РІВЕНЬ   : найвищий максимум за попередні 240 годин (10 діб) — опір. Для підтримки все дзеркально (найнижчий мінімум; угода SHORT).
ПІДТИСКАННЯ: бар «тримається біля рівня», якщо він НЕ оновив рівень і закрився не далі ніж 1,5 ATR(14) від нього. hug = скільки таких барів поспіль під тим самим рівнем.
ТЕСТ 1 (чи правда, що «не відкочує → проб'є»): момент, коли hug уперше дорівнює N (N = 1 — «щойно підійшла», 6, 12, 24, 48 годин). Дивимось 48 годин уперед:
          що сталося раніше — закриття ЗА рівнем (пробій) чи закриття на 3 ATR ДАЛІ від рівня (відкат). Якщо правило працює, частка пробоїв має рости з N.
ТЕСТ 2 (чи можна заробити): вхід на закритті бару пробою (закриття за рівнем; рівню не менше 12 годин; не частіше одного пробою на 24 години на монету).
          Стоп — за протилежним краєм останніх max(hug, 3) барів мінус 0,1 ATR (за «полицею»); пропуск, якщо стоп < 0,3% або > 5%. Цілі 2R і 3R; до 72 годин; у спірному барі стоп першим.
          Корзини за hug перед пробоєм: «з ходу» (0–2), 3–5, 6–11, 12–23, 24+ годин. Правило власниці = чим довше підтискання, тим кращий пробій.
ТЕСТ 3 (вхід ЗАЗДАЛЕГІДЬ, ще до пробою): коли hug = 12 — вхід у бік рівня на закритті, стоп за краєм полиці, ціль 2R/3R, до 72 годин.
«ПРАЦЮЄ» = плюс у всіх 6 клітинках (2 групи × 3 періоди) при n ≥ 50 у кожній. Інакше — НЕ ПІДТВЕРДЖЕНО.
Використання: squeeze_lab.py CANDLES_DIR SEARCH CONTROL"""
import os, sys
import numpy as np, pandas as pd
CD, GA, GB = sys.argv[1], sys.argv[2].split(","), sys.argv[3].split(",")
LB = 240; NEAR = 1.5; FEE = 0.001; HOR = 72; NS = (1, 6, 12, 24, 48)
T1 = []; T2 = []; T3 = []


def trade(H, L, C, i, e, sl, k):
    risk = e - sl
    for j in range(i + 1, min(len(C), i + HOR + 1)):
        if L[j] <= sl: return -1.0
        if H[j] >= e + k * risk: return float(k)
    return (C[min(len(C) - 1, i + HOR)] - e) / risk


def run(sym, grp):
    d = pd.read_csv(f"{CD}/{sym}/15m.csv").drop_duplicates("open_time").sort_values("open_time")
    g = d.groupby(d.open_time // 3600 * 3600).agg(n=("open", "size"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index(); g = g[g.n == 4]
    t, h, l, c = (g[k].to_numpy(float) for k in ("open_time", "high", "low", "close")); n = len(c)
    if n < LB + 200: return
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy()
    for side in (1, -1):
        H, L, C = (h, l, c) if side > 0 else (-l, -h, -c)
        lvl = pd.Series(H).rolling(LB).max().shift(1).to_numpy()                 # рівень ДО бару i
        hug = 0; set_i = 0; last_brk = -10 ** 9
        for i in range(LB + 15, n - HOR - 1):
            if not (A[i] > 0 and lvl[i] == lvl[i]): hug = 0; continue
            if lvl[i] != lvl[i - 1]: hug = 0; set_i = i - 1                      # рівень змінився (оновили або старий випав із вікна)
            y = pd.Timestamp(t[i], unit="s").year; P = "P1" if y <= 2022 else ("P2" if y <= 2024 else "P3")
            if C[i] > lvl[i]:                                                    # ПРОБІЙ закриттям
                if i - last_brk >= 24 and i - set_i >= 12:
                    w = max(hug, 3); sl = L[i - w:i + 1].min() - 0.1 * A[i]; e = C[i]; rp = (e - sl) / abs(e)
                    if 0.003 <= rp <= 0.05:
                        b = "з ходу" if hug <= 2 else ("3–5 год" if hug <= 5 else ("6–11 год" if hug <= 11 else ("12–23 год" if hug <= 23 else "24+ год")))
                        T2.append((grp, P, side, b, 10 * (trade(H, L, C, i, e, sl, 2) - FEE / rp), 10 * (trade(H, L, C, i, e, sl, 3) - FEE / rp), y))
                last_brk = i; hug = 0; continue
            if H[i] <= lvl[i] and C[i] >= lvl[i] - NEAR * A[i]: hug += 1
            else: hug = 0
            if hug in NS:
                out = "нічого"
                for j in range(i + 1, i + 49):
                    if C[j] > lvl[i]: out = "пробій"; break
                    if C[j] < lvl[i] - 3 * A[i]: out = "відкат"; break
                T1.append((grp, P, side, hug, out))
                if hug == 12:
                    sl = L[i - 11:i + 1].min() - 0.1 * A[i]; e = C[i]; rp = (e - sl) / abs(e)
                    if 0.003 <= rp <= 0.05: T3.append((grp, P, side, 10 * (trade(H, L, C, i, e, sl, 2) - FEE / rp), 10 * (trade(H, L, C, i, e, sl, 3) - FEE / rp), y))


for grp, syms in (("A", GA), ("B", GB)):
    for s in syms:
        if os.path.exists(f"{CD}/{s}/15m.csv"): run(s, grp)
CELLS = [(g, p) for g in "AB" for p in ("P1", "P2", "P3")]; SD = {1: "опір → вгору (LONG)", -1: "підтримка → вниз (SHORT)"}
A1 = pd.DataFrame(T1, columns=["g", "P", "side", "n", "out"]); A2 = pd.DataFrame(T2, columns=["g", "P", "side", "b", "u2", "u3", "y"]); A3 = pd.DataFrame(T3, columns=["g", "P", "side", "u2", "u3", "y"])
print("ТЕСТ 1. Ціна тримається біля рівня N годин і не відкочує. Що сталося раніше за наступні 48 годин: пробій / відкат на 3 ATR / нічого")
for side in (1, -1):
    print(f"\n  {SD[side]}")
    for N in NS:
        x = A1[(A1.side == side) & (A1.n == N)]
        if not len(x): continue
        v = x.out.value_counts(normalize=True); cells = " | ".join(f"{100*(x[(x.g==g)&(x.P==p)].out=='пробій').mean():.0f}%" for g, p in CELLS)
        print(f"   тримається {N:2d} год: випадків {len(x):6d} → пробій {100*v.get('пробій',0):.0f}%, відкат {100*v.get('відкат',0):.0f}%, нічого {100*v.get('нічого',0):.0f}%   | частка пробоїв по клітинках (A·P1..B·P3): {cells}")
def table(X, keys, title):
    print(f"\n{title}\n  формат: $ на угоду (n) у клітинках A·P1 | A·P2 | A·P3 || B·P1 | B·P2 | B·P3")
    ok = []
    for key, x in X.groupby(keys, sort=False):
        for col, tg in (("u2", "ціль 2R"), ("u3", "ціль 3R")):
            cs = []; allpos = True
            for g, p in CELLS:
                z = x[(x.g == g) & (x.P == p)][col]
                if len(z) < 50: cs.append(f" — ({len(z)})"); allpos = False
                else: cs.append(f"{z.mean():+.2f} ({len(z)})"); allpos &= z.mean() > 0
            nm = (SD[key[0]] + " · " + key[1]) if isinstance(key, tuple) else SD[key]
            if allpos: ok.append(f"{nm} · {tg}")
            print(f"  {nm:44s} {tg}: " + " | ".join(cs[:3]) + " || " + " | ".join(cs[3:]) + f"   разом {x[col].mean():+.2f}, виграшних {100*(x[col]>0).mean():.0f}%, n={len(x)}" + ("   <<< ПЛЮС У ВСІХ 6" if allpos else ""))
    print("  у плюсі в усіх 6 клітинках: " + ("; ".join(ok) if ok else "НІЧОГО"))
A2["b"] = pd.Categorical(A2.b, ["з ходу", "3–5 год", "6–11 год", "12–23 год", "24+ год"], ordered=True); A2 = A2.sort_values(["side", "b"], ascending=[False, True])
table(A2, ["side", "b"], "ТЕСТ 2. Вхід на пробої рівня: чим довше ціна трималась біля рівня перед пробоєм, тим краще?")
table(A3, "side", "ТЕСТ 3. Вхід заздалегідь: ціна 12 годин тримається біля рівня, пробою ще немає")

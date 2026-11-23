"""READ-ONLY. ПЕРЕВІРКА «імпульс за тижні/місяці» (22.11.2026): міжмонетний (cross-sectional) і часовий (time-series) momentum на ДЕННИХ свічках, 2019/2020–2026.
Без фігур, без стопів. Лише рейтинг і арифметика. Публічна ідея (ЗОВНІШНЄ): монети з найвищим зростанням за останні L днів продовжують рости, найслабші — падати (momentum). Усі параметри з сітки показуємо, жодного відбору «найкращого».
 CSM  : кожні H днів сортуємо монети за зростанням за L днів (на закритті дня t), LONG верхні 20% / SHORT нижні 20%, рівні ваги; прибуток береться з дня t+1 (без заглядання вперед). Також «лише LONG верхніх 20% мінус рівний кошик усіх» (перевага над ринком).
 TSM  : кожна монета окремо: LONG якщо зростання за L днів > 0, SHORT якщо < 0; ваги обернено пропорційні 60-денній мінливості, сума модулів = 1.
Витрати: 0.06% на кожну зміну позиції (комісія + прослизання, одна сторона). Капітал $5000 = валова позиція 1× (сума модулів ваг = 1).
Метрики: річна дохідність на $5000, Шарп, макс. просадка, по роках; період ділимо: 2020–2021 (поза вибіркою для решти наших ідей), 2022–2026.
Використання: csm.py fetch DIR SYMS  |  csm.py run DIR SYMS OUT"""
import io, os, sys, zipfile, urllib.request
import numpy as np, pandas as pd
mode, D, SYMS = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
MONTHS = [f"{y}-{m:02d}" for y in range(2019, 2027) for m in range(1, 13) if (2019, 9) <= (y, m) <= (2026, 10)]
if mode == "fetch":
    os.makedirs(D, exist_ok=True)
    for s in SYMS:
        parts = []
        for mo in MONTHS:
            u = f"https://data.binance.vision/data/futures/um/monthly/klines/{s}/1d/{s}-1d-{mo}.zip"
            try:
                with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "office-research"}), timeout=60) as r: z = zipfile.ZipFile(io.BytesIO(r.read()))
            except Exception: continue
            for ln in z.read(z.namelist()[0]).decode().splitlines():
                p = ln.split(",")
                if p[0].isdigit(): parts.append((int(p[0]) // 1000 if int(p[0]) > 10**11 else int(p[0]), float(p[4]), float(p[7]) if len(p) > 7 else 0.0))
        if parts:
            pd.DataFrame(sorted(set(parts)), columns=["t", "close", "qvol"]).to_csv(f"{D}/{s}.csv", index=False); print(s, len(parts), end="; ")
    print(); sys.exit(0)
OUT = sys.argv[4]
C = {}; Q = {}
for s in SYMS:
    p = f"{D}/{s}.csv"
    if os.path.exists(p):
        d = pd.read_csv(p); d["day"] = d.t // 86400; d = d.drop_duplicates("day").set_index("day"); C[s] = d.close; Q[s] = d.qvol
C = pd.DataFrame(C).sort_index(); Q = pd.DataFrame(Q).sort_index(); idx = pd.to_datetime(C.index * 86400, unit="s"); yrs = idx.year
R = C.pct_change()                                       # дохід дня t (закриття t-1 → закриття t)
vol60 = R.rolling(60).std()
FEE1 = 0.0006; CAP = 5000.0
print(f"IMPULS ЗА ТИЖНІ/МІСЯЦІ: монет {C.shape[1]}, днів {len(C)}, {idx[0]:%Y-%m-%d} — {idx[-1]:%Y-%m-%d}; витрати {FEE1*100:.2f}% на кожну зміну позиції; капітал ${CAP:.0f} = валова позиція 1×")
def evalw(W):
    W = W.fillna(0.0)
    gross = (W.shift(1) * R.fillna(0.0)).sum(axis=1)        # вага, сформована на закритті дня t-1, заробляє дохід дня t
    cost = W.diff().abs().sum(axis=1).fillna(0.0) * FEE1
    net = gross - cost
    return net
def summ(net, lo, hi):
    m = (yrs >= lo) & (yrs <= hi); x = net[m]
    if len(x) < 100: return None
    eq = (1 + x).cumprod(); dd = (eq / eq.cummax() - 1).min(); ann = x.mean() * 365; sh = x.mean() / x.std() * np.sqrt(365) if x.std() > 0 else np.nan
    return ann, sh, dd
def line(name, net):
    out = []
    for lo, hi, lab in ((2020, 2021, "2020–21"), (2022, 2026, "2022–26")):
        s = summ(net, lo, hi)
        if s: out.append(f"{lab}: {100*s[0]:+.0f}%/рік (${CAP*s[0]:+.0f}), Шарп {s[1]:+.2f}, просадка {100*s[2]:.0f}%")
    py = ", ".join(f"{y}:{100*net[yrs==y].sum():+.0f}%" for y in sorted(set(yrs)) if (yrs == y).sum() > 100)
    print(f" {name:38s} " + " | ".join(out) + f"\n{'':40s}по роках: {py}")
def csm(L, H, long_only=False):
    mom = C / C.shift(L) - 1; W = pd.DataFrame(0.0, index=C.index, columns=C.columns); last = None
    for k, t in enumerate(C.index):
        if k % H == 0:
            sc = mom.loc[t].dropna()
            sc = sc[Q.loc[t, sc.index] > 0] if len(sc) else sc
            if len(sc) >= 10:
                n = max(2, int(len(sc) * 0.2)); top = sc.nlargest(n).index; bot = sc.nsmallest(n).index; w = pd.Series(0.0, index=C.columns)
                if long_only:
                    w[top] = 1.0 / n; w[sc.index] -= 1.0 / len(sc); w = w / 2          # LONG верх 20% мінус рівний кошик (валова 1×)
                else: w[top] = 0.5 / n; w[bot] = -0.5 / n
                last = w
        if last is not None: W.loc[t] = last
    return W
QV30 = Q.rolling(30).mean()
def tsm(L, H, topn=None, equal=False):
    mom = C / C.shift(L) - 1; W = pd.DataFrame(0.0, index=C.index, columns=C.columns); last = None
    for k, t in enumerate(C.index):
        if k % H == 0:
            sc = np.sign(mom.loc[t]).replace(0, np.nan).dropna()
            if topn: sc = sc[sc.index.isin(QV30.loc[t].dropna().nlargest(topn).index)]      # лише найліквідніші топ-N за обсягом торгів
            iv = (1 / vol60.loc[t, sc.index]).replace([np.inf], np.nan).dropna(); sc = sc[iv.index]
            if equal: iv = iv * 0 + 1
            if len(sc) >= 5: w = pd.Series(0.0, index=C.columns); w[sc.index] = sc * iv / iv.sum(); last = w
        if last is not None: W.loc[t] = last
    return W
if os.environ.get("ROBUST") == "1":
    print("\n=== СТІЙКІСТЬ найкращого за 2020–21 вибору (L=30, H=7) та сусідів: ліквідність, ваги, витрати ===")
    for (L, H) in ((30, 7), (14, 7), (30, 14), (14, 14)):
        for topn in (None, 30, 20, 10):
            for equal in (False, True):
                for fee in (0.0006, 0.0015):
                    FEE1 = fee
                    line(f"TSM L={L} H={H} топ{topn or 'всі'} {'рівні' if equal else 'за мінливістю'} витрати {fee*100:.2f}%", evalw(tsm(L, H, topn, equal)))
    sys.exit(0)
bench = pd.DataFrame(1.0 / C.shape[1], index=C.index, columns=C.columns).where(C.notna(), 0.0); bench = bench.div(bench.sum(axis=1).replace(0, np.nan), axis=0)
print("\n=== Контрольний кошик: просто тримати всі монети порівну ==="); line("тримати все (LONG, рівні ваги)", evalw(bench))
for L in (7, 14, 30, 60, 90):
    for H in (7, 14, 30):
        print(f"\n--- L={L} днів дивимось назад, H={H} днів перетримуємо ---")
        line("CSM LONG верх20% / SHORT низ20%", evalw(csm(L, H)))
        line("CSM LONG верх20% мінус кошик", evalw(csm(L, H, True)))
        line("TSM кожна монета за своїм знаком", evalw(tsm(L, H)))

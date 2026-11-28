import pandas as pd, sys
D = pd.read_csv(sys.argv[1]); D["dt"] = pd.to_datetime(D.date); D["mo"] = D.dt.dt.strftime("%Y-%m")
print(D.status.value_counts().to_dict()); print("період", D.dt.min(), D.dt.max())
C = D[D.m1.notna()].copy(); print("закритих із підсумком:", len(C))
for m in ("m1", "m2", "m3", "z"): print(m, f"сума ${10*C[m].sum():+.0f}, на угоду ${10*C[m].mean():+.2f}, виграшних {100*(C[m]>0).mean():.0f}%")
def tab(col, m="z", minn=15):
    g = C.groupby(col).agg(n=(m, "size"), usd=(m, lambda s: round(10 * s.sum())), per=(m, lambda s: round(10 * s.mean(), 2)), win=(m, lambda s: round(100 * (s > 0).mean())), m1=("m1", lambda s: round(10 * s.sum())))
    print(f"\n--- {col}"); print(g[g.n >= minn].to_string())
for c in ("mo", "tier", "kind", "dir", "tf", "ses", "regime", "ai", "kz", "against", "add"): tab(c)
C["scb"] = pd.cut(C.score, [-2, 11, 13, 15, 17, 20]); tab("scb"); C["slb"] = pd.cut(C.slp, [0, 2, 3, 4, 6, 50]); tab("slb"); C["rrb"] = pd.cut(C.rr1, [0, 1, 1.5, 2, 3, 99]); tab("rrb"); C["aib"] = pd.cut(C.ai_s, [-2, 0, 40, 60, 80, 100]); tab("aib")
C["stock"] = C.sym.isin([s for s in C.sym.unique() if s[:-4] in ("AMD","INTC","NVDA","TSLA","AAPL","MSFT","PLTR","HOOD","TSM","WDC","ASTS","IREN","SOXL","EWY","NOK","MU","COIN","MSTR","GOOGL","META","AMZN","XAG","XAU")]); tab("stock")
print("\nтоп монет за кількістю:"); print(C.groupby("sym").agg(n=("m3","size"),usd=("m3",lambda s: round(10*s.sum()))).sort_values("n",ascending=False).head(12).to_string())
print("\nтривалість год (медіана):", C.dur_h.median(), "| SL:", C[C.status=='SL'].dur_h.median(), "| TP:", C[C.status.str.startswith('TP')].dur_h.median())

print("\n=== модель за розміром (z): по місяцях і напрямках"); print((10*C.pivot_table(index="mo", columns="dir", values="z", aggfunc="sum")).round(0).to_string())
d=C.assign(day=C.dt.dt.date).groupby("day").z.sum()*10; print("днів",len(d),"у плюсі",int((d>0).sum()),"найгірший день",round(d.min()),"найкращий",round(d.max())); eq=d.cumsum(); print("найбільше падіння",round((eq-eq.cummax()).min()))
S=C[C.dir=="SHORT"]; print("SHORT по місяцях:",(10*S.groupby("mo").z.sum()).round(0).to_dict()); L=C[C.dir=="LONG"]; print("LONG по місяцях:",(10*L.groupby("mo").z.sum()).round(0).to_dict())
print("ПРЕМІУМ+SHORT+15m:",len(C[(C.tier=="ПРЕМІУМ")&(C.dir=="SHORT")&(C.tf=="15m")]),round(10*C[(C.tier=="ПРЕМІУМ")&(C.dir=="SHORT")&(C.tf=="15m")].z.sum()))

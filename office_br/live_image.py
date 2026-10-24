"""B&R evidence-only image. Never paint invented price levels."""
from __future__ import annotations
import json
import math
import os
import tempfile
from datetime import datetime, timezone

def render(row, bars):
    if not isinstance(bars,list) or len(bars)<100:
        raise ValueError("missing Binance Futures M15 history")
    prices=[(float(x["open"]),float(x["high"]),float(x["low"]),float(x["close"])) for x in bars]
    if not all(all(math.isfinite(p) and p>0 for p in b) for b in prices):
        raise ValueError("invalid candles")
    last=datetime.fromisoformat(str(bars[-1]["ts"]).replace("Z","+00:00")).timestamp()
    if float(row["confirm_ts"])-last>900 or last>float(row["confirm_ts"]):
        raise ValueError("candles not aligned with signal confirmation")
    from matplotlib import pyplot as plt
    from matplotlib.patches import Rectangle
    from office_price_format import format_px
    sym=row["symbol"]
    target=json.loads(row["targets_json"]) if isinstance(row["targets_json"],str) else row["targets_json"]
    vals=[("Пробій",float(row["level"]),"#62b7fd"),("Вхід",float(row["entry"]),"#facb45"),("SL",float(row["sl"]),"#fb465a")]
    vals.extend((f"TP{i}",float(z["p"]),"#32db86") for i,z in enumerate(target[:3],1))
    fig,ax=plt.subplots(figsize=(8.2,10.4),facecolor="#ffffff")
    fig.subplots_adjust(left=.09,right=.88,bottom=.31,top=.85)
    fig.text(.07,.958,f"B&R-{row['seq']}",color="#637185",fontsize=12,fontweight="bold")
    fig.text(.07,.907,sym+"  ·  "+row["direction"],color="#f4434b" if row["direction"]=="SHORT" else "#119f6a",fontsize=21,fontweight="bold")
    ax.set_facecolor("#071521")
    sample=prices[-95:]
    for i,(o,h,l,c) in enumerate(sample):
        clr="#00c9a6" if c>=o else "#fb4f60"
        ax.vlines(i,l,h,color=clr,linewidth=0.8)
        ax.add_patch(Rectangle((i-.32,min(o,c)),.64,max(abs(c-o),1e-12),facecolor=clr,edgecolor=clr))
    for label,price,clr in vals:
        ax.axhline(price,color=clr,linestyle="--",alpha=.8,linewidth=1)
        ax.text(len(sample)-1,price," "+label+" "+format_px(price,sym),color=clr,va="bottom",ha="right",fontsize=9,fontweight="bold",
                bbox=dict(facecolor="#071521",edgecolor="none",alpha=.9,pad=1))
    # True historical extremes only: no synthetic liquidity zones.
    past=sample[:-1]
    hi=max(x[1] for x in past);lo=min(x[2] for x in past)
    ax.axhspan(hi-(hi-lo)*.035,hi,color="#ec4a67",alpha=.25)
    ax.axhspan(lo,lo+(hi-lo)*.035,color="#398fe8",alpha=.2)
    ax.axhline(hi,color="#fa6385",alpha=.6,linewidth=.9)
    ax.axhline(lo,color="#4d9ded",alpha=.7,linewidth=.9)
    ax.text(1,hi,"Попередній максимум",color="#ff91a8",fontsize=8,va="bottom")
    ax.text(1,lo,"Попередній мінімум",color="#87c0fc",fontsize=8,va="bottom")
    ax.set_xlim(-1,len(sample)+1)
    ax.set_title(f"{sym}  ·  M15",color="white",fontsize=11,loc="left",pad=11)
    ax.tick_params(colors="#abb6c5",labelsize=8)
    ax.grid(color="#29394b",alpha=.3)
    for side in ax.spines.values():side.set_color("#27394e")
    # Approved compact footer. Every number is from the stored B&R plan.
    entry=float(row["entry"]); stop=float(row["sl"]); risk=abs(entry-stop)
    def number(p):
        return format_px(p,sym).replace(".",",")
    def pct(p):
        return f"{abs(p-entry)/entry*100:.2f}".replace(".",",")
    fig.text(.08,.277,"Пробій:  "+number(float(row["level"]))+"  —  закриття "+("вище" if row["direction"]=="LONG" else "нижче")+" підтверджено",
             fontsize=11,color="#142030",weight="bold")
    footer=[("ВХІД",entry,"#dfad21"),("SL",stop,"#e63645")]
    footer.extend((f"TP{i}",float(t["p"]),"#079b55") for i,t in enumerate(target[:3],1))
    for k,(name,price,color) in enumerate(footer):
        y=.236-k*.034
        fig.text(.09,y,"●",fontsize=14,color=color,va="center")
        suffix=""
        if name=="SL": suffix="   (−"+pct(price)+"%)"
        elif name.startswith("TP"): suffix="   (+"+pct(price)+"% · "+(f"{abs(price-entry)/risk:.2f}".replace(".",",") if risk else "—")+"R)"
        fig.text(.135,y,f"{name}:   {number(price)}{suffix}",fontsize=11.5,fontweight="bold",color="#142030",va="center")
    fig.text(.09,.047,"✕ Скасування: закриття "+("нижче" if row["direction"]=="LONG" else "вище")+
             " "+number(float(row["level"]))+" до входу",fontsize=10.5,color="#bd2636",weight="bold")
    fd,path=tempfile.mkstemp(prefix="br_live_",suffix=".png")
    os.close(fd)
    try:fig.savefig(path,dpi=170,facecolor=fig.get_facecolor())
    finally:plt.close(fig)
    return path

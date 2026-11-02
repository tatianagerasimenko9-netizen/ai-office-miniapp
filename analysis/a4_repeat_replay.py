"""A4: offline duplicate suppression comparison; does NOT alter PR #284 or live.

Reads 970 exported deduplicated PSV plans. Candidate suppression only for
same symbol/direction inside a HYPOTHESIS window. Baseline outcome is first
TP1 or SL from recorded events, not independent M1 replay.
"""
import argparse
import csv
import glob
from pathlib import Path

OFF=1790000000


def records(pattern):
    out=[]
    for path in sorted(glob.glob(pattern)):
        for line in Path(path).read_text().splitlines():
            p=line.split("|")
            if len(p)<8 or not p[0].isdigit(): continue
            events=[]
            for e in p[7].split(","):
                if "@" in e:
                    k,t=e.split("@",1)
                    events.append((k,int(t)+OFF))
            risk=abs(float(p[4])-float(p[5]))
            if risk<=0 or not any(k=="E" for k,_ in events) or any(k=="AMB" for k,_ in events):
                continue
            first=next(((k,t) for k,t in sorted(events,key=lambda x:x[1]) if k in ("T1","SL")),None)
            if first is None: continue
            price=float(p[4]);target=float(p[6].split(",")[0].split(":")[0])
            r=(abs(target-price)/risk if first[0]=="T1" else -1)-0.0015*price/risk
            out.append({"seq":p[0],"symbol":p[1],"dir":p[2],"ts":int(p[3]),"r":r})
    return sorted(out,key=lambda x:(x["ts"],int(x["seq"])))


def filter_repeats(rows,window_seconds):
    seen={}
    kept=[]
    removed=[]
    for row in rows:
        key=(row["symbol"],row["dir"])
        last=seen.get(key)
        if last is not None and 0<=row["ts"]-last<window_seconds:
            removed.append(row)
        else:
            kept.append(row)
            seen[key]=row["ts"]
    return kept,removed


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--plans",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--windows-minutes",default="15,60,120",
                    help="HYPOTHESIS grid, not automatic recommendations")
    args=ap.parse_args()
    rows=records(args.plans)
    baseline=sum(x["r"] for x in rows)/len(rows) if rows else None
    result=[]
    for w in [int(i) for i in args.windows_minutes.split(",")]:
        kept,removed=filter_repeats(rows,w*60)
        result.append({"window_min_hypothesis":w,"kept":len(kept),"suppressed":len(removed),
                       "kept_net_r":sum(x["r"] for x in kept)/len(kept) if kept else None,
                       "removed_net_r":sum(x["r"] for x in removed)/len(removed) if removed else None})
    path=Path(args.out);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=["window_min_hypothesis","kept","suppressed","kept_net_r","removed_net_r"])
        writer.writeheader();writer.writerows(result)
    print({"n":len(rows),"baseline_net_r":baseline,"result":result,
           "limitation":"Selection bias; no CI or out-of-sample proof. Do not merge live suppression."})


if __name__=="__main__":
    main()

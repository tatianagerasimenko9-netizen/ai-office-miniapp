import json, sys, time, urllib.request
sys.path.insert(0, ".")
import office_signal_track as T

PLANS = json.load(open("plans.json"))
NOW = time.time()


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "x"}), timeout=25) as r:
        return json.loads(r.read().decode())


for p in PLANS:
    if p["sym"] not in ("SYRUPUSDT", "VVVUSDT"):
        continue
    plan = {"scenario_id": "x", "symbol": p["sym"], "direction": p["dir"], "entry": p["entry"], "sl": p["sl"], "tp1": p["tp1"], "tp2": p["tp2"], "tp3": p["tp3"],
            "confirmed_ts": p["t"], "valid_until_ts": p["valid"]}
    d = get(f"https://ai-office-miniapp.onrender.com/api/v2/candles?symbol={p['sym']}&tf=M15&limit=500")
    cs = d.get("candles", [])
    print(p["sym"], "src", d.get("source"), "status", d.get("data_status"), "n", len(cs), "as_of", d.get("as_of"), "now", time.strftime("%H:%M:%S", time.gmtime(NOW)))
    for c in cs[-6:]:
        print("   ", time.strftime("%H:%M", time.gmtime(c["time"])), c["open"], c["high"], c["low"], c["close"], "forming" if c.get("forming") else "")
    res = T.simulate(plan, cs_dicts := [{"ts": c["ts"], "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]} for c in cs], NOW)
    print("   simulate(15m):", json.dumps({k: res[k] for k in ("status", "filled_at", "reached", "stopped", "result_at")}, default=str))
    levels = T._levels_of(res) if hasattr(T, "_levels_of") else None
    print("   levels:", levels)

import json
import urllib.parse
import urllib.request

B = "https://ai-office-miniapp.onrender.com"
IDS = ["SCN|OPNUSDT|LONG|H1|a4e62466ee09a1ec", "SCN|ONEUSDT|SHORT|H1|7643432c6c6075af"]


def get(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(B + p, headers={"User-Agent": "x"}), timeout=60).read().decode())


for sid in IDS:
    d = get("/api/v2/scenario?id=" + urllib.parse.quote(sid, safe=""))
    h = d.get("human") or {}
    r = h.get("ready") or {}
    print("\n====", sid)
    print("state:", h.get("state"), h.get("state_ua"), "| data_source:", h.get("data_source"))
    print("entry:", r.get("entry"), "| max_entry:", r.get("max_entry"), "| valid_until:", r.get("valid_until"))
    print("levels:", [(x["k"], x["px"], x.get("pct"), x.get("why")) for x in r.get("levels", [])])
    print("setup:", (r.get("setup") or {}).get("name"), "| why:", (r.get("setup") or {}).get("why"))
    print("market:", r.get("market"))
    print("phase_line:", r.get("phase_line"))
    print("now:", json.dumps(h.get("now"), ensure_ascii=False)[:400])
    print("progress:", json.dumps(h.get("progress"), ensure_ascii=False)[:300])

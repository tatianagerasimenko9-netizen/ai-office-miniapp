import urllib.request, re, hashlib, os
out = set(); marker = ""
for _ in range(30):
    x = urllib.request.urlopen("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/monthly/klines/" + (f"&marker={marker}" if marker else ""), timeout=60).read().decode()
    out |= set(re.findall(r"<Prefix>data/futures/um/monthly/klines/([A-Z0-9]+)/</Prefix>", x))
    m = re.search(r"<NextMarker>(.*?)</NextMarker>", x)
    if not m: break
    marker = m.group(1)
c = sorted((s for s in out if s.endswith("USDT") and "_" not in s), key=lambda s: hashlib.md5(s.encode()).hexdigest())
k = int(os.environ.get("SHARD", "0")); print(",".join(c[k::6]))

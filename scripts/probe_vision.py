import io, sys, urllib.request, zipfile
B = "https://data.binance.vision/data/"
D = "2026-09-30"
paths = [
 f"futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-{D}.zip",
 f"futures/um/daily/klines/BTCUSDT/1m/BTCUSDT-1m-{D}.zip",
 "futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2026-08.zip",
 f"futures/um/daily/liquidationSnapshot/BTCUSDT/BTCUSDT-liquidationSnapshot-{D}.zip",
 f"futures/um/daily/bookDepth/BTCUSDT/BTCUSDT-bookDepth-{D}.zip",
 f"futures/um/daily/bookTicker/BTCUSDT/BTCUSDT-bookTicker-{D}.zip",
 f"futures/um/daily/markPriceKlines/BTCUSDT/1m/BTCUSDT-1m-{D}.zip",
 f"futures/um/daily/premiumIndexKlines/BTCUSDT/1m/BTCUSDT-1m-{D}.zip",
 f"option/daily/EOHSummary/BTCUSDT/BTCUSDT-EOHSummary-{D}.zip",
 f"option/daily/BVOLIndex/BTCBVOLUSDT/BTCBVOLUSDT-BVOLIndex-{D}.zip",
 "futures/um/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08.zip",
 "futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2024-06-30.zip",
 "futures/um/daily/liquidationSnapshot/BTCUSDT/BTCUSDT-liquidationSnapshot-2023-06-30.zip",
]
for p in paths:
    try:
        r = urllib.request.urlopen(urllib.request.Request(B + p, headers={"User-Agent": "x"}), timeout=60)
        raw = r.read()
        z = zipfile.ZipFile(io.BytesIO(raw))
        n = z.namelist()[0]
        txt = z.read(n)[:600].decode("utf-8", "replace").splitlines()
        print("OK ", p, len(raw), "bytes |", txt[0][:230], "|", (txt[1] if len(txt) > 1 else "")[:200])
    except Exception as e:
        print("NO ", p, type(e).__name__, str(e)[:80])

"""Дописує до candles/<SYM>/15m.csv свічки за сьогодні зі СПОТ-дзеркала Binance (data-api.binance.vision), бо денний архів ф'ючерсів з'являється лише наступного дня.
ЛИШЕ для діагностики (спот трохи відрізняється від ф'ючерсів). Використання: append_spot_tail.py CANDLES_DIR FROM_ISO SYMS"""
import sys, json, urllib.request
from datetime import datetime, timezone
import pandas as pd
cd, frm, syms = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
t0 = int(datetime.fromisoformat(frm).replace(tzinfo=timezone.utc).timestamp() * 1000)
for s in syms:
    p = f"{cd}/{s}/15m.csv"; d = pd.read_csv(p)
    cols = list(d.columns); last = float(d.open_time.max())
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={s}&interval=15m&startTime={t0}&limit=1000"
    try:
        rows = json.load(urllib.request.urlopen(url, timeout=30))
    except Exception as exc:
        print(s, "ПОМИЛКА", type(exc).__name__); continue
    new = [r for r in rows if r[0] / 1000 > last and r[6] / 1000 < datetime.now(timezone.utc).timestamp()]      # лише закриті бари
    add = pd.DataFrame([{**{c: 0 for c in cols}, "open_time": r[0] / 1000, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])} for r in new])
    if len(add): pd.concat([d, add[cols]]).to_csv(p, index=False)
    print(s, "дописано", len(add), "барів; до", datetime.fromtimestamp(float(add.open_time.max()) if len(add) else last, timezone.utc).strftime("%m-%d %H:%M"))

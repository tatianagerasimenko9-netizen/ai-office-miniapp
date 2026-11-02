"""READ-ONLY. Розбір конкретного руху: що було ДО піку/низу, де був діапазон Азії, зняття вчорашніх/азійських меж, швидкість і форма падіння.
Дані: публічний дзеркальний API спот-свічок (data-api.binance.vision), M15, UTC (спот BTCUSDT мало відрізняється від ф'ючерсів).
Використання: case_day.py SYMBOL YYYY-MM-DD   (день руху; береться також попередній)"""
import sys, json, urllib.request, datetime as dt
import numpy as np
sym, day = sys.argv[1], sys.argv[2]
d0 = dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc)
start = int((d0 - dt.timedelta(days=8)).timestamp() * 1000); end = int((d0 + dt.timedelta(days=1)).timestamp() * 1000)
rows = []; t = start
while t < end:
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval=15m&startTime={t}&limit=1000"
    k = json.loads(urllib.request.urlopen(url, timeout=60).read())
    if not k: break
    rows += k; t = k[-1][0] + 900000
a = np.array([[r[0] // 1000, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in rows])
ts, o, h, l, c, v = a.T
T = lambda x: dt.datetime.fromtimestamp(x, dt.timezone.utc).strftime("%m-%d %H:%M")
n = len(c); pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); atr = np.convolve(tr, np.ones(14) / 14, mode="same")
day_ts = int(d0.timestamp()); prev_ts = day_ts - 86400
m_day = (ts >= day_ts) & (ts < day_ts + 86400); m_prev = (ts >= prev_ts) & (ts < day_ts)
print(f"=== {sym} {day} (UTC), спот M15; свічок {n} ===")
ia = np.nonzero(m_day & (((ts % 86400) // 3600) < 7))[0]; ah, al = h[ia].max(), l[ia].min()
print(f"Азія {day} 00-07 UTC: low {al:.1f} high {ah:.1f}  (ширина {100*(ah-al)/al:.2f}%)")
ip = np.nonzero(m_prev)[0]; print(f"Вчора: high {h[ip].max():.1f} ({T(ts[ip][np.argmax(h[ip])])}), low {l[ip].min():.1f} ({T(ts[ip][np.argmin(l[ip])])}), close {c[ip[-1]]:.1f}")
idd = np.nonzero(m_day)[0]; hi_i = idd[np.argmax(h[idd])]; lo_i = idd[np.argmin(l[idd])]
print(f"День: high {h[hi_i]:.1f} о {T(ts[hi_i])} UTC; low {l[lo_i]:.1f} о {T(ts[lo_i])} UTC; падіння {100*(h[hi_i]-l[lo_i])/h[hi_i]:.2f}% за {(ts[lo_i]-ts[hi_i])/3600:.1f} год; у ATR14: {(h[hi_i]-l[lo_i])/atr[hi_i]:.1f}")
print(f"Пік дня vs Азія: {'вище Asian high на '+format(100*(h[hi_i]-ah)/ah,'.2f')+'%' if h[hi_i]>ah else 'в межах Азії'}; пік вище вчорашнього high: {h[hi_i] > h[ip].max()}")
print(f"Об'єм: біля піку(±4 свічки) {v[max(0,hi_i-4):hi_i+5].mean():.0f} vs середній за 3 дні {v[-288:].mean():.0f}; біля низу {v[max(0,lo_i-4):lo_i+5].mean():.0f}")
print("\nГодинна карта дня (UTC): open high low close, %зміни, об'єм")
for hh in range(0, 24):
    mm = np.nonzero(m_day & (((ts % 86400) // 3600) == hh))[0]
    if len(mm) == 0: continue
    print(f"  {hh:02d}:00  o {o[mm[0]]:.1f}  h {h[mm].max():.1f}  l {l[mm].min():.1f}  c {c[mm[-1]]:.1f}  {100*(c[mm[-1]]-o[mm[0]])/o[mm[0]]:+.2f}%  vol {v[mm].sum():.0f}")
print("\n##### ПІДСУМОК case_day готово")

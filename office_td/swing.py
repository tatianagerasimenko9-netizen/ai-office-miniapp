"""СВІНГ (ТЕСТ, гіпотеза): трендова стратегія на 4-годинному графіку. Лише спостереження: ордерів немає.
Походження: широкий пошук на історії 2022-2026 (docs/handoff/br-profitability/IMPROVEMENTS_LOG_UA.md, розділ G; strategy_search/discover.py). Три «рукави», усі за трендом (MA200 на H4):
  1) Пробій каналу: закриття вище максимуму 20 попередніх свічок (лонг) / нижче мінімуму (шорт);
  2) RSI(2) повернення: RSI(2) < 10 (лонг) / > 90 (шорт);
  3) Боллінджер(20, 2) повернення: закриття нижче нижньої смуги (лонг) / вище верхньої (шорт).
Вхід — на закритті сигнальної свічки (у бектесті: відкриття наступної), стоп 3 ATR(14), ціль 6 стопів, тримати до 10 діб. Одна позиція на монету. Подія = умова щойно стала істинною.
Сигнал пишеться в br_test_signal з sig_id 'SW|…'; доставку й супровід (ENTRY/TP/SL) робить контур office_br.live. Вимкнути: SW_LIVE=0."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "BNBUSDT", "LTCUSDT", "DOTUSDT", "ATOMUSDT")
H1_BARS = 1500
PER = 14400
STOP_ATR, TP_R, MIN_SP = 3.0, 6.0, 0.0005
MAX_AGE_S = 1200
_LAST_H4 = 0
RULE_NAMES = {"breakout": "пробій каналу 20 свічок", "rsi2": "RSI(2) повернення", "bollinger": "Боллінджер повернення"}


def enabled() -> bool:
    return os.getenv("SW_LIVE", "1").strip().lower() in ("1", "true", "yes", "on")


def _epoch(x: dict) -> float:
    return datetime.fromisoformat(str(x["ts"]).replace("Z", "+00:00")).timestamp()


def h4_from_h1(rows: List[dict]) -> Optional[Dict[str, np.ndarray]]:
    """4-годинні бари з годинних (лише повні: 4 години). Повертає масиви open_time/open/high/low/close."""
    if not isinstance(rows, list) or len(rows) < 800: return None
    t = np.array([_epoch(x) for x in rows]); g = lambda k: np.array([float(x[k]) for x in rows])
    d = pd.DataFrame({"t": t, "o": g("open"), "h": g("high"), "l": g("low"), "c": g("close")}); d["b"] = (d.t // PER * PER).astype(float)
    a = d.groupby("b").agg(n=("t", "size"), o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last")).reset_index()
    a = a[a.n == 4]
    return {"t": a.b.to_numpy(float), "o": a.o.to_numpy(float), "h": a.h.to_numpy(float), "l": a.l.to_numpy(float), "c": a.c.to_numpy(float)}


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); return pd.Series(tr).rolling(n).mean().to_numpy()


def _rsi(c, n):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.where(d > 0, d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.where(d < 0, -d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


def _ev(state: np.ndarray) -> np.ndarray:
    s = np.nan_to_num(state.astype(float)) > 0; return s & ~np.r_[False, s[:-1]]


def signals(b: Dict[str, np.ndarray]):
    """Сигнали на ОСТАННЬОМУ закритому барі: [(напрям +1/-1, ключ рукава)], ATR, ціна закриття. Та сама логіка, що в discover.py."""
    h, l, c = b["h"], b["l"], b["c"]; ser = pd.Series
    m200 = ser(c).rolling(200).mean().to_numpy(); up, dn = c > m200, c < m200
    hi20 = ser(h).rolling(20).max().shift(1).to_numpy(); lo20 = ser(l).rolling(20).min().shift(1).to_numpy()
    r2 = _rsi(c, 2); mb = ser(c).rolling(20).mean().to_numpy(); sb = ser(c).rolling(20).std().to_numpy(); ub, lb = mb + 2 * sb, mb - 2 * sb
    rules = {"breakout": (_ev(c > hi20) & up, _ev(c < lo20) & dn), "rsi2": (_ev((r2 < 10) & up), _ev((r2 > 90) & dn)), "bollinger": (_ev((c < lb) & up), _ev((c > ub) & dn))}
    A = _atr(h, l, c); i = len(c) - 1; out = []
    for key, (L_, S_) in rules.items():
        if L_[i]: out.append((1, key))
        if S_[i]: out.append((-1, key))
    return out, float(A[i]) if np.isfinite(A[i]) else float("nan"), float(c[i])


def _open_symbol(db: str, sym: str) -> bool:
    from office_bridge import _fetchone
    return bool(_fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id LIKE 'SW|%' AND symbol = ? AND status IN ('NEW', 'SENT') LIMIT 1", (sym,)))


def record(db: str, sym: str, side: int, why_keys: List[str], bar_open: float, entry: float, atr: float, now: float) -> Optional[str]:
    from office_bridge import _execute, _fetchone
    direction = "LONG" if side > 0 else "SHORT"; sid = f"SW|{sym}|{direction}|{int(bar_open)}"
    if _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id = ?", (sid,)): return None
    risk = STOP_ATR * atr; sl = entry - side * risk; tp = entry + side * TP_R * risk
    nxt = _fetchone(db, "SELECT COALESCE(MAX(seq), 0) + 1 FROM br_test_signal WHERE sig_id LIKE 'SW|%'"); seq = int(nxt[0]) if nxt else 1
    names = "; ".join(RULE_NAMES[k] for k in why_keys)
    trend = "вище" if side > 0 else "нижче"
    why = f"Тренд {'вгору' if side > 0 else 'вниз'}: ціна {trend} 200-середньої (4 год). Сигнал: {names}."
    hyp = {"strategy": "SW_TEST", "rules": why_keys, "why": why, "hold": "до 10 діб", "tf_s": PER, "stop_atr": STOP_ATR, "tp_r": TP_R, "atr": atr, "model": "SWING_H4_TREND"}
    _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
             (sid, seq, sym, direction, entry, bar_open, bar_open + PER, bar_open, entry, sl, json.dumps([{"p": tp, "src": "SW"}]), json.dumps(hyp, default=str), now, "NEW"))
    return sid


def scan(db: str, fetch: Callable, now: Optional[float] = None, symbols: tuple = SYMBOLS) -> int:
    """Один прохід після закриття 4-годинного бару. Повертає кількість нових сигналів, -1 — дані недоступні (повтор у цю ж годину)."""
    from office_br import store
    store.init(db); now = time.time() if now is None else now; n = 0; seen = 0
    for sym in symbols:
        try:
            rows = fetch(sym, "1h", H1_BARS, closed_only=True)
            b = h4_from_h1(rows)
            if b is None or len(b["c"]) < 230: continue
            bar_open = float(b["t"][-1])
            if bar_open + PER > now or now - (bar_open + PER) > MAX_AGE_S: continue      # лише свіжозакритий H4-бар
            seen += 1
            sg, atr, close = signals(b)
            if not sg or not atr > 0 or (STOP_ATR * atr) / close < MIN_SP: continue
            sides = {s for s, _ in sg}
            if len(sides) != 1 or _open_symbol(db, sym): continue                          # одна позиція на монету; суперечливі сигнали пропускаємо
            side = sides.pop(); sid = record(db, sym, side, [k for _, k in sg], bar_open, close, atr, now)
            if sid: n += 1; print(f"[sw] СИГНАЛ {sid} entry={close:.6g} atr={atr:.6g} правила={[k for _, k in sg]}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[sw] scan {sym}: {type(exc).__name__}: {exc}", flush=True)
    if seen == 0: return -1
    print(f"[sw] H4-скан: перевірено {seen} із {len(symbols)} монет; нових сигналів {n}", flush=True)
    return n


def cycle(db: str, fetch: Callable, now: Optional[float] = None) -> Dict[str, int]:
    """Викликається з фонового потоку раз на ~45 с; скан — раз на 4 год, через 20+ секунд після закриття бару."""
    global _LAST_H4
    now = time.time() if now is None else now; out = {"sw_signals": 0}
    k = int(now // PER)
    if k > _LAST_H4 and now - k * PER >= 20:
        got = scan(db, fetch, now)
        if got >= 0: out["sw_signals"] = got; _LAST_H4 = k
    return out

"""ТИХИЙ ЖУРНАЛ (shadow) · «вхід у хвилю 3 за трендом» (EW3). Нічого не надсилає і не відкриває: лише записує гіпотетичні угоди в таблицю sw_shadow і їхній підсумок.
Згода власниці 23.11.2026 («тихий журнал, хай буде»). Правила — ЗОВНІШНЄ (docs/strategies/ELLIOTT_PUBLIC_RULES_UA.md), реалізація наша (ГІПОТЕЗА), та сама, що в бектесті elliott_test.py, варіант A0, K=3, H4, «з трендом»:
причинний ATR-зигзаг (поріг 3×ATR14); на барі, де підтверджено пивот P2: P0 → P1 → P2, хвиля 2 не заходить за початок хвилі 1 (LONG: P2>P0), ціна по той самий бік MA200;
вхід = закриття бару (наближення до відкриття наступного), стоп за P0, ціль P2 + 1,618·(P1−P0), утримання ≤60 H4-барів, SL-першим, комісія 0,10% за круг, ризик $10.
Історія 2022–2026 (журнал, розділ AB): 3 631 угода, +$3 277. Вимкнути: SW_SHADOW=0."""
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

K = 3.0; HOLD = 60; PER = 14400; FEE = 0.001; KIND = "EW3"
DDL = """CREATE TABLE IF NOT EXISTS sw_shadow (
    sid TEXT PRIMARY KEY, kind TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL, bar_ts DOUBLE PRECISION NOT NULL, entry DOUBLE PRECISION NOT NULL, sl DOUBLE PRECISION NOT NULL, tp DOUBLE PRECISION NOT NULL,
    created_ts DOUBLE PRECISION NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', exit_ts DOUBLE PRECISION, exit_px DOUBLE PRECISION, r DOUBLE PRECISION)"""


def enabled() -> bool:
    return os.getenv("SW_SHADOW", "1").strip().lower() in ("1", "true", "yes", "on")


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc))); return pd.Series(tr).rolling(n).mean().to_numpy()


def zigzag(h, l, A, k: float = K) -> List[Tuple[int, int, float, int]]:
    """Причинний зигзаг: (бар підтвердження, бар пивота, ціна, +1 максимум / −1 мінімум). Ідентичний elliott_test.py."""
    n = len(h); out = []; trend = 0; eh, ehi, el, eli = h[0], 0, l[0], 0
    for i in range(1, n):
        if not A[i] > 0: continue
        thr = k * A[i]
        if trend == 0:
            if h[i] > eh: eh, ehi = h[i], i
            if l[i] < el: el, eli = l[i], i
            if eh - l[i] >= thr and ehi < i: out.append((i, ehi, eh, 1)); trend = -1; el, eli = l[i], i
            elif h[i] - el >= thr and eli < i: out.append((i, eli, el, -1)); trend = 1; eh, ehi = h[i], i
        elif trend == 1:
            if h[i] > eh: eh, ehi = h[i], i
            if eh - l[i] >= thr: out.append((i, ehi, eh, 1)); trend = -1; el, eli = l[i], i
        else:
            if l[i] < el: el, eli = l[i], i
            if h[i] - el >= thr: out.append((i, eli, el, -1)); trend = 1; eh, ehi = h[i], i
    return out


def candidate(b: Dict[str, np.ndarray]) -> Optional[Dict[str, float]]:
    """Сигнал EW3 на ОСТАННЬОМУ закритому барі або None."""
    h, l, c = b["h"], b["l"], b["c"]; n = len(c)
    if n < 210: return None
    A = _atr(h, l, c); m200 = pd.Series(c).rolling(200).mean().to_numpy(); Z = zigzag(h, l, A)
    if len(Z) < 3 or Z[-1][0] != n - 1 or not m200[-1] > 0: return None
    P0, P1, (_, _, P2, ty) = Z[-3][2], Z[-2][2], Z[-1]; side = 1 if ty == -1 else -1; w1 = abs(P1 - P0)
    if w1 <= 0 or not ((side > 0 and P2 > P0) or (side < 0 and P2 < P0)): return None            # хвиля 2 не заходить за початок хвилі 1
    if not ((side > 0 and c[-1] > m200[-1]) or (side < 0 and c[-1] < m200[-1])): return None     # лише за трендом (сторона MA200)
    e = float(c[-1]); sl = float(P0); tp = float(P2 + side * 1.618 * w1); risk = (e - sl) * side
    if risk <= 0 or not 0.0005 <= risk / e <= 0.25 or (tp - e) * side <= 0: return None
    return {"side": side, "entry": e, "sl": sl, "tp": tp}


def step(db: str, sym: str, b: Dict[str, np.ndarray], now: Optional[float] = None) -> Optional[str]:
    """Один крок для монети на свіжозакритому H4-барі: закрити гіпотетичні угоди, що завершились, і записати нову, якщо є сигнал і немає відкритої. Повертає sid нової або None."""
    if not enabled(): return None
    from office_bridge import _execute, _fetchall, _fetchone
    now = time.time() if now is None else now; _execute(db, DDL, ())
    t, h, l, c = b["t"], b["h"], b["l"], b["c"]
    for sid, direction, bar_ts, e, sl, tp in _fetchall(db, "SELECT sid, direction, bar_ts, entry, sl, tp FROM sw_shadow WHERE kind = ? AND symbol = ? AND status = 'OPEN'", (KIND, sym)):
        side = 1 if direction == "LONG" else -1; risk = abs(e - sl); idx = [i for i in range(len(t)) if t[i] > bar_ts][:HOLD]; res = None
        for j, i in enumerate(idx):
            if (l[i] <= sl) if side > 0 else (h[i] >= sl): res = ("SL", -1.0, sl, t[i]); break
            if (h[i] >= tp) if side > 0 else (l[i] <= tp): res = ("TP", side * (tp - e) / risk, tp, t[i]); break
        if res is None and len(idx) >= HOLD: i = idx[-1]; res = ("TIME", side * (c[i] - e) / risk, float(c[i]), t[i])
        if res: _execute(db, "UPDATE sw_shadow SET status = ?, r = ?, exit_px = ?, exit_ts = ? WHERE sid = ?", (res[0], float(res[1]) - FEE / (risk / e), float(res[2]), float(res[3]) + PER, sid))
    cd = candidate(b)
    if not cd or _fetchone(db, "SELECT 1 FROM sw_shadow WHERE kind = ? AND symbol = ? AND status = 'OPEN' LIMIT 1", (KIND, sym)): return None
    direction = "LONG" if cd["side"] > 0 else "SHORT"; sid = f"{KIND}|{sym}|{direction}|{int(t[-1])}"
    _execute(db, "INSERT INTO sw_shadow(sid, kind, symbol, direction, bar_ts, entry, sl, tp, created_ts) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", (sid, KIND, sym, direction, float(t[-1]), cd["entry"], cd["sl"], cd["tp"], now))
    print(f"[sw-shadow] {sid} entry={cd['entry']:.6g} sl={cd['sl']:.6g} tp={cd['tp']:.6g} (тихий журнал, без повідомлень)", flush=True)
    return sid

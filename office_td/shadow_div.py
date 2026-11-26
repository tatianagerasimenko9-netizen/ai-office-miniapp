"""ТИХИЙ ЖУРНАЛ (shadow) · «усі дивергенції RSI на 4 годинах» (DIV). Нічого не надсилає і не відкриває: лише записує гіпотетичні угоди в sw_shadow.
Згода власниці 26.11.2026 («фіксувати в тихому журналі треба всі дивергенції, щоб розуміти далі, як це використовувати»). Означення — ЗОВНІШНЄ (класичний теханаліз), числа — як у перевірці
div_lab.py (журнал, розділ AZ; ГІПОТЕЗА): RSI(14) на закритих H4-барах; пивот = екстремум серед 3 барів з обох боків (видно через 3 бари); попередній пивот того ж типу не далі 60 барів.
  RB звичайна бичача (ціна нижче, RSI вище → LONG), HB прихована бичача (ціна вище, RSI нижче → LONG), RS звичайна ведмежа (SHORT), HS прихована ведмежа (SHORT).
Запис: kind = DIV_<вид>_<T|A> (T — за трендом MA200, A — проти); вхід = закриття бару підтвердження, стоп 2×ATR14, ціль 6R, утримання ≤60 барів, SL-першим, комісія 0,10%.
На історії стійко плюсова лише RS за трендом (+$1,7…2,2 на угоду в трьох незалежних групах); решта записується для спостереження. Вимкнути: DIV_SHADOW=0."""
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

K = 3; LOOK = 60; HOLD = 60; PER = 14400; FEE = 0.001; STOP_ATR = 2.0; TP_R = 6.0


def enabled() -> bool:
    return os.getenv("DIV_SHADOW", "1").strip().lower() in ("1", "true", "yes", "on")


def _rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()


def candidates(b: Dict[str, np.ndarray]) -> List[Dict[str, object]]:
    """Дивергенції, що стали видимі на ОСТАННЬОМУ закритому барі (пивот — 3 бари тому). Може бути кілька (мінімум і максимум одночасно — рідко)."""
    h, l, c = b["h"], b["l"], b["c"]; n = len(c); out: List[Dict[str, object]] = []
    if n < 230: return out
    pc = np.r_[c[0], c[:-1]]; atr = float(pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().iloc[-1]); m200 = float(c[-200:].mean()); R = _rsi(c)
    if not atr > 0 or not m200 > 0: return out
    q = n - 1 - K; w = 2 * K + 1
    for typ, x in (("L", l), ("H", h)):
        ext = (pd.Series(x).rolling(w, center=True).min() if typ == "L" else pd.Series(x).rolling(w, center=True).max()).to_numpy()
        if not ext[q] == x[q]: continue
        prev = [p for p in range(max(210, q - LOOK), q - K) if ext[p] == x[p]]
        if not prev: continue
        p = prev[-1]
        if any(ext[j] == x[j] for j in range(p + 1, q)): continue          # попередній пивот має бути сусіднім (між ними немає іншого)
        if not R[q] > 0 or not R[p] > 0: continue
        if typ == "L": kind = "RB" if (l[q] < l[p] and R[q] > R[p]) else ("HB" if (l[q] > l[p] and R[q] < R[p]) else None); side = 1
        else: kind = "RS" if (h[q] > h[p] and R[q] < R[p]) else ("HS" if (h[q] < h[p] and R[q] > R[p]) else None); side = -1
        if not kind: continue
        e = float(c[-1]); risk = STOP_ATR * atr
        if not 0.0005 <= risk / e <= 0.25: continue
        out.append({"kind": f"DIV_{kind}_{'T' if side * (e - m200) > 0 else 'A'}", "side": side, "entry": e, "sl": e - side * risk, "tp": e + side * TP_R * risk})
    return out


def step(db: str, sym: str, b: Dict[str, np.ndarray], now: Optional[float] = None) -> List[str]:
    """Один крок на свіжозакритому H4-барі: закрити завершені записи DIV_* і додати нові (один відкритий на монету і вид). Повідомлень немає."""
    if not enabled(): return []
    from office_bridge import _execute, _fetchall, _fetchone
    from office_td.shadow_wave import DDL
    now = time.time() if now is None else now; _execute(db, DDL, ())
    t, h, l, c = b["t"], b["h"], b["l"], b["c"]
    for sid, direction, bar_ts, e, sl, tp in _fetchall(db, "SELECT sid, direction, bar_ts, entry, sl, tp FROM sw_shadow WHERE kind LIKE 'DIV_%' AND symbol = ? AND status = 'OPEN'", (sym,)):
        side = 1 if direction == "LONG" else -1; risk = abs(e - sl); idx = [i for i in range(len(t)) if t[i] > bar_ts][:HOLD]; res = None
        for i in idx:
            if (l[i] <= sl) if side > 0 else (h[i] >= sl): res = ("SL", -1.0, sl, t[i]); break
            if (h[i] >= tp) if side > 0 else (l[i] <= tp): res = ("TP", side * (tp - e) / risk, tp, t[i]); break
        if res is None and len(idx) >= HOLD: i = idx[-1]; res = ("TIME", side * (c[i] - e) / risk, float(c[i]), t[i])
        if res: _execute(db, "UPDATE sw_shadow SET status = ?, r = ?, exit_px = ?, exit_ts = ? WHERE sid = ?", (res[0], float(res[1]) - FEE / (risk / e), float(res[2]), float(res[3]) + PER, sid))
    made = []
    for cd in candidates(b):
        if _fetchone(db, "SELECT 1 FROM sw_shadow WHERE kind = ? AND symbol = ? AND status = 'OPEN' LIMIT 1", (cd["kind"], sym)): continue
        direction = "LONG" if cd["side"] > 0 else "SHORT"; sid = f"{cd['kind']}|{sym}|{direction}|{int(t[-1])}"
        _execute(db, "INSERT INTO sw_shadow(sid, kind, symbol, direction, bar_ts, entry, sl, tp, created_ts) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", (sid, cd["kind"], sym, direction, float(t[-1]), cd["entry"], cd["sl"], cd["tp"], now))
        print(f"[div-shadow] {sid} entry={cd['entry']:.6g} sl={cd['sl']:.6g} tp={cd['tp']:.6g} (тихий журнал, без повідомлень)", flush=True); made.append(sid)
    return made

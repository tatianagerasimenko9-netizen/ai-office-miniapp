"""ТИХИЙ ЖУРНАЛ (shadow) · «B&R на 4 годинах за трендом» (BR4). Нічого не надсилає і не відкриває: лише записує гіпотетичні угоди в таблицю sw_shadow (kind='BR4') і їхній підсумок.
Згода власниці 25.11.2026 («записуй місяць-два у живому ринку у тихий журнал»). Правила — ті самі, що в бектесті br_hist.py (журнал, розділ AR), ГІПОТЕЗА / OUR_IMPLEMENTATION:
детектор office_br.detect без зміни чисел, але на ЗАКРИТИХ барах H4; сигнал беремо лише на щойно закритому барі і лише за трендом (ціна по той самий бік MA200 H4, що й напрям);
вхід = ціна входу сигналу (закриття бару підтвердження), стоп = 3 × відстань до стопа сигналу, ціль = 3 × цей ризик, утримання ≤60 H4-барів, SL-першим, комісія 0,10% за круг.
Історія 2022–2026, 12 монет: 6 427 угод, +$0,48 на угоду при ризику $10 (0,10%), роки +,+,−,+,+. Найкраща комірка обрана після перегляду — НЕ ПІДТВЕРДЖЕНО, тому лише журнал. Вимкнути: BR4_SHADOW=0."""
from __future__ import annotations

import os
import time
from typing import Dict, Optional

import numpy as np
import pandas as pd

KIND = "BR4"; HOLD = 60; PER = 14400; FEE = 0.001; STOP_X = 3.0; TP_R = 3.0; LOOK = 60


def enabled() -> bool:
    return os.getenv("BR4_SHADOW", "1").strip().lower() in ("1", "true", "yes", "on")


def candidate(b: Dict[str, np.ndarray]) -> Optional[Dict[str, float]]:
    """Сигнал BR4 на ОСТАННЬОМУ закритому H4-барі або None."""
    from office_br import detect
    t, o, h, l, c = b["t"], b["o"], b["h"], b["l"], b["c"]; n = len(c)
    if n < 210: return None
    m200 = float(pd.Series(c).rolling(200).mean().iloc[-1])
    if not m200 > 0: return None
    k0 = max(0, n - 200); tt, oo, hh, ll, cc = (list(map(float, x[k0:])) for x in (t, o, h, l, c)); m = len(cc)   # вікно більше за lookback детектора (96) + ретест/підтвердження
    sg = [s for s in detect.scan(tt, oo, hh, ll, cc, start=m - LOOK) if s["confirm_i"] == m - 1]
    if not sg: return None
    s = sg[-1]; side = 1 if s["direction"] == "LONG" else -1
    if not side * (cc[-1] - m200) > 0: return None                                           # лише за трендом (сторона MA200 H4)
    e = float(s["entry"]); risk = STOP_X * float(s["risk"])
    if risk <= 0 or not 0.0005 <= risk / e <= 0.5: return None
    return {"side": side, "entry": e, "sl": e - side * risk, "tp": e + side * TP_R * risk}


def step(db: str, sym: str, b: Dict[str, np.ndarray], now: Optional[float] = None) -> Optional[str]:
    """Один крок для монети на свіжозакритому H4-барі: закрити завершені гіпотетичні угоди і записати нову, якщо є сигнал і немає відкритої. Повідомлень немає."""
    if not enabled(): return None
    from office_bridge import _execute, _fetchall, _fetchone
    from office_td.shadow_wave import DDL
    now = time.time() if now is None else now; _execute(db, DDL, ())
    t, h, l, c = b["t"], b["h"], b["l"], b["c"]
    for sid, direction, bar_ts, e, sl, tp in _fetchall(db, "SELECT sid, direction, bar_ts, entry, sl, tp FROM sw_shadow WHERE kind = ? AND symbol = ? AND status = 'OPEN'", (KIND, sym)):
        side = 1 if direction == "LONG" else -1; risk = abs(e - sl); idx = [i for i in range(len(t)) if t[i] > bar_ts][:HOLD]; res = None
        for i in idx:
            if (l[i] <= sl) if side > 0 else (h[i] >= sl): res = ("SL", -1.0, sl, t[i]); break
            if (h[i] >= tp) if side > 0 else (l[i] <= tp): res = ("TP", side * (tp - e) / risk, tp, t[i]); break
        if res is None and len(idx) >= HOLD: i = idx[-1]; res = ("TIME", side * (c[i] - e) / risk, float(c[i]), t[i])
        if res: _execute(db, "UPDATE sw_shadow SET status = ?, r = ?, exit_px = ?, exit_ts = ? WHERE sid = ?", (res[0], float(res[1]) - FEE / (risk / e), float(res[2]), float(res[3]) + PER, sid))
    cd = candidate(b)
    if not cd or _fetchone(db, "SELECT 1 FROM sw_shadow WHERE kind = ? AND symbol = ? AND status = 'OPEN' LIMIT 1", (KIND, sym)): return None
    direction = "LONG" if cd["side"] > 0 else "SHORT"; sid = f"{KIND}|{sym}|{direction}|{int(t[-1])}"
    _execute(db, "INSERT INTO sw_shadow(sid, kind, symbol, direction, bar_ts, entry, sl, tp, created_ts) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", (sid, KIND, sym, direction, float(t[-1]), cd["entry"], cd["sl"], cd["tp"], now))
    print(f"[br4-shadow] {sid} entry={cd['entry']:.6g} sl={cd['sl']:.6g} tp={cd['tp']:.6g} (тихий журнал, без повідомлень)", flush=True)
    return sid

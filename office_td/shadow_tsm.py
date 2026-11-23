"""ТИХИЙ ЖУРНАЛ (shadow) · «тижнева карта монет» (TSM). Нічого не надсилає і не відкриває: раз на тиждень записує гіпотетичний кошик і результат попереднього тижня в таблицю tsm_shadow_week.
Згода власниці 23.11.2026 («Мовчки записує»). Ідея — ЗОВНІШНЄ (часовий імпульс), реалізація наша (ГІПОТЕЗА), як у бектесті csm.py (журнал, розділи X, Y), варіант L=30, H=7, топ-20 за обсягом, ваги обернено мінливості:
 щопонеділка (00:00 UTC, за закриттям неділі): для 20 найліквідніших монет (середній денний обсяг у $ за 30 днів) напрям = знак зміни ціни за 30 днів; вага ∝ 1/мінливість за 60 днів; сума модулів ваг = 1 (капітал $5 000 = валова позиція 1×).
 Результат тижня = Σ вага·зміна ціни за тиждень − 0,06% за кожну зміну ваги. Стопів і цілей немає.
Історія 2022–2026 (топ-20): ≈ +30…33% на рік, просадка до −43%. Вимкнути: TSM_SHADOW=0."""
from __future__ import annotations

import json
import os
import time
from typing import Callable, Dict, List, Optional

import numpy as np

L, VOLN, TOPN, FEE1, CAP = 30, 60, 20, 0.0006, 5000.0
WEEK = 604800; MON0 = 345600                      # 1970-01-05 00:00 UTC — понеділок
RETRY_S = 1800; _LAST_TRY = 0.0
DDL = """CREATE TABLE IF NOT EXISTS tsm_shadow_week (
    week_ts DOUBLE PRECISION PRIMARY KEY, created_ts DOUBLE PRECISION NOT NULL, weights_json TEXT NOT NULL, prices_json TEXT NOT NULL,
    ret_prev DOUBLE PRECISION, cost DOUBLE PRECISION, usd_prev DOUBLE PRECISION, n_long INTEGER, n_short INTEGER)"""


def enabled() -> bool:
    return os.getenv("TSM_SHADOW", "1").strip().lower() in ("1", "true", "yes", "on")


def universe() -> tuple:
    from office_td import swing
    return tuple(swing.SYMBOLS[:12]) + tuple(swing.EXTRA_CRYPTO)       # лише крипто (як у бектесті), без металів/нафти/акцій


def weights(data: Dict[str, Dict[str, np.ndarray]]) -> Dict[str, float]:
    """data[sym] = {'c': закриття днів, 'v': обсяг у монетах}; повертає ваги зі знаком (сума модулів = 1) для топ-20 за обсягом."""
    liq = {s: float(np.mean(d["c"][-30:] * d["v"][-30:])) for s, d in data.items() if len(d["c"]) >= VOLN + 2}
    top = sorted(liq, key=liq.get, reverse=True)[:TOPN]; raw = {}
    for s in top:
        c = data[s]["c"]; mom = c[-1] / c[-1 - L] - 1; sd = float(np.std(np.diff(c[-VOLN - 1:]) / c[-VOLN - 1:-1], ddof=1))
        if mom != 0 and sd > 0: raw[s] = (1.0 if mom > 0 else -1.0) / sd
    tot = sum(abs(x) for x in raw.values())
    return {s: x / tot for s, x in raw.items()} if len(raw) >= 5 and tot > 0 else {}


def cycle(db: str, fetch: Callable, now: Optional[float] = None) -> Optional[Dict[str, float]]:
    """Викликається з фонового потоку; працює раз на тиждень (або одразу, якщо запису за поточний тиждень ще немає). Повертає запис тижня або None."""
    global _LAST_TRY
    if not enabled(): return None
    now = time.time() if now is None else now
    wk = float((now - MON0) // WEEK * WEEK + MON0)
    if now - wk < 600 or now - _LAST_TRY < RETRY_S: return None
    from office_bridge import _execute, _fetchone
    _execute(db, DDL, ())
    if _fetchone(db, "SELECT 1 FROM tsm_shadow_week WHERE week_ts = ?", (wk,)): _LAST_TRY = now; return None
    _LAST_TRY = now; data: Dict[str, Dict[str, np.ndarray]] = {}
    prev = _fetchone(db, "SELECT weights_json, prices_json FROM tsm_shadow_week WHERE week_ts < ? ORDER BY week_ts DESC LIMIT 1", (wk,))
    pw: Dict[str, float] = json.loads(prev[0]) if prev else {}; pp: Dict[str, float] = json.loads(prev[1]) if prev else {}
    for s in dict.fromkeys(list(universe()) + list(pw)):
        try:
            rows = fetch(s, "1d", 100, closed_only=True)
            if isinstance(rows, list) and len(rows) >= VOLN + 2:
                data[s] = {"c": np.array([float(r["close"]) for r in rows]), "v": np.array([float(r.get("volume") or 0.0) for r in rows])}
        except Exception:  # noqa: BLE001
            continue
    if len(data) < 25 or any(s not in data for s in pw): print(f"[tsm-shadow] даних замало ({len(data)} монет) — повтор пізніше", flush=True); return None
    w = weights(data)
    if not w: return None
    px = {s: float(d["c"][-1]) for s, d in data.items()}
    ret = sum(pw[s] * (px[s] / pp[s] - 1) for s in pw if pp.get(s)) if pw else None
    cost = sum(abs(w.get(s, 0.0) - pw.get(s, 0.0)) for s in set(w) | set(pw)) * FEE1
    usd = CAP * (ret - cost) if ret is not None else None
    nl = sum(1 for x in w.values() if x > 0); ns = len(w) - nl
    _execute(db, "INSERT INTO tsm_shadow_week(week_ts, created_ts, weights_json, prices_json, ret_prev, cost, usd_prev, n_long, n_short) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
             (wk, now, json.dumps(w), json.dumps({s: px[s] for s in w}), ret, cost, usd, nl, ns))
    print(f"[tsm-shadow] тиждень {time.strftime('%Y-%m-%d', time.gmtime(wk))}: купівля {nl}, продаж {ns}; минулий тиждень {'—' if usd is None else f'{usd:+.0f}$'} (тихий журнал, без повідомлень)", flush=True)
    return {"week_ts": wk, "n_long": nl, "n_short": ns, "usd_prev": usd}

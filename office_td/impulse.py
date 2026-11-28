"""«ПРОБІЙ» (IM) — четвертий вид сигналу: пробій 10-денного рівня ривком на годинному графіку. Ордерів не відкриває.
Джерело: журнал CB, CC (tvh_lab / impulse_lab; 72 монети, 2020–2026: +$2,46 на угоду при ризику $10, просадка −$316). Числа — ГІПОТЕЗА (наша автоматизація), правило зафіксоване до підтвердної перевірки.
ПРАВИЛО (без змін проти перевірки): бари H1; рівень = максимум (мінімум) за попередні 240 год; останній закритий бар ЗАКРИВСЯ за рівнем; рівню ≥ 12 год;
  за попередні 24 год пробою цього боку не було; рух за останні 6 год у бік пробою ≥ 4 ATR(14); вхід = ціна закриття; стоп = екстремум останніх 3 барів ∓ 0,1 ATR
  (лише якщо стоп 0,3%…5% ціни); ціль 2R; утримання до 72 год.
Режими: IMP_LIVE=1 — сигнал у спільну таблицю (картка в Telegram, супровід як у ВІДСКОКУ); інакше — лише тихий запис sw_shadow (kind=IMP). Вимкнути все: IMP=0.
Рішення власниці 28.11.2026: «пробій теж має приходити»; картку показано перед увімкненням."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

PER = 3600; LB = 240; SPEED = 4.0; TP_R = 2.0; HOLD = 72; FEE = 0.001
_LAST = 0


def enabled() -> bool:
    return os.getenv("IMP", "1").strip().lower() in ("1", "true", "yes", "on")


def live_enabled() -> bool:
    return os.getenv("IMP_LIVE", "0").strip().lower() in ("1", "true", "yes", "on")


def detect(b: Dict[str, np.ndarray]) -> Optional[Dict[str, Any]]:
    """Сигнал на ОСТАННЬОМУ закритому барі або None. b: t, h, l, c (H1, за зростанням часу)."""
    h, l, c = b["h"], b["l"], b["c"]; n = len(c)
    if n < LB + 40: return None
    pc = np.r_[c[0], c[:-1]]; A = pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy(); i = n - 1
    if not A[i] > 0: return None
    for side in (1, -1):
        H, L, C = (h, l, c) if side > 0 else (-l, -h, -c)
        lvl = pd.Series(H).rolling(LB).max().shift(1).to_numpy()
        if not (lvl[i] == lvl[i] and C[i] > lvl[i]): continue
        if any(lvl[j] == lvl[j] and C[j] > lvl[j] for j in range(i - 24, i)): continue          # за останні 24 год уже був пробій
        set_i = i - 1
        while set_i > i - LB and lvl[set_i] == lvl[i]: set_i -= 1
        if i - set_i < 12: continue                                                             # рівню менше 12 год
        sp = (C[i] - C[i - 6]) / A[i]
        if sp < SPEED: continue
        e = float(c[i]); slT = L[i - 2:i + 1].min() - 0.1 * A[i]; sl = float(slT if side > 0 else -slT); rp = abs(e - sl) / e
        if not (0.003 <= rp <= 0.05) or (e - sl) * side <= 0: continue
        return {"side": side, "entry": e, "sl": sl, "tp": e + side * TP_R * abs(e - sl), "speed": float(sp), "level": float(lvl[i] if side > 0 else -lvl[i]), "stop_pct": 100 * rp, "bar_ts": float(b["t"][i])}
    return None


def signal(db: str, sym: str, d: Dict[str, Any], now: float) -> Optional[str]:
    from office_bridge import _execute, _fetchone
    from office_br import store
    store.init(db); direction = "LONG" if d["side"] > 0 else "SHORT"; te = d["bar_ts"] + PER; sid = f"IM|{sym}|{direction}|{int(te)}"
    if _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id = ?", (sid,)) or _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id LIKE 'IM|%' AND symbol = ? AND status IN ('NEW', 'SENT') LIMIT 1", (sym,)): return None
    nxt = _fetchone(db, "SELECT COALESCE(MAX(seq), 0) + 1 FROM br_test_signal WHERE sig_id LIKE 'IM|%'"); seq = int(nxt[0]) if nxt else 1
    hyp = {"strategy": "IMPULSE", "tf_s": 900, "hold": "до 3 діб", "speed_atr": round(d["speed"], 1),
           "why": f"ціна ривком пробила {'максимум' if d['side'] > 0 else 'мінімум'} за 10 діб і закрилась за ним",
           "note": "На історії 5 з 10 у плюс; виграш удвічі більший за стоп"}
    _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
             (sid, seq, sym, direction, d["level"], d["bar_ts"], te, te - 900, d["entry"], d["sl"], json.dumps([{"p": d["tp"], "src": "IM"}]), json.dumps(hyp, ensure_ascii=False), now, "NEW"))
    print(f"[imp] СИГНАЛ {sid} №{seq} entry={d['entry']:.6g} sl={d['sl']:.6g} tp={d['tp']:.6g} швидкість={d['speed']:.1f} ATR", flush=True)
    return sid


def scan(db: str, fetch: Callable, now: Optional[float] = None, symbols: Optional[tuple] = None) -> List[str]:
    """Раз на годину після закриття H1-бару. Закриває завершені тихі записи IMP і додає нові (сигнал або тихий запис)."""
    if not enabled(): return []
    from office_bridge import _execute, _fetchall, _fetchone
    from office_td.shadow_wave import DDL
    from office_td import swing, shadow_bounce as sb
    now = time.time() if now is None else now; _execute(db, DDL, ())
    symbols = symbols or tuple(s for s in swing.SYMBOLS if s in ("BTCUSDT",) + swing.SYMBOLS[:12] + swing.EXTRA_CRYPTO) + sb.EXTRA_COINS
    te = float(int(now // PER) * PER); data = {}; made: List[str] = []
    for sym in symbols:
        try:
            b = sb._bars(fetch(sym, "1h", 400, closed_only=True))
            if b is None or b["t"][-1] + PER != te: continue
            data[sym] = b
        except Exception: continue
    for sid, sym, direction, bar_ts, e, sl, tp in _fetchall(db, "SELECT sid, symbol, direction, bar_ts, entry, sl, tp FROM sw_shadow WHERE kind = 'IMP' AND status = 'OPEN'", ()):
        b = data.get(sym)
        if b is None: continue
        s = 1 if direction == "LONG" else -1; risk = abs(e - sl); idx = [i for i in range(len(b["t"])) if b["t"][i] > bar_ts][:HOLD]; res = None
        for i in idx:
            if (b["l"][i] <= sl) if s > 0 else (b["h"][i] >= sl): res = ("SL", -1.0, sl, b["t"][i]); break
            if (b["h"][i] >= tp) if s > 0 else (b["l"][i] <= tp): res = ("TP", TP_R, tp, b["t"][i]); break
        if res is None and len(idx) >= HOLD: i = idx[-1]; res = ("TIME", s * (b["c"][i] - e) / risk, float(b["c"][i]), b["t"][i])
        if res: _execute(db, "UPDATE sw_shadow SET status = ?, r = ?, exit_px = ?, exit_ts = ? WHERE sid = ?", (res[0], float(res[1]) - FEE / (risk / e), float(res[2]), float(res[3]) + PER, sid))
    for sym, b in data.items():
        try:
            d = detect(b)
            if not d: continue
            direction = "LONG" if d["side"] > 0 else "SHORT"
            if live_enabled():
                s = signal(db, sym, d, now)
                if s: made.append(s)
            elif not _fetchone(db, "SELECT 1 FROM sw_shadow WHERE kind = 'IMP' AND symbol = ? AND status = 'OPEN' LIMIT 1", (sym,)):
                sid = f"IMP|{sym}|{direction}|{int(d['bar_ts'])}"
                _execute(db, "INSERT INTO sw_shadow(sid, kind, symbol, direction, bar_ts, entry, sl, tp, created_ts) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", (sid, "IMP", sym, direction, d["bar_ts"], d["entry"], d["sl"], d["tp"], now))
                print(f"[imp-shadow] {sid} entry={d['entry']:.6g} sl={d['sl']:.6g} tp={d['tp']:.6g} (тихий запис)", flush=True); made.append(sid)
        except Exception as exc:  # noqa: BLE001
            print(f"[imp] {sym}: {type(exc).__name__}: {exc}", flush=True)
    return made


def cycle(db: str, fetch: Callable, now: Optional[float] = None) -> None:
    global _LAST
    now = time.time() if now is None else now; k = int(now // PER)
    if enabled() and k > _LAST and now - k * PER >= 50: _LAST = k; scan(db, fetch, now)

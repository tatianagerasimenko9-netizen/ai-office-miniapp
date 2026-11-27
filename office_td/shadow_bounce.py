"""ТИХИЙ ЖУРНАЛ (shadow) · «відскок після зливу» (BNC). Нічого не надсилає і не відкриває: лише записує гіпотетичні LONG-угоди в sw_shadow.
Згода власниці 27.11.2026 («так, у журнал»). Правила — як у перевірці bounce_lab.py (журнал, розділи BE і BG; ідеї власниці/ЗОВНІШНЄ, числа — ГІПОТЕЗА), годинні закриті бари:
  ЗЛИВ: мінімум бару — найнижчий за 72 бари, а падіння від максимуму останніх 24 барів ≥ 3 ATR(14).
  ПОВЕРНЕННЯ: протягом 6 наступних барів бар закрився вище максимуму бару зливу (мінімум зливу не оновлено) → вхід на закритті.
  Стоп: мінімум зливу − 0,1 ATR. Ціль 3R. Утримання ≤ 48 барів. SL-першим. Комісія 0,10%.
Записуємо лише коли разом виконано: B «весь ринок» (≥50% монет зробили свій злив за останні 6 год), L «денний рівень» (проколото денний свінг-мінімум останніх 90 діб, вхід уже вище),
T «біткоїн підтвердив» (BTC дав своє ПОВЕРНЕННЯ за останні 6 год). kind = BNC_U, якщо вчорашнє денне закриття BTC вище середньої за 200 діб (єдина комбінація, плюсова в трьох періодах), інакше BNC_N (для порівняння).
ДОДАНО 27.11.2026 (журнал BH, BK, BJ; рішення власниці «хочу такий сигнал, і щоб записувався в тихий журнал; заходити чи ні — вирішую сама»): при ПОВЕРНЕННІ, коли BTC підтвердив,
  рахуємо K (тести того ж дна за 7 діб, ±1 ATR) і падіння від 7-денного максимуму: падіння >20% і K≥1 → сигнал «ВІДСКОК» (BN|…, картка з позначкою «на перевірці»; вимкнути BNC_LIVE=0) + запис BNC_S3 (K≥2, сильний) або BNC_S2 (K=1, добрий);
  K≥1 і 10–20% (слабкий) → лише тихо BNC_W. Ордерів немає.
Відмінність від перевірки: ширина рахується по 42 крипто-монетах Офісу (у перевірці — 72). Вимкнути: BNC_SHADOW=0."""
from __future__ import annotations

import os
import time
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

LB = 72; D24 = 24; WAIT = 6; HOLD = 48; PER = 3600; FEE = 0.001; KA = 3.0; TP_R = 3.0
_LAST = 0


def enabled() -> bool:
    return os.getenv("BNC_SHADOW", "1").strip().lower() in ("1", "true", "yes", "on")


def _bars(rows) -> Optional[Dict[str, np.ndarray]]:
    from office_td.swing import _epoch
    if not isinstance(rows, list) or len(rows) < 200: return None
    g = lambda k: np.array([float(x[k]) for x in rows])
    return {"t": np.array([_epoch(x) for x in rows]), "h": g("high"), "l": g("low"), "c": g("close")}


def _atr(b) -> np.ndarray:
    h, l, c = b["h"], b["l"], b["c"]; pc = np.r_[c[0], c[:-1]]
    return pd.Series(np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))).rolling(14).mean().to_numpy()


def flushes(b) -> np.ndarray:
    """Індекси барів-«зливів»."""
    h, l = b["h"], b["l"]; A = _atr(b)
    lo = pd.Series(l).rolling(LB).min().to_numpy(); hi = pd.Series(h).rolling(D24).max().to_numpy()
    return np.flatnonzero((l == lo) & (hi - l >= KA * A))


def entry_at(b, j: int, fl: Optional[np.ndarray] = None) -> Optional[Tuple[int, float, float]]:
    """Чи є бар j баром ПОВЕРНЕННЯ. Повертає (індекс зливу, вхід, стоп) або None."""
    h, l, c = b["h"], b["l"], b["c"]; fl = flushes(b) if fl is None else fl; A = _atr(b)
    for f in fl[(fl >= j - WAIT) & (fl < j)][::-1]:
        ok = True
        for q in range(f + 1, j + 1):
            if l[q] < l[f]: ok = False; break                 # дно оновлено — інший злив
            if c[q] > h[f]: ok = (q == j); break              # перше закриття вище — це і є вхід
        else: ok = False
        if ok and A[j] > 0:
            e = float(c[j]); sl = float(l[f] - 0.1 * A[j])
            if 0.0005 <= (e - sl) / e <= 0.25: return int(f), e, sl
    return None


def level_ok(daily, t_flush: float, low_flush: float, entry: float, now: float) -> bool:
    """L: злив проколов денний свінг-мінімум (3 доби з обох боків; видимий через 4 доби; не старіший за 90 діб), вхід уже вище нього."""
    dt, dl = daily["t"], daily["l"]
    for i in range(3, len(dl) - 3):
        if dl[i] == dl[i - 3:i + 4].min() and now - 90 * 86400 <= dt[i] + 4 * 86400 <= t_flush and low_flush < dl[i] < entry: return True
    return False


def live_enabled() -> bool:
    return os.getenv("BNC_LIVE", "1").strip().lower() in ("1", "true", "yes", "on")


def depth(b, f: int) -> Tuple[int, float]:
    """(скільки попередніх зливів за 7 діб, не ближче 12 год, мали дно в межах ±1 ATR від цього; падіння від 7-денного максимуму, %). Як у bounce_feat.py (ознаки K і F)."""
    fl = flushes(b); A = _atr(b); pf = fl[(fl >= f - 168) & (fl <= f - 12)]
    k = int(sum(abs(b["l"][q] - b["l"][f]) <= A[f] for q in pf)); hi = float(b["h"][max(0, f - 167):f + 1].max())
    return k, 100.0 * (hi - float(b["l"][f])) / hi


def _deep(db: str, sym: str, b, f: int, e: float, sl: float, now: float) -> List[str]:
    """СИЛЬНИЙ (дно ≥2 тестів, падіння >20%) → сигнал «ВІДСКОК» власниці (BN|…, якщо BNC_LIVE) і запис BNC_S3; дно 1 тест + >20% → тихо BNC_S2; дно ≥1 тесту + 10–20% → тихо BNC_W. BTC уже підтвердив."""
    from office_bridge import _execute, _fetchone
    k, drop = depth(b, f)
    if k < 1 or drop < 10: return []
    kind = "BNC_S3" if (k >= 2 and drop > 20) else ("BNC_S2" if drop > 20 else "BNC_W"); tp = e + TP_R * (e - sl); bar = float(b["t"][-1]); out = []
    if not _fetchone(db, "SELECT 1 FROM sw_shadow WHERE kind = ? AND symbol = ? AND status = 'OPEN' LIMIT 1", (kind, sym)):
        sid = f"{kind}|{sym}|LONG|{int(bar)}"
        _execute(db, "INSERT INTO sw_shadow(sid, kind, symbol, direction, bar_ts, entry, sl, tp, created_ts) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", (sid, kind, sym, "LONG", bar, e, sl, tp, now))
        print(f"[bnc-shadow] {sid} entry={e:.6g} sl={sl:.6g} tp={tp:.6g} тестів дна={k} падіння={drop:.1f}% (тихий журнал)", flush=True); out.append(sid)
    if kind in ("BNC_S3", "BNC_S2") and live_enabled():          # сильні (2+ тести дна) і добрі (1 тест) — власниці; слабкі (падіння 10–20%) — лише тихо (її рішення 27.11.2026)
        sid = signal(db, sym, b, f, e, sl, tp, k, drop, now)
        if sid: out.append(sid)
    return out


def signal(db: str, sym: str, b, f: int, e: float, sl: float, tp: float, k: int, drop: float, now: float) -> Optional[str]:
    """Сигнал «ВІДСКОК» у спільну таблицю сигналів: доставляє і супроводжує наявний контур (як ІНТРАДЕЙ). Ордерів не відкриває. Текст картки погоджено власницею 27.11.2026."""
    import json
    from office_bridge import _execute, _fetchone
    from office_br import store
    store.init(db); te = float(b["t"][-1]) + PER; sid = f"BN|{sym}|LONG|{int(te)}"
    if _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id = ?", (sid,)) or _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id LIKE 'BN|%' AND symbol = ? AND status IN ('NEW', 'SENT') LIMIT 1", (sym,)): return None
    nxt = _fetchone(db, "SELECT COALESCE(MAX(seq), 0) + 1 FROM br_test_signal WHERE sig_id LIKE 'BN|%'"); seq = int(nxt[0]) if nxt else 1
    word = "раз" if k == 1 else "двічі" if k == 2 else f"{k} рази" if k in (3, 4) else f"{k} разів"
    hyp = {"strategy": "BOUNCE", "tf_s": 900, "hold": "до 2 діб", "tests": k, "drop_pct": round(drop, 1),
           "why": f"дно тестували {word}, і воно встояло · падіння {drop:.0f}% за тиждень · біткоїн розвернувся".replace(".", ","),
           "note": "На історії " + ("5 з 10 у плюс" if k >= 2 else "4–5 з 10 у плюс")}
    sw = _fetchone(db, "SELECT seq, msg_id FROM br_test_signal WHERE sig_id LIKE 'SW|%' AND symbol = ? AND direction = 'SHORT' AND status = 'SENT' ORDER BY created_ts DESC LIMIT 1", (sym,))
    if sw:
        hyp["opp"] = f"Шорт СВІНГ №{int(sw[0])} по {sym.replace('USDT', '')} не закривати — у нього свій стоп"
        if sw[1]: hyp["links"] = {f"СВІНГ №{int(sw[0])}": int(sw[1])}
    _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
             (sid, seq, sym, "LONG", float(b["l"][f]), float(b["t"][f]), te, te - 900, e, sl, json.dumps([{"p": tp, "src": "BN"}]), json.dumps(hyp, ensure_ascii=False), now, "NEW"))
    print(f"[bnc] СИГНАЛ {sid} №{seq} entry={e:.6g} sl={sl:.6g} tp={tp:.6g} тестів={k} падіння={drop:.1f}%", flush=True)
    return sid


def scan(db: str, fetch: Callable, now: Optional[float] = None, symbols: Optional[tuple] = None) -> List[str]:
    """Раз на годину після закриття H1-бару: закрити завершені записи BNC_* і додати нові. Повідомлень немає."""
    if not enabled(): return []
    from office_bridge import _execute, _fetchall, _fetchone
    from office_td.shadow_wave import DDL
    from office_td import swing
    now = time.time() if now is None else now; _execute(db, DDL, ())
    symbols = symbols or tuple(s for s in swing.SYMBOLS if s in ("BTCUSDT",) + swing.SYMBOLS[:12] + swing.EXTRA_CRYPTO)
    te = float(int(now // PER) * PER); data = {}; cand = {}; tot = hit = 0; btc_ret = False
    for sym in symbols:
        try:
            b = _bars(fetch(sym, "1h", 400, closed_only=True))
            if b is None or b["t"][-1] + PER != te: continue
        except Exception: continue
        data[sym] = b; fl = flushes(b); n = len(b["c"]); tot += 1
        hit += int(len(fl) > 0 and fl[-1] >= n - 1 - WAIT)                      # злив за останні 6 год (включно з останнім баром)
        en = entry_at(b, n - 1, fl)
        if en: cand[sym] = en
        if sym == "BTCUSDT": btc_ret = any(entry_at(b, j, fl) for j in range(n - WAIT, n))
    # закриття відкритих записів
    for sid, sym, bar_ts, e, sl, tp in _fetchall(db, "SELECT sid, symbol, bar_ts, entry, sl, tp FROM sw_shadow WHERE kind LIKE 'BNC_%' AND status = 'OPEN'", ()):
        b = data.get(sym)
        if b is None: continue
        risk = e - sl; idx = [i for i in range(len(b["t"])) if b["t"][i] > bar_ts][:HOLD]; res = None
        for i in idx:
            if b["l"][i] <= sl: res = ("SL", -1.0, sl, b["t"][i]); break
            if b["h"][i] >= tp: res = ("TP", TP_R, tp, b["t"][i]); break
        if res is None and len(idx) >= HOLD: i = idx[-1]; res = ("TIME", (b["c"][i] - e) / risk, float(b["c"][i]), b["t"][i])
        if res: _execute(db, "UPDATE sw_shadow SET status = ?, r = ?, exit_px = ?, exit_ts = ? WHERE sid = ?", (res[0], float(res[1]) - FEE / (risk / e), float(res[2]), float(res[3]) + PER, sid))
    made: List[str] = []
    if cand and btc_ret:                                                         # знайдена закономірність (журнал BH/BK): глибокий злив + повторний тест дна + BTC розвернувся
        for sym, (f, e, sl) in cand.items():
            try: made += _deep(db, sym, data[sym], f, e, sl, now)
            except Exception as exc:  # noqa: BLE001
                print(f"[bnc] {sym}: {type(exc).__name__}: {exc}", flush=True)
    if not cand or tot < 10 or hit / tot < 0.5 or not btc_ret: return made      # B і T
    try:
        d = _bars(fetch("BTCUSDT", "1d", 260, closed_only=True)); up = bool(d is not None and len(d["c"]) >= 200 and d["c"][-1] > d["c"][-200:].mean())
    except Exception: return made
    if d is None or len(d["c"]) < 200: return made
    kind = "BNC_U" if up else "BNC_N"
    for sym, (f, e, sl) in cand.items():
        try:
            b = data[sym]; dd = _bars(fetch(sym, "1d", 120, closed_only=True)) if sym != "BTCUSDT" else d
            if dd is None or not level_ok(dd, float(b["t"][f]), float(b["l"][f]), e, now): continue
            if _fetchone(db, "SELECT 1 FROM sw_shadow WHERE kind LIKE 'BNC_%' AND symbol = ? AND status = 'OPEN' LIMIT 1", (sym,)): continue
            tp = e + TP_R * (e - sl); sid = f"{kind}|{sym}|LONG|{int(b['t'][-1])}"
            _execute(db, "INSERT INTO sw_shadow(sid, kind, symbol, direction, bar_ts, entry, sl, tp, created_ts) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", (sid, kind, sym, "LONG", float(b["t"][-1]), e, sl, tp, now))
            print(f"[bnc-shadow] {sid} entry={e:.6g} sl={sl:.6g} tp={tp:.6g} ширина={hit}/{tot} (тихий журнал, без повідомлень)", flush=True); made.append(sid)
        except Exception as exc:  # noqa: BLE001
            print(f"[bnc-shadow] {sym}: {type(exc).__name__}: {exc}", flush=True)
    return made


def cycle(db: str, fetch: Callable, now: Optional[float] = None) -> None:
    global _LAST
    now = time.time() if now is None else now; k = int(now // PER)
    if enabled() and k > _LAST and now - k * PER >= 40: _LAST = k; scan(db, fetch, now)

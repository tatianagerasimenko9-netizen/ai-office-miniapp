"""TD-V1 · ТЕСТ (гіпотеза): живі сигнали за стратегією «зверху вниз». Лише спостереження: ордерів немає.
Крок 1 (раз на годину, H1): модель оцінює 12 монет × 2 напрями; оцінка >= порога -> кандидат.
Крок 2 (щохвилини, M15): до 4 год чекаємо підтвердження (закриття за екстремумом попередньої свічки у бік угоди); тоді SL за структурою M15, ціль із плану H1.
Сигнал пишеться в br_test_signal з sig_id 'TD|…' і доставляється/супроводжується існуючим контуром B&R (картка позначена «ТЕСТ»).
Вимкнути: TD_LIVE=0."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from office_td import features as F
from office_td import levels as LV
from office_td.model import Model, _DEFAULT as MODEL_PATH

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "BNBUSDT", "LTCUSDT", "DOTUSDT", "ATOMUSDT")
# Золото, срібло, нафта (WTI, Brent), газ: додано за вимогою власниці як ТЕСТ без ордерів. Історія (2024-2026, комісія 0,10%): газ +$38, нафта WTI −$120, срібло −$130, золото −$134, Brent −$144.
# NVDA, SPCX (акції-перпи Binance) додано за вимогою власниці; на історії НЕ перевірені (немає даних у тесті).
COMMODITIES = ("XAUUSDT", "XAGUSDT", "CLUSDT", "BZUSDT", "NATGASUSDT", "NVDAUSDT", "SPCXUSDT")
if os.getenv("TD_COMMODITIES", "1").strip().lower() in ("1", "true", "yes", "on"):
    SYMBOLS = SYMBOLS + COMMODITIES
H1_BARS = 1500                    # ≈62 доби: потрібні попередній місяць і 336-барові вікна
MIN_H1 = 800
DEDUPE_S = 12 * 3600
CONFIRM_BARS = 16                 # вікно підтвердження M15: 4 год
MIN_SP15, MAX_SP15 = 0.0015, 0.03
STRATEGY = "TD_V1_TEST"

DDL = """CREATE TABLE IF NOT EXISTS td_candidate (
    cand_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, h1_ts DOUBLE PRECISION NOT NULL, h1_close_ts DOUBLE PRECISION NOT NULL,
    h1_entry DOUBLE PRECISION NOT NULL, h1_sl DOUBLE PRECISION NOT NULL, tp DOUBLE PRECISION NOT NULL, score DOUBLE PRECISION NOT NULL,
    feats_json TEXT, status TEXT NOT NULL, note TEXT, created_ts DOUBLE PRECISION NOT NULL, done_ts DOUBLE PRECISION)"""

_MODEL: Optional[Model] = None
_LAST_H1 = 0


def enabled() -> bool:
    return os.getenv("TD_LIVE", "1").strip().lower() in ("1", "true", "yes", "on")


def model() -> Model:
    global _MODEL
    if _MODEL is None:
        _MODEL = Model.load()
    return _MODEL


def init(db: str) -> None:
    from office_bridge import _execute
    _execute(db, DDL)


def _epoch(row: dict) -> float:
    return datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).timestamp()


def _arrays(rows: List[dict]):
    t = np.array([_epoch(x) for x in rows]); a = lambda k: np.array([float(x[k]) for x in rows])
    return t, a("open"), a("high"), a("low"), a("close"), a("volume")


def _btc_ctx(bt: np.ndarray, bc: np.ndarray, t: np.ndarray):
    r4 = np.r_[np.full(4, np.nan), (bc[4:] - bc[:-4]) / bc[:-4]]; r24 = np.r_[np.full(24, np.nan), (bc[24:] - bc[:-24]) / bc[:-24]]
    pos = {float(x): i for i, x in enumerate(bt)}
    ix = np.array([pos.get(float(x), -1) for x in t])
    return np.where(ix >= 0, r4[np.maximum(ix, 0)], np.nan), np.where(ix >= 0, r24[np.maximum(ix, 0)], np.nan)


def score_symbol(sym: str, bars: List[dict], btc_bars: List[dict], m: Model) -> List[Dict[str, Any]]:
    """Оцінки двох напрямів для ОСТАННЬОГО закритого H1-бара. Повертає список {direction, score, feats, ent, sl, sp, h1_ts}."""
    t, o, h, l, c, v = _arrays(bars)
    if len(t) < MIN_H1: return []
    bt, _, _, _, bc, _ = _arrays(btc_bars)
    b4, b24 = _btc_ctx(bt, bc, t)
    B = F.compute(t, o, h, l, c, v, b4, b24); i = len(t) - 1; out = []
    if not np.isfinite(B["atr"][i]): return []
    for s in (1, -1):
        f, ent, sl, sp = F.side_features(B, [i], s)
        if not (F.MIN_SP <= float(sp[0]) <= F.MAX_SP): continue
        x = [float(f[k][0]) for k in m.features]
        sc = m.predict_row(x)
        out.append(dict(direction="LONG" if s > 0 else "SHORT", score=float(sc), feats={k: float(f[k][0]) for k in f}, ent=float(ent[0]), sl=float(sl[0]), sp=float(sp[0]), h1_ts=float(t[i]), side=s))
    return out


def scan_h1(db: str, fetch: Callable, now: Optional[float] = None, m: Optional[Model] = None, symbols: tuple = SYMBOLS) -> int:
    """Створює кандидатів (PENDING). Дедуплікація: ≤1 кандидат на монету й напрям за 12 год."""
    from office_bridge import _execute, _fetchone
    init(db); now = time.time() if now is None else now; m = m or model(); created = 0
    btc = fetch("BTCUSDT", "1h", H1_BARS, closed_only=True)
    if not isinstance(btc, list) or len(btc) < MIN_H1: return -1      # дані недоступні: повторимо в цю ж годину
    for sym in symbols:
        try:
            bars = btc if sym == "BTCUSDT" else fetch(sym, "1h", H1_BARS, closed_only=True)
            if not isinstance(bars, list) or len(bars) < MIN_H1: continue
            last_open = _epoch(bars[-1])
            if last_open + 3600 > now or now - (last_open + 3600) > 1800: continue          # лише свіжозакритий бар
            for r in score_symbol(sym, bars, btc, m):
                if r["score"] < m.threshold: continue
                try:                                    # тиха позначка (лише запис): рівні зі свічок на момент кандидата
                    _t, _o, _h, _l, _c, _v = _arrays(bars)
                    r["feats"]["_lv"] = [round(x, 8) for x in LV.levels_from_h1(_t, _h, _l, r["h1_ts"] + 3600)]
                except Exception as exc_lv:  # noqa: BLE001
                    print(f"[td] рівні недоступні {sym}: {type(exc_lv).__name__}", flush=True)
                if _fetchone(db, "SELECT 1 FROM td_candidate WHERE symbol = ? AND direction = ? AND h1_ts > ? LIMIT 1", (sym, r["direction"], r["h1_ts"] - DEDUPE_S)): continue
                risk = abs(r["ent"] - r["sl"]); tp = r["ent"] + r["side"] * 3 * risk
                cid = f"TD|{sym}|{r['direction']}|{int(r['h1_ts'])}"
                _execute(db, "INSERT INTO td_candidate(cand_id, symbol, direction, h1_ts, h1_close_ts, h1_entry, h1_sl, tp, score, feats_json, status, created_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                         (cid, sym, r["direction"], r["h1_ts"], r["h1_ts"] + 3600, r["ent"], r["sl"], tp, r["score"], json.dumps(r["feats"]), "PENDING", now))
                created += 1
                print(f"[td] кандидат {cid} score={r['score']:.3f} thr={m.threshold:.3f}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[td] scan {sym}: {type(exc).__name__}: {exc}", flush=True)
    return created


def _atr15(h, l, c, j):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return float(np.mean(tr[j - 14:j])) if j >= 14 else float("nan")


def confirm_candidate(cand: dict, bars: List[dict], now: float) -> Dict[str, Any]:
    """Чиста логіка кроку 2. Повертає {'status': 'WAIT'|'EXPIRED'|'SKIPPED'|'CONFIRMED', ...}."""
    t, o, h, l, c, _ = _arrays(bars)
    side = 1 if cand["direction"] == "LONG" else -1
    i0 = int(np.searchsorted(t, float(cand["h1_close_ts"])))
    for k in range(CONFIRM_BARS):
        j = i0 + k
        if j >= len(t): return {"status": "WAIT"}
        if j < 9: continue
        conf = (c[j] > o[j] and c[j] > h[j - 1]) if side > 0 else (c[j] < o[j] and c[j] < l[j - 1])
        if not conf: continue
        at = _atr15(h, l, c, j)
        if not np.isfinite(at): return {"status": "SKIPPED", "note": "ATR M15 недоступний"}
        ext = float(l[j - 7:j + 1].min()) if side > 0 else float(h[j - 7:j + 1].max())
        sl = ext - side * 0.1 * at; ent = float(c[j]); sp = abs(ent - sl) / ent; tp = float(cand["tp"])
        if (ent - sl) * side <= 0 or not (MIN_SP15 <= sp <= MAX_SP15): return {"status": "SKIPPED", "note": f"стоп {sp*100:.2f}% поза межами"}
        if (tp - ent) * side <= 0 or (tp - ent) * side < abs(ent - sl): return {"status": "SKIPPED", "note": "ціль не далі за стоп"}
        if now - (float(t[j]) + 900) > 240: return {"status": "EXPIRED", "note": "підтвердження застаріло (не відправляємо)"}
        return {"status": "CONFIRMED", "confirm_ts": float(t[j]), "entry": ent, "sl": float(sl), "tp": tp, "sp": sp, "k": k}
    return {"status": "EXPIRED", "note": "підтвердження за 4 год не було"}


def record_signal(db: str, cand: dict, res: dict, now: float, thr: Optional[float] = None) -> Optional[str]:
    from office_bridge import _execute, _fetchone
    sid = f"TD|{cand['symbol']}|{cand['direction']}|{int(res['confirm_ts'])}"
    if _fetchone(db, "SELECT 1 FROM br_test_signal WHERE sig_id = ?", (sid,)): return None
    nxt = _fetchone(db, "SELECT COALESCE(MAX(seq), 0) + 1 FROM br_test_signal WHERE sig_id LIKE 'TD|%'"); seq = int(nxt[0]) if nxt else 1
    feats = json.loads(cand["feats_json"]) if cand.get("feats_json") else {}
    try:
        lv = feats.get("_lv"); stop_tag = LV.stop_tag(lv, 1 if cand["direction"] == "LONG" else -1, res["entry"], res["sl"]) if lv else None
    except Exception:  # noqa: BLE001
        stop_tag = None
    try:
        from office_bridge import _fetchall
        others = _fetchall(db, "SELECT symbol FROM td_candidate WHERE h1_ts = ? AND direction = ? AND cand_id != ? ORDER BY symbol", (cand["h1_ts"], cand["direction"], cand["cand_id"] if cand.get("cand_id") else f"TD|{cand['symbol']}|{cand['direction']}|{int(cand['h1_ts'])}"))
        cluster = {"n": len(others), "syms": [str(r[0]).replace("USDT", "") for r in others][:8]}
    except Exception:  # noqa: BLE001
        cluster = None
    hyp = {"strategy": STRATEGY, "stop_tag": stop_tag, "cluster": cluster, "model": "TD_V1", "score": cand["score"], "threshold": thr if thr is not None else model().threshold, "h1_entry": cand["h1_entry"], "h1_sl": cand["h1_sl"],
           "k_bars": res["k"], "feats": {k: feats.get(k) for k in ("W_ahead", "W_behind", "H4_ahead", "H4_behind", "D_ahead", "D_behind", "pos72", "pos168", "fib_ret", "W_swept", "H4_swept", "D_swept", "touch_tot")}}
    _execute(db, "INSERT INTO br_test_signal(sig_id, seq, symbol, direction, level, break_ts, retest_ts, confirm_ts, entry, sl, targets_json, hyp_json, created_ts, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
             (sid, seq, cand["symbol"], cand["direction"], cand["h1_entry"], cand["h1_ts"], cand["h1_close_ts"], res["confirm_ts"], res["entry"], res["sl"],
              json.dumps([{"p": res["tp"], "src": "TD"}]), json.dumps(hyp, default=str), now, "NEW"))
    return sid


def confirm_all(db: str, fetch: Callable, now: Optional[float] = None, m: Optional[Model] = None) -> int:
    from office_bridge import _execute, _fetchall
    init(db); now = time.time() if now is None else now; n = 0
    cols = "cand_id, symbol, direction, h1_ts, h1_close_ts, h1_entry, h1_sl, tp, score, feats_json"
    for r in _fetchall(db, f"SELECT {cols} FROM td_candidate WHERE status = 'PENDING' ORDER BY h1_ts", ()):
        cand = dict(zip(cols.replace(" ", "").split(","), r))
        if now > float(cand["h1_close_ts"]) + 6 * 3600:
            _execute(db, "UPDATE td_candidate SET status = 'EXPIRED', note = 'час вичерпано', done_ts = ? WHERE cand_id = ?", (now, cand["cand_id"])); continue
        bars = fetch(cand["symbol"], "15m", 80, closed_only=True)
        if not isinstance(bars, list) or len(bars) < 30: continue
        res = confirm_candidate(cand, bars, now)
        if res["status"] == "WAIT": continue
        if res["status"] == "CONFIRMED":
            sid = record_signal(db, cand, res, now, (m.threshold if m is not None else None))
            _execute(db, "UPDATE td_candidate SET status = 'CONFIRMED', note = ?, done_ts = ? WHERE cand_id = ?", (sid, now, cand["cand_id"])); n += 1
            print(f"[td] СИГНАЛ {sid} entry={res['entry']} sl={res['sl']:.6g} tp={res['tp']:.6g}", flush=True)
        else:
            _execute(db, "UPDATE td_candidate SET status = ?, note = ?, done_ts = ? WHERE cand_id = ?", (res["status"], res.get("note"), now, cand["cand_id"]))
    return n


def cycle(db: str, fetch: Callable, now: Optional[float] = None) -> Dict[str, int]:
    """Один прохід (викликається з моніторингу B&R раз на хвилину). Блокуюча функція: запускати через asyncio.to_thread."""
    global _LAST_H1
    now = time.time() if now is None else now; out = {"candidates": 0, "signals": 0}
    h = int(now // 3600)
    if h > _LAST_H1 and now - h * 3600 >= 20:
        got = scan_h1(db, fetch, now)
        if got >= 0:
            out["candidates"] = got; _LAST_H1 = h
    out["signals"] = confirm_all(db, fetch, now)
    return out

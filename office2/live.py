"""Office 2.0 SHADOW LIVE — спостерігач 24/7. Нічого не надсилає користувачу, не торгує, не змінює рішень старого Лева.

Що робить (раз на закритий бар M15):
  1. Знімає СТАН ринку для кожної монети всесвіту (office2_shadow_state): ціна, ATR, режим H4/D1, відносна сила проти BTC/ETH,
     ширина ринку (частка монет вгору за 4 год/24 год), режим волатильності, найближчі рівні ліквідності. Усе — лише по закритих барах.
  2. Шукає кандидата Office2 (pipeline v0: sweep+reclaim) на щойно закритому барі. Рішення Office2 завжди OBSERVE (немає GATE) —
     кандидат пишеться як спостереження, а не як сигнал (office2_shadow_event, знімок незмінний).
  3. Бачить нові рішення старого Лева (SIGNAL_PLAN у office_events, читання) і пише подію OLD_LEV зі знімком стану Office2 на той самий момент.
  4. Через 48 год дорахує наслідок за 1m-свічками (office2_shadow_outcome): TP/SL-порядок, MFE/MAE, net R. Майбутнє потрапляє ЛИШЕ сюди.

Вимкнено за замовчуванням: OFFICE2_SHADOW=1 вмикає потік. Будь-яка помилка гаситься й логується; потік не торкається Telegram.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from office2 import features as F
from office2 import outcome as OUT
from office2 import pipeline as P
from office2 import risk as RK

VERSION = "o2-shadow-1"
SOURCE = "binance_fapi_klines"
DEFAULT_UNIVERSE = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT",
                    "NEARUSDT", "OPUSDT", "SUIUSDT", "UNIUSDT", "ETCUSDT", "FILUSDT", "HBARUSDT", "TIAUSDT", "SEIUSDT", "1000PEPEUSDT",
                    "1000SHIBUSDT", "FETUSDT", "RUNEUSDT", "ALGOUSDT", "MKRUSDT", "WLDUSDT", "ONDOUSDT", "JUPUSDT")
OBS_ONLY = "OBSERVE"            # Office2 не має GATE-компонентів: рішення завжди спостереження, не READY2
OUTCOME_AFTER_SEC = 48 * 3600
CYCLE_SEC = 900
KL_URL = "https://fapi.binance.com/fapi/v1/klines"
TF_SEC = {"15m": 900, "4h": 4 * 3600, "1d": 86400, "1w": 7 * 86400}
TF_TTL = {"15m": 0, "4h": 3600, "1d": 6 * 3600, "1w": 24 * 3600}   # як довго тримаємо завантажене до повторного запиту
TF_LIMIT = {"15m": 500, "4h": 300, "1d": 120, "1w": 40}
_LOCK = threading.Lock()
_STATS: Dict[str, Any] = {"cycles": 0, "states": 0, "events": 0, "old_lev": 0, "outcomes": 0, "errors": 0, "last_cycle": None, "last_error": None}

DDL = (
    """CREATE TABLE IF NOT EXISTS office2_shadow_state (
        ts_epoch BIGINT NOT NULL, symbol TEXT NOT NULL, version TEXT NOT NULL, payload_json TEXT NOT NULL,
        PRIMARY KEY (ts_epoch, symbol))""",
    """CREATE TABLE IF NOT EXISTS office2_shadow_event (
        event_id TEXT PRIMARY KEY, ts_epoch BIGINT NOT NULL, ts_utc TEXT NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL,
        direction TEXT, entry DOUBLE PRECISION, sl DOUBLE PRECISION, tp DOUBLE PRECISION, decision TEXT NOT NULL,
        version TEXT NOT NULL, source TEXT NOT NULL, snapshot_json TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS office2_shadow_outcome (
        event_id TEXT PRIMARY KEY, ts_resolved_epoch BIGINT NOT NULL, status TEXT NOT NULL, version TEXT NOT NULL, outcome_json TEXT NOT NULL)""",
)


def enabled() -> bool:
    return os.getenv("OFFICE2_SHADOW", "").strip().lower() in ("1", "true", "yes", "on")


def universe() -> List[str]:
    raw = os.getenv("OFFICE2_SHADOW_SYMBOLS", "").strip()
    return [s.strip().upper() for s in raw.split(",") if s.strip()] if raw else list(DEFAULT_UNIVERSE)


def stats() -> Dict[str, Any]:
    with _LOCK:
        return dict(_STATS)


def _bump(k: str, n: int = 1) -> None:
    with _LOCK:
        _STATS[k] = _STATS.get(k, 0) + n


def _log(msg: str) -> None:
    print(f"[o2shadow] {msg}", flush=True)


# ---------------------------------------------------------------- storage
def init_db(db: str) -> None:
    from office_bridge import _execute

    for ddl in DDL:
        _execute(db, ddl)


def _insert_ignore(db: str, table: str, cols: Tuple[str, ...], vals: tuple) -> None:
    from office_bridge import _execute

    q = f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) ON CONFLICT DO NOTHING"
    _execute(db, q, vals)


def _j(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, default=lambda x: None if (isinstance(x, float) and not math.isfinite(x)) else (float(x) if isinstance(x, np.floating) else int(x) if isinstance(x, np.integer) else str(x)))


def _clean(o: Any) -> Any:
    """NaN/inf → None, numpy → python (щоб JSON був валідним)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return v if math.isfinite(v) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# ---------------------------------------------------------------- дані
def _rows_to_arr(rows: list, drop_open_at: Optional[float] = None) -> Optional[Dict[str, np.ndarray]]:
    """Сирі klines Binance → масиви; незакритий (формується) бар відкидається: береться тільки те, що закрилось до drop_open_at."""
    out: List[List[float]] = []
    for r in rows or []:
        try:
            t = float(r[0]) / 1000.0
            tc = float(r[6]) / 1000.0
            if drop_open_at is not None and tc > drop_open_at:
                continue
            out.append([t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[9]) if len(r) > 9 else float("nan")])
        except (TypeError, ValueError, IndexError):
            continue
    if len(out) < 5:
        return None
    a = np.array(out, dtype=np.float64)
    return {"t": a[:, 0], "o": a[:, 1], "h": a[:, 2], "l": a[:, 3], "c": a[:, 4], "v": a[:, 5], "tbv": a[:, 6]}


class Feed:
    """Завантаження klines із паузами між запитами; HTF кешуються довше. Спільний ліміт/пауза Binance береться з office_market_data."""

    def __init__(self, getter: Optional[Callable[[str, Dict[str, Any]], Any]] = None, pause: float = 0.6):
        self._get = getter or self._default_get
        self.pause = pause
        self._cache: Dict[Tuple[str, str], Tuple[float, Any]] = {}
        self.requests = 0

    @staticmethod
    def _default_get(url: str, params: Dict[str, Any]) -> Any:
        import office_market_data as MD

        if MD.backoff_left() > 0:
            raise RuntimeError(f"backoff {MD.backoff_left():.0f}s")
        return MD._http_get_json(url, params)

    def klines(self, sym: str, tf: str, now: float, limit: Optional[int] = None, start_ms: Optional[int] = None) -> Optional[Dict[str, np.ndarray]]:
        key = (sym, tf)
        ttl = TF_TTL.get(tf, 0)
        hit = self._cache.get(key)
        if start_ms is None and hit and ttl and now - hit[0] < ttl:
            return hit[1]
        params: Dict[str, Any] = {"symbol": sym, "interval": tf, "limit": limit or TF_LIMIT.get(tf, 500)}
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        time.sleep(self.pause) if self.pause else None
        self.requests += 1
        rows = self._get(KL_URL, params)
        arr = _rows_to_arr(rows, drop_open_at=now)
        if start_ms is None and arr is not None:
            self._cache[key] = (now, arr)
        return arr


def build_ctx(feed: Feed, sym: str, now: float) -> Optional[Dict[str, Any]]:
    m15 = feed.klines(sym, "15m", now)
    h4 = feed.klines(sym, "4h", now)
    d1 = feed.klines(sym, "1d", now)
    w1 = feed.klines(sym, "1w", now)
    if not (m15 and h4 and d1 and w1) or len(m15["t"]) < 60 or len(h4["t"]) < 30 or len(d1["t"]) < 20:
        return None
    return {"m15": m15, "h4": h4, "d1": d1, "w1": w1, "atr15": F.atr(m15, 14), "reg4": F.regime_by_bar(h4), "regd": F.regime_by_bar(d1),
            "levels": F.build_levels(h4, d1, w1)}


# ---------------------------------------------------------------- ознаки стану (лише закриті бари; CONTEXT)
def _ret(bars: Dict[str, np.ndarray], n: int) -> Optional[float]:
    c = bars["c"]
    return float((c[-1] / c[-1 - n] - 1.0) * 100.0) if len(c) > n and c[-1 - n] > 0 else None


def symbol_state(sym: str, ctx: Dict[str, Any], now: float) -> Optional[Dict[str, Any]]:
    m15, h4, d1 = ctx["m15"], ctx["h4"], ctx["d1"]
    atr = ctx["atr15"]
    if len(m15["t"]) < 100 or not np.isfinite(atr[-1]):
        return None
    price = float(m15["c"][-1])
    atr_pct = float(atr[-1] / price * 100.0)
    atr_hist = atr[-672:] / m15["c"][-672:] * 100.0       # ~7 діб
    atr_hist = atr_hist[np.isfinite(atr_hist)]
    vol_regime = float(np.mean(atr_hist <= atr_pct)) if len(atr_hist) >= 50 else None   # перцентиль поточної волатильності за 7 діб (0..1)
    k4 = F.last_closed(h4, 4 * 3600, now)
    kd = F.last_closed(d1, F.DAY, now)
    rng24 = (float(m15["h"][-96:].max()), float(m15["l"][-96:].min()))
    pos24 = (price - rng24[1]) / (rng24[0] - rng24[1]) if rng24[0] > rng24[1] else None
    up = sorted([lv for lv in ctx["levels"] if lv["known"] <= now and lv["side"] == "high" and lv["p"] > price], key=lambda x: x["p"])[:3]
    dn = sorted([lv for lv in ctx["levels"] if lv["known"] <= now and lv["side"] == "low" and lv["p"] < price], key=lambda x: -x["p"])[:3]
    lvl = lambda L: [{"p": float(x["p"]), "kind": x["kind"], "strength": int(x["strength"]), "dist_atr": float(abs(x["p"] - price) / atr[-1])} for x in L]  # noqa: E731
    tbv_last = float(2.0 * m15["tbv"][-1] - m15["v"][-1]) if np.isfinite(m15["tbv"][-1]) else None
    return {"price": price, "atr15_pct": atr_pct, "vol_regime_7d": vol_regime, "reg4": int(ctx["reg4"][k4]) if k4 >= 0 else 0,
            "regd": int(ctx["regd"][kd]) if kd >= 0 else 0, "ret_1h": _ret(m15, 4), "ret_4h": _ret(m15, 16), "ret_24h": _ret(m15, 96),
            "pos_24h_range": pos24, "range_24h_atr": float((rng24[0] - rng24[1]) / atr[-1]), "taker_delta_last_bar": tbv_last,
            "levels_up": lvl(up), "levels_dn": lvl(dn), "bar_close_ts": float(m15["t"][-1] + 900)}


def market_context(states: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    btc, eth = states.get("BTCUSDT"), states.get("ETHUSDT")
    alts = [s for k, s in states.items() if k not in ("BTCUSDT", "ETHUSDT")]

    def frac(key: str) -> Optional[float]:
        v = [s[key] for s in alts if s.get(key) is not None]
        return float(np.mean([x > 0 for x in v])) if len(v) >= 5 else None

    def med(key: str) -> Optional[float]:
        v = [s[key] for s in alts if s.get(key) is not None]
        return float(np.median(v)) if len(v) >= 5 else None

    return {"n_alts": len(alts), "breadth_up_1h": frac("ret_1h"), "breadth_up_4h": frac("ret_4h"), "breadth_up_24h": frac("ret_24h"),
            "median_alt_ret_4h": med("ret_4h"), "median_alt_ret_24h": med("ret_24h"), "median_vol_regime": med("vol_regime_7d"),
            "btc_ret_4h": btc.get("ret_4h") if btc else None, "btc_ret_24h": btc.get("ret_24h") if btc else None, "btc_reg4": btc.get("reg4") if btc else None,
            "btc_regd": btc.get("regd") if btc else None, "btc_vol_regime": btc.get("vol_regime_7d") if btc else None,
            "eth_ret_4h": eth.get("ret_4h") if eth else None, "eth_ret_24h": eth.get("ret_24h") if eth else None, "eth_reg4": eth.get("reg4") if eth else None}


def relative_strength(st: Dict[str, Any], mc: Dict[str, Any]) -> Dict[str, Optional[float]]:
    def d(a: Optional[float], b: Optional[float]) -> Optional[float]:
        return None if a is None or b is None else float(a - b)

    return {"rs_vs_btc_4h": d(st.get("ret_4h"), mc.get("btc_ret_4h")), "rs_vs_eth_4h": d(st.get("ret_4h"), mc.get("eth_ret_4h")),
            "rs_vs_btc_24h": d(st.get("ret_24h"), mc.get("btc_ret_24h")), "rs_vs_alts_4h": d(st.get("ret_4h"), mc.get("median_alt_ret_4h"))}


def session_bucket(ts: float) -> str:
    h = datetime.fromtimestamp(ts, tz=timezone.utc).hour
    return "ASIA" if h < 7 else "EU" if h < 13 else "US" if h < 21 else "LATE"


# ---------------------------------------------------------------- старий Лев (лише читання)
def _json(s: Any) -> Dict[str, Any]:
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def old_lev_state(db: str, symbol: str, now: float) -> Dict[str, Any]:
    """Що старий Лев думав про монету на момент now: останній LEV_WATCH і останній SIGNAL_PLAN (24 год). Лише читання."""
    from office_bridge import _fetchall

    out: Dict[str, Any] = {"watch": None, "plan_24h": None}
    try:
        rows = _fetchall(db, "SELECT payload_json, ts_utc FROM office_events WHERE event_type = 'LEV_WATCH' AND payload_json LIKE ? ORDER BY id DESC LIMIT 40", (f'%"{symbol}"%',))
        for pj, ts in rows:
            d = _json(pj)
            if str(d.get("symbol", "")).upper() == symbol:
                out["watch"] = {k: d.get(k) for k in ("watch_id", "status", "direction", "zone_lo", "zone_hi", "invalidation", "wait_tf", "expires_at", "touched_zone") if k in d} | {"ts_utc": ts}
                break
        rows = _fetchall(db, "SELECT payload_json, ts_utc FROM office_events WHERE event_type = 'SIGNAL_PLAN' AND payload_json LIKE ? ORDER BY id DESC LIMIT 20", (f'%"{symbol}"%',))
        for pj, ts in rows:
            d = _json(pj)
            ct = d.get("confirmed_ts")
            if str(d.get("symbol", "")).upper() == symbol and isinstance(ct, (int, float)) and now - ct <= 86400:
                out["plan_24h"] = {k: d.get(k) for k in ("scenario_id", "direction", "entry", "sl", "tp1", "tp2", "tp3", "rejected", "reason", "confirmed_ts")}
                break
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:120]
    return out


def new_old_lev_plans(db: str, after_id: int) -> List[Tuple[int, Dict[str, Any]]]:
    from office_bridge import _fetchall

    rows = _fetchall(db, "SELECT id, payload_json FROM office_events WHERE event_type = 'SIGNAL_PLAN' AND id > ? ORDER BY id ASC LIMIT 100", (after_id,))
    return [(int(i), _json(pj)) for i, pj in rows]


def last_event_id(db: str) -> int:
    from office_bridge import _fetchone

    r = _fetchone(db, "SELECT MAX(id) FROM office_events WHERE event_type = 'SIGNAL_PLAN'")
    return int(r[0]) if r and r[0] is not None else 0


# ---------------------------------------------------------------- події
def _eid(*parts: Any) -> str:
    return "E-" + hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def candidate_snapshot(sym: str, cand: dict, st: Dict[str, Any], mc: Dict[str, Any], old: Dict[str, Any], now: float) -> Dict[str, Any]:
    pos = RK.position_size(RK.RiskConfig().risk_usd, cand["entry"], cand["sl"])
    return _clean({"decision": OBS_ONLY, "why_not_ready2": "Office2 не має жодного GATE-компонента з доведеною перевагою OOS; кандидат — лише спостереження",
                   "decision_ts": now, "session": session_bucket(now), "old_lev": old, "market": mc, "relative": relative_strength(st, mc), "state": st,
                   "candidate": {k: cand[k] for k in ("dir", "entry", "sl", "tp", "risk_pct", "rr", "trigger", "etype", "lvl_kind", "lvl_strength", "lvl_p", "depth_atr", "tp_kind",
                                                       "reg4", "regd", "btc4", "flow_ok", "atr_pct", "htf_ok", "btc_ok")},
                   "structural_invalidation": {"sl": cand["sl"], "basis": "екстремум sweep ∓ 0.5·ATR(M15)", "risk_pct": cand["risk_pct"]},
                   "targets": {"tp": cand["tp"], "kind": cand["tp_kind"], "rr": cand["rr"]},
                   "risk": {"risk_usd": pos["risk_usd"], "qty": pos["qty"], "notional": pos["notional"], "cluster": RK.cluster_of(sym)},
                   "params": {"k_buf": P.Params().k_buf, "min_rr": P.Params().min_rr}, "version": VERSION, "source": SOURCE})


def store_event(db: str, event_id: str, now: float, sym: str, kind: str, direction: Optional[str], entry: Optional[float], sl: Optional[float], tp: Optional[float], snap: Dict[str, Any]) -> bool:
    iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    _insert_ignore(db, "office2_shadow_event", ("event_id", "ts_epoch", "ts_utc", "symbol", "kind", "direction", "entry", "sl", "tp", "decision", "version", "source", "snapshot_json"),
                   (event_id, int(now), iso, sym, kind, direction, entry, sl, tp, snap.get("decision", OBS_ONLY), VERSION, SOURCE, _j(snap)))
    return True


def cycle(db: str, feed: Feed, now: float, state: Dict[str, Any], syms: Optional[List[str]] = None) -> Dict[str, int]:
    """Один цикл. now — момент закриття щойно завершеного M15-бару. state: пам'ять між циклами {'last_plan_id': int}."""
    syms = syms or universe()
    ctxs: Dict[str, Dict[str, Any]] = {}
    states: Dict[str, Dict[str, Any]] = {}
    for sym in syms:
        try:
            ctx = build_ctx(feed, sym, now)
            if not ctx:
                continue
            st = symbol_state(sym, ctx, now)
            if st:
                ctxs[sym], states[sym] = ctx, st
        except Exception as exc:  # noqa: BLE001
            _bump("errors")
            with _LOCK:
                _STATS["last_error"] = f"{sym}: {str(exc)[:100]}"
            if "backoff" in str(exc) or "429" in str(exc) or "RateLimited" in type(exc).__name__:
                break   # Binance просить паузу — цикл закінчуємо
    mc = market_context(states)
    res = {"states": 0, "events": 0, "old_lev": 0}
    ts_bar = int(now)
    btc_ctx = ctxs.get("BTCUSDT")
    btc_for_pipe = {"m15": btc_ctx["m15"]} if btc_ctx else None
    for sym, st in states.items():
        rec = dict(st, **relative_strength(st, mc), market=mc, session=session_bucket(now))
        _insert_ignore(db, "office2_shadow_state", ("ts_epoch", "symbol", "version", "payload_json"), (ts_bar, sym, VERSION, _j(_clean(rec))))
        res["states"] += 1
        # кандидат Office2 на щойно закритому барі: синтетичний 1m-рядок «ціна входу» у момент тригера (чесно: вхід після закриття бару)
        ctx = ctxs[sym]
        price = float(ctx["m15"]["c"][-1])
        m1 = {"t": np.array([now], dtype=np.float64), "o": np.array([price]), "h": np.array([price]), "l": np.array([price]), "c": np.array([price]),
              "v": np.zeros(1), "tbv": np.zeros(1)}
        try:
            cands = P.candidates(sym, dict(ctx, m1=m1), btc_for_pipe if sym != "BTCUSDT" else None, P.Params())
        except Exception as exc:  # noqa: BLE001
            _bump("errors")
            with _LOCK:
                _STATS["last_error"] = f"cand {sym}: {str(exc)[:100]}"
            continue
        for c in cands:
            if abs(c["t_entry"] - now) > 1:
                continue   # лише кандидати, чий тригер = щойно закритий бар
            old = old_lev_state(db, sym, now)
            snap = candidate_snapshot(sym, c, st, mc, old, now)
            eid = _eid("O2", sym, c["dir"], c["trigger"], int(c["t_entry"]), round(c["lvl_p"], 8))
            store_event(db, eid, now, sym, "O2_CANDIDATE", c["dir"], c["entry"], c["sl"], c["tp"], snap)
            res["events"] += 1
    # нові рішення старого Лева → подія OLD_LEV зі знімком стану Office2 на той самий момент
    for pid, plan in new_old_lev_plans(db, int(state.get("last_plan_id", 0))):
        state["last_plan_id"] = max(int(state.get("last_plan_id", 0)), pid)
        sym = str(plan.get("symbol") or "").upper()
        if not sym or plan.get("direction") not in ("LONG", "SHORT"):
            continue
        st = states.get(sym)
        if st is None:
            try:
                ctx = build_ctx(feed, sym, now)
                st = symbol_state(sym, ctx, now) if ctx else None
            except Exception:  # noqa: BLE001
                st = None
        snap = _clean({"decision": "OLD_LEV_" + ("REJECTED" if plan.get("rejected") else "READY"), "decision_ts": now, "session": session_bucket(now),
                       "old_lev": {"plan": {k: plan.get(k) for k in ("scenario_id", "direction", "entry", "sl", "tp1", "tp2", "tp3", "max_entry", "confirmed_ts", "valid_until_ts", "rejected", "reason", "tf")}},
                       "market": mc, "relative": relative_strength(st, mc) if st else None, "state": st, "office2_decision": OBS_ONLY,
                       "version": VERSION, "source": SOURCE})
        store_event(db, _eid("OLDLEV", pid), now, sym, "OLD_LEV", plan["direction"], plan.get("entry"), plan.get("sl"), plan.get("tp1"), snap)
        res["old_lev"] += 1
    _bump("states", res["states"])
    _bump("events", res["events"])
    _bump("old_lev", res["old_lev"])
    _bump("cycles")
    with _LOCK:
        _STATS["last_cycle"] = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
    return res


# ---------------------------------------------------------------- наслідки (майбутнє — лише тут)
def resolve_outcomes(db: str, feed: Feed, now: float, limit: int = 6) -> int:
    from office_bridge import _fetchall

    rows = _fetchall(db, """SELECT e.event_id, e.ts_epoch, e.symbol, e.direction, e.entry, e.sl, e.tp, e.kind, e.snapshot_json FROM office2_shadow_event e
                            LEFT JOIN office2_shadow_outcome o ON o.event_id = e.event_id
                            WHERE o.event_id IS NULL AND e.ts_epoch <= ? AND e.direction IS NOT NULL AND e.entry IS NOT NULL AND e.sl IS NOT NULL
                            ORDER BY e.ts_epoch ASC LIMIT ?""", (int(now - OUTCOME_AFTER_SEC), limit))
    done = 0
    for eid, ts, sym, direction, entry, sl, tp, kind, snap_json in rows:
        try:
            parts: List[Dict[str, np.ndarray]] = []
            start = int(ts) * 1000
            end = (int(ts) + OUTCOME_AFTER_SEC + 120) * 1000
            while start < end and len(parts) < 4:
                a = feed.klines(sym, "1m", now, limit=1500, start_ms=start)
                if a is None or not len(a["t"]):
                    break
                parts.append(a)
                start = int(a["t"][-1] * 1000) + 60_000
            if not parts:
                continue
            m1 = {k: np.concatenate([p[k] for p in parts]) for k in ("t", "o", "h", "l", "c", "v", "tbv")}
            i0 = int(np.searchsorted(m1["t"], ts, side="left"))
            if i0 >= len(m1["t"]):
                continue
            if kind == "OLD_LEV":   # план старого Лева — лімітний вхід: рахуємо з першого дотику ціни входу протягом 24 год
                touch = np.flatnonzero((m1["l"][i0:] <= float(entry)) & (m1["h"][i0:] >= float(entry)) & (m1["t"][i0:] <= ts + 86400))
                if not len(touch):
                    _insert_ignore(db, "office2_shadow_outcome", ("event_id", "ts_resolved_epoch", "status", "version", "outcome_json"), (eid, int(now), "NOT_FILLED", VERSION, "{}"))
                    continue
                i0 += int(touch[0])
            st = (_json(snap_json).get("state") or {})
            px, ap = st.get("price"), st.get("atr15_pct")
            atr = float(px) * float(ap) / 100.0 if px and ap else abs(float(entry) - float(sl))
            rec = OUT.outcome_record(m1, i0, direction, float(entry), float(sl), atr=atr, horizon_sec=OUTCOME_AFTER_SEC)
            if rec is None:
                _insert_ignore(db, "office2_shadow_outcome", ("event_id", "ts_resolved_epoch", "status", "version", "outcome_json"), (eid, int(now), "NO_DATA", VERSION, "{}"))
                continue
            if tp:   # власна ціль/сторона: перший дотик TP чи SL на 1m (одна хвилина → стоп першим), net R після комісій
                from office2 import sim as S

                ft = S.first_touch(m1, i0, direction, float(entry), float(sl), float(tp), horizon_sec=OUTCOME_AFTER_SEC)
                rec["own_target"] = {"outcome": ft["outcome"], "ttr_sec": ft["ttr_sec"], "r_gross": ft["r_gross"], "r_net": S.net_r(ft["r_gross"], rec["risk_pct"], OUT.FEE_RT_PCT + OUT.SLIP_RT_PCT), "mfe_r": ft["mfe_r"], "mae_r": ft["mae_r"]}
            _insert_ignore(db, "office2_shadow_outcome", ("event_id", "ts_resolved_epoch", "status", "version", "outcome_json"), (eid, int(now), "COMPLETE" if rec.get("complete") else "PARTIAL", VERSION, _j(_clean(rec))))
            done += 1
        except Exception as exc:  # noqa: BLE001
            _bump("errors")
            with _LOCK:
                _STATS["last_error"] = f"outcome {sym}: {str(exc)[:100]}"
            if "backoff" in str(exc):
                break
    _bump("outcomes", done)
    return done


# ---------------------------------------------------------------- фон
def _next_bar_close(now: float) -> float:
    return (int(now) // CYCLE_SEC + 1) * CYCLE_SEC


def run_forever(db: str, feed: Optional[Feed] = None) -> None:
    feed = feed or Feed()
    init_db(db)
    state: Dict[str, Any] = {"last_plan_id": last_event_id(db)}   # лише нові рішення Лева, без вичитування історії
    _log(f"старт {VERSION}: символів {len(universe())}, db ok; Telegram не використовується")
    while True:
        try:
            nxt = _next_bar_close(time.time())
            time.sleep(max(1.0, nxt - time.time() + 20))     # +20 с: бар точно закрито й віддається біржею
            now = float(nxt)
            t0 = time.time()
            res = cycle(db, feed, now, state)
            n_out = resolve_outcomes(db, feed, time.time())
            _log(f"цикл {datetime.fromtimestamp(now, tz=timezone.utc):%H:%M}Z: {res}, наслідків {n_out}, запитів {feed.requests}, {time.time() - t0:.0f} с")
        except Exception as exc:  # noqa: BLE001
            _bump("errors")
            with _LOCK:
                _STATS["last_error"] = str(exc)[:160]
            _log(f"помилка циклу (гаситься): {exc!r}")
            time.sleep(30)


def start_background(db: str) -> bool:
    """Запускає потік, якщо OFFICE2_SHADOW=1. Ніколи не кидає виняток у виклику (worker не має постраждати)."""
    try:
        if not enabled():
            return False
        th = threading.Thread(target=run_forever, args=(db,), name="office2-shadow", daemon=True)
        th.start()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[o2shadow] не запущено: {exc!r}", file=sys.stderr, flush=True)
        return False

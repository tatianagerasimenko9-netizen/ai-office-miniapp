"""Воронка скану Binance Futures: ротація всього universe + окремі Gainers/Losers + PULLBACK WATCH.

Проблема, яку вирішує: глибокий аналіз щоразу бачив ті самі ~24 майже статичні монети (мувери-«перегріті» займали місця й завжди відсікались T0/ATR,
Gainers витісняли Losers, після SKIP сценарій губився). Тепер:
  1. Весь ліквідний universe (USDT-перпи після базових фільтрів) РЕГУЛЯРНО проходить глибокий аналіз: кожного циклу — ротаційна пачка
     «найдавніше не аналізовані першими» (monitor coverage), тож за кілька циклів перебираються всі монети.
  2. Top Gainers і Top Losers — ОКРЕМІ квоти: ріст не витісняє падіння.
  3. Сильний рух, що вже виходить за межі (≥ EXTENDED_PCT за 24 год або T0/ATR заблокував вхід), — НЕ звичайний кандидат: це PULLBACK WATCH
     (не наздоганяємо; чекаємо відкат/ретест). Станом володіє реєстр, він переживає SKIP і перезапуск (запис у БД).
  4. Напрям після сильного руху: після росту — LONG на здоровому відкаті, SHORT лише за підтвердженим розворотом структури (CHoCH); після падіння — дзеркально.
Пороги ATR, RR, підтвердження й інші запобіжники НЕ змінюються: воронка лише вирішує, КОГО дивитись і КОЛИ повернутись до монети. Ордерів немає."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

EVENT_TYPE = "PULLBACK_WATCH"
STRONG_PCT = 5.0            # |зміна за 24 год| ≥ цього — «сильний рух» (діє правило напрямку)
EXTENDED_PCT = 10.0         # ≥ цього — одразу PULLBACK WATCH, глибокий слот не витрачаємо, поки немає відкату
PULLBACK_ZONE = (0.30, 0.80)  # частка відкату від екстремуму до бази руху: «здоровий» відкат
RECHECK_SEC = 1800          # повторна перевірка монети з реєстру — не частіше, ніж раз на 30 хв
TTL_SEC = 36 * 3600         # запис у реєстрі живе 36 год
FADE_PCT = 3.0              # рух зійшов нанівець (|зміна| < 3%) — запис знімаємо

CAP = int(os.getenv("OFFICE_SCOUT_DEEP_CAP", "36") or 36)
ROTATE_MIN = 10             # завжди резервуємо стільки місць під ротацію
Q_USER_CTX = 99             # запит власниці й контекст — без ліміту
Q_PULLBACK = 6
Q_GAINERS = 5
Q_LOSERS = 5
Q_VOLUME = 4
Q_WATCHING = 6


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


def _sym(v: Any) -> str:
    return str(v or "").upper().strip()


@dataclass
class FunnelState:
    last_deep: Dict[str, float] = field(default_factory=dict)       # symbol → ts останнього глибокого аналізу
    pullbacks: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # symbol → запис PULLBACK WATCH
    deep_log: List[Tuple[float, str]] = field(default_factory=list)  # (ts, symbol) за останню добу — для звіту покриття
    hydrated: bool = False
    persisted_at: float = 0.0


STATE = FunnelState()


def mark_deep(symbol: str, now: Optional[float] = None, state: Optional[FunnelState] = None) -> None:
    st = state or STATE
    now = time.time() if now is None else now
    s = _sym(symbol)
    st.last_deep[s] = now
    st.deep_log.append((now, s))
    cut = now - 86400
    if len(st.deep_log) > 4000 or (st.deep_log and st.deep_log[0][0] < cut):
        st.deep_log = [x for x in st.deep_log if x[0] >= cut]


# ── PULLBACK WATCH ──────────────────────────────────────────────────────────────

def impulse_of(row: Dict[str, Any]) -> Optional[str]:
    ch = _f(row.get("change_pct"))
    if ch is None or abs(ch) < STRONG_PCT:
        return None
    return "UP" if ch > 0 else "DOWN"


def retrace_of(entry: Dict[str, Any], price: float) -> Optional[float]:
    """Частка відкату від екстремуму до бази руху: 0 — на екстремумі, 1 — уся база віддана. None — немає діапазону."""
    hi, lo = _f(entry.get("ext_high")), _f(entry.get("ext_low"))
    if hi is None or lo is None or hi <= lo:
        return None
    if entry.get("impulse") == "UP":
        return max(0.0, (hi - price) / (hi - lo))
    return max(0.0, (price - lo) / (hi - lo))


def register_pullback(symbol: str, row: Dict[str, Any], *, reason: str, now: Optional[float] = None,
                      t0_blocked: bool = False, state: Optional[FunnelState] = None) -> Optional[Dict[str, Any]]:
    """Ставимо монету на PULLBACK WATCH. Існуючий запис лише оновлюємо (межі руху розширюємо, час реєстрації лишаємо)."""
    st = state or STATE
    now = time.time() if now is None else now
    s = _sym(symbol)
    imp = impulse_of(row)
    if not s or imp is None:
        return None
    e = st.pullbacks.get(s)
    hi, lo = _f(row.get("high")), _f(row.get("low"))
    if e is None:
        e = {"symbol": s, "impulse": imp, "since": now, "last_check": 0.0, "reason": reason, "t0_blocked": bool(t0_blocked),
             "ext_high": hi, "ext_low": lo, "status": "EXTENDED", "change_pct": _f(row.get("change_pct"))}
        st.pullbacks[s] = e
    else:
        if hi is not None:
            e["ext_high"] = max(hi, e["ext_high"] or hi)
        if lo is not None:
            e["ext_low"] = min(lo, e["ext_low"] or lo)
        if reason:
            e["reason"] = reason
        e["t0_blocked"] = bool(t0_blocked or e.get("t0_blocked"))
    return e


def update_pullbacks(rows: Iterable[Dict[str, Any]], now: Optional[float] = None, state: Optional[FunnelState] = None) -> Dict[str, int]:
    """Оновлюємо стан за знімком ticker/24hr: EXTENDED (ще далеко від відкату) → PULLBACK (відкат у зоні) → REVERSAL_ZONE (віддано >80% руху).
    Протухлі й «зійшли нанівець» записи знімаємо. Дешево: без запитів, лише ціни з одного знімка."""
    st = state or STATE
    now = time.time() if now is None else now
    by = {_sym(r.get("symbol")): r for r in rows if isinstance(r, dict)}
    for s in list(st.pullbacks):
        e = st.pullbacks[s]
        r = by.get(s)
        if now - float(e.get("since") or now) > TTL_SEC:
            del st.pullbacks[s]
            continue
        if not r:
            continue
        ch = _f(r.get("change_pct"))
        px = _f(r.get("price"))
        if ch is not None and abs(ch) < FADE_PCT and now - float(e.get("since") or now) > 3600:
            del st.pullbacks[s]
            continue
        hi, lo = _f(r.get("high")), _f(r.get("low"))
        if hi is not None:
            e["ext_high"] = hi if e.get("ext_high") is None else max(e["ext_high"], hi)
        if lo is not None:
            e["ext_low"] = lo if e.get("ext_low") is None else min(e["ext_low"], lo)
        e["change_pct"] = ch
        rt = retrace_of(e, px) if px else None
        e["retrace"] = None if rt is None else round(rt, 3)
        if rt is None:
            e["status"] = "EXTENDED"
        elif rt < PULLBACK_ZONE[0]:
            e["status"] = "EXTENDED"
        elif rt <= PULLBACK_ZONE[1]:
            e["status"] = "PULLBACK"
        else:
            e["status"] = "REVERSAL_ZONE"
    c = {"EXTENDED": 0, "PULLBACK": 0, "REVERSAL_ZONE": 0}
    for e in st.pullbacks.values():
        c[e["status"]] = c.get(e["status"], 0) + 1
    return c


def due_pullbacks(now: Optional[float] = None, state: Optional[FunnelState] = None) -> List[str]:
    """Монети з реєстру, де відкат уже сформувався (або структура віддала рух) і давно не перевіряли."""
    st = state or STATE
    now = time.time() if now is None else now
    out = [e for e in st.pullbacks.values() if e.get("status") in ("PULLBACK", "REVERSAL_ZONE") and now - float(e.get("last_check") or 0) >= RECHECK_SEC]
    out.sort(key=lambda e: (e.get("status") != "PULLBACK", float(e.get("last_check") or 0)))
    return [e["symbol"] for e in out]


def mark_checked(symbol: str, now: Optional[float] = None, state: Optional[FunnelState] = None, note: str = "") -> None:
    st = state or STATE
    e = st.pullbacks.get(_sym(symbol))
    if e is not None:
        e["last_check"] = time.time() if now is None else now
        if note:
            e["note"] = note[:200]


def reversal_confirmed(h1_candles: Any, impulse: str) -> bool:
    """Підтверджений розворот структури ПРОТИ імпульсу: закриття за останнім свінгом проти руху (CHoCH) на закритих H1.
    Після росту — CHoCH вниз (SHORT), після падіння — CHoCH вгору (LONG)."""
    try:
        import office_smc as smc
        from office_patterns import closed_only

        rows = closed_only([r for r in (h1_candles or []) if isinstance(r, dict)], None)[-120:]
        if len(rows) < 15:
            return False
        want = "SHORT" if impulse == "UP" else "LONG"
        st = smc.structure(rows)
        return any(ev.get("kind") == "choch" and ev.get("side") == want and ev.get("idx", 0) >= len(rows) - 6 for ev in st.get("events") or [])
    except Exception:  # noqa: BLE001
        return False


def direction_gate(direction: str, impulse: Optional[str], *, reversal_ok: bool) -> Tuple[bool, str]:
    """(дозволено, причина). Без сильного руху обмежень немає. Проти імпульсу — лише з підтвердженим розворотом структури."""
    d = str(direction or "").upper()
    if impulse not in ("UP", "DOWN") or d not in ("LONG", "SHORT"):
        return True, ""
    with_trend = (impulse == "UP" and d == "LONG") or (impulse == "DOWN" and d == "SHORT")
    if with_trend:
        return True, ""
    if reversal_ok:
        return True, "розворот структури підтверджено"
    word = "росту" if impulse == "UP" else "падіння"
    return False, f"після сильного {word} протилежний напрям лише за підтвердженим розворотом структури (CHoCH) — його поки немає"


# ── вибір для глибокого аналізу ─────────────────────────────────────────────────

def select_deep(rows: Sequence[Dict[str, Any]], gainers: Sequence[Dict[str, Any]], losers: Sequence[Dict[str, Any]], *,
                user_symbols: Sequence[str] = (), context_symbols: Sequence[str] = ("BTCUSDT", "XAUUSDT"), active_watching: Sequence[str] = (),
                now: Optional[float] = None, cap: Optional[int] = None, state: Optional[FunnelState] = None) -> List[Dict[str, Any]]:
    """[{symbol, tier, reason}] у порядку пріоритету. Місця: запит власниці+контекст → відкат у реєстрі → Gainers (окрема квота) → Losers (окрема квота)
    → обсяг → вже у спостереженні → ротація (найдавніше не аналізовані). Ротація має зарезервовані місця (ROTATE_MIN) і ніколи не витісняється."""
    st = state or STATE
    now = time.time() if now is None else now
    cap = max(ROTATE_MIN + 2, int(cap or CAP))
    chosen: List[Dict[str, Any]] = []
    seen: set = set()
    universe = {_sym(r.get("symbol")): r for r in rows if isinstance(r, dict) and r.get("symbol")}

    def take(sym: Any, tier: str, reason: str) -> bool:
        s = _sym(sym)
        if not s or s in seen:
            return False
        seen.add(s)
        chosen.append({"symbol": s, "tier": tier, "reason": reason})
        return True

    for s in user_symbols:
        take(s, "user", "запит власниці")
    for s in context_symbols:
        take(s, "context", "контекст ринку (завжди в аналізі)")
    budget = cap - ROTATE_MIN

    def quota(items: Iterable[Any], tier: str, n: int, why) -> None:
        got = 0
        for it in items:
            if got >= n or len(chosen) >= budget:
                break
            sym = it.get("symbol") if isinstance(it, dict) else it
            if _sym(sym) in st.pullbacks and tier in ("gainers", "losers", "volume"):
                continue          # «перегріті» монети — не звичайні кандидати, їх місце займає наступний у списку
            if take(sym, tier, why(it) if callable(why) else why):
                got += 1

    due = due_pullbacks(now, st)
    quota(due, "pullback", Q_PULLBACK, lambda s: f"PULLBACK WATCH: відкат сформувався ({'після росту' if st.pullbacks[s]['impulse'] == 'UP' else 'після падіння'}, відкат {int(100 * (st.pullbacks[s].get('retrace') or 0))}%)")
    quota([r for r in gainers if (_f(r.get("change_pct")) or 0) > 0], "gainers", Q_GAINERS,
          lambda r: f"Top Gainer 24 год {(_f(r.get('change_pct')) or 0):+.1f}%".replace(".", ","))
    quota([r for r in losers if (_f(r.get("change_pct")) or 0) < 0], "losers", Q_LOSERS,
          lambda r: f"Top Loser 24 год {(_f(r.get('change_pct')) or 0):+.1f}%".replace(".", ","))
    vol = sorted(rows, key=lambda r: float(r.get("volume_usdt") or 0.0), reverse=True)[:12]
    quota(vol, "volume", Q_VOLUME, lambda r: f"великий обсяг ({float(r.get('volume_usdt') or 0) / 1e6:.0f} млн USDT)")
    quota(active_watching, "watching", Q_WATCHING, "вже у спостереженні")

    # ротація: усі решта ліквідні монети, найдавніше аналізовані першими; ніколи не аналізовані — раніше за всіх
    rest = [s for s in universe if s not in seen and s not in st.pullbacks]
    rest.sort(key=lambda s: (st.last_deep.get(s, 0.0), -float(universe[s].get("volume_usdt") or 0.0)))
    room = cap - len(chosen)
    for s in rest[:max(room, 0)]:
        never = s not in st.last_deep
        take(s, "rotation", "ротація universe: " + ("ще не аналізована" if never else f"остання перевірка {int((now - st.last_deep[s]) / 60)} хв тому"))
    return chosen


def coverage(universe_size: int, now: Optional[float] = None, state: Optional[FunnelState] = None, window_sec: int = 86400) -> Dict[str, Any]:
    st = state or STATE
    now = time.time() if now is None else now
    syms = {s for t, s in st.deep_log if now - t <= window_sec}
    return {"deep_distinct": len(syms), "universe": int(universe_size), "share": round(len(syms) / universe_size, 3) if universe_size else None}


def counts_report(chosen: Sequence[Dict[str, Any]], state: Optional[FunnelState] = None) -> Dict[str, Any]:
    st = state or STATE
    tiers: Dict[str, int] = {}
    for c in chosen:
        tiers[c["tier"]] = tiers.get(c["tier"], 0) + 1
    pb = {"EXTENDED": 0, "PULLBACK": 0, "REVERSAL_ZONE": 0}
    for e in st.pullbacks.values():
        pb[e["status"]] = pb.get(e["status"], 0) + 1
    return {"selected": len(chosen), "tiers": tiers, "pullback_watch_total": len(st.pullbacks), "pullback_by_status": pb}


# ── збереження в БД (переживає перезапуск worker) ───────────────────────────────

def persist(db: str, state: Optional[FunnelState] = None, now: Optional[float] = None) -> None:
    from office_bridge import log_event

    st = state or STATE
    log_event(db, EVENT_TYPE, {"at": time.time() if now is None else now, "pullbacks": st.pullbacks,
                               "last_deep": {s: t for s, t in st.last_deep.items() if (time.time() if now is None else now) - t < 86400}})


def hydrate(db: str, state: Optional[FunnelState] = None, now: Optional[float] = None) -> int:
    from office_bridge import _fetchall

    st = state or STATE
    now = time.time() if now is None else now
    try:
        rows = _fetchall(db, "SELECT payload_json FROM office_events WHERE event_type = ? ORDER BY id DESC LIMIT 1", (EVENT_TYPE,))
    except Exception:  # noqa: BLE001
        return 0
    if not rows:
        return 0
    try:
        p = json.loads(rows[0][0]) if isinstance(rows[0][0], str) else dict(rows[0][0])
    except (TypeError, ValueError):
        return 0
    n = 0
    for s, e in (p.get("pullbacks") or {}).items():
        if isinstance(e, dict) and now - float(e.get("since") or 0) <= TTL_SEC:
            st.pullbacks[_sym(s)] = e
            n += 1
    for s, t in (p.get("last_deep") or {}).items():
        if _f(t) is not None:
            st.last_deep.setdefault(_sym(s), float(t))
    return n

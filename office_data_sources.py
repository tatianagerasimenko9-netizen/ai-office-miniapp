"""Статуси джерел даних для Mini App — ОКРЕМО по кожному джерелу (а не одним рядком «Лев не бачить: …»).

Лише відображення й пояснення: нічого не блокує, не змінює RR/пороги/READY/WATCHING/Telegram.
Джерела: стакан і спред (авто-вмикання після 24 год стабільних свічок), ліквідації (потік Binance у worker → зліпок у БД), новини (календар)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

ON, OFF = "on", "off"


def _usd(v: float) -> str:
    v = float(v or 0.0)
    if v >= 1e6:
        return f"{v / 1e6:.1f}".replace(".", ",") + " млн $"
    if v >= 1e3:
        return f"{v / 1e3:.0f} тис $"
    return f"{v:.0f} $"


def depth_source(symbol: str, db: Optional[str]) -> Dict[str, Any]:
    import office_data_stability as ds
    import office_market_data as omd

    mode = omd.depth_mode()
    syms = omd.depth_symbols()
    names = " і ".join(s.replace("USDT", "") for s in syms)
    st: Dict[str, Any] = {}
    try:
        st = ds.status(db) if db else {}
    except Exception:  # noqa: BLE001
        st = {}
    need = int(st.get("need") or ds.HOURS)
    have = int(st.get("streak_hours") or 0)
    base = {"key": "depth", "name": "Стакан і спред"}
    if mode == "on" or (mode == "auto" and st.get("stable")):
        if str(symbol or "").upper() not in syms:
            return {**base, "state": OFF, "text": f"Стакан увімкнено лише для {names}. Для цієї монети його немає."}
        how = "увімкнено вручну" if mode == "on" else f"увімкнено автоматично: свічки стабільні {need} год поспіль"
        return {**base, "state": ON, "text": f"Стакан і спред підключені ({how})."}
    if mode == "auto":
        return {**base, "state": OFF, "text": (f"Стакан вимкнено: вмикається сам, коли свічки Binance стабільні {need} год поспіль без збоїв. "
                                                 f"Зараз {have} з {need} год. Свічки важливіші за стакан.")}
    return {**base, "state": OFF, "text": "Стакан вимкнено в налаштуваннях."}


def liq_source(symbol: str, direction: str, zone_lo: Any, zone_hi: Any, db: Optional[str], now: Optional[float] = None) -> Dict[str, Any]:
    import time

    import office_liq_map as lm

    now = time.time() if now is None else now
    base = {"key": "liquidations", "name": "Ліквідації"}
    r = lm.latest_persisted(db, symbol, now=now) if db else {"ok": False, "note": "база даних недоступна"}
    if not r.get("ok"):
        return {**base, "state": OFF, "text": f"Дані ліквідацій недоступні: {r.get('note') or 'потік не пише'}."}
    real = r.get("real") or {}
    stream = r.get("stream") or {}
    started = stream.get("started_at")
    hours = 24.0
    if isinstance(started, (int, float)) and started:
        hours = max(0.1, min(24.0, (now - float(started)) / 3600.0))
    win = f"{hours:.0f}" if hours >= 1 else "менше години"
    span = f"За останні {win} год" if hours >= 1 else "Відколи запущено потік (менше години)"
    longs, shorts, cnt = float(real.get("long_liq_usd") or 0), float(real.get("short_liq_usd") or 0), int(real.get("count") or 0)
    if cnt == 0:
        return {**base, "state": ON, "text": f"Потік ліквідацій працює. {span}: помітних ліквідацій цієї монети немає."}
    parts = [f"Потік ліквідацій працює. {span}: лонгів ліквідовано на {_usd(longs)}, шортів — на {_usd(shorts)}."]
    long_ = str(direction or "").upper() != "SHORT"
    if longs > shorts * 1.5:
        parts.append("Переважали ліквідації лонгів — покупців уже вибивало. " + ("Купівля ризикованіша." if long_ else "Це збігається з напрямком продажу."))
    elif shorts > longs * 1.5:
        parts.append("Переважали ліквідації шортів — продавців уже вибивало. " + ("Це збігається з напрямком купівлі." if long_ else "Продаж ризикованіший."))
    else:
        parts.append("Ліквідації лонгів і шортів приблизно рівні — перекосу немає.")
    try:
        lo, hi = float(zone_lo), float(zone_hi)
        pad = (hi - lo) * 0.5 + (hi + lo) / 2 * 0.004
        near = [b for b in (real.get("buckets") or []) if lo - pad <= float(b.get("price") or 0) <= hi + pad]
        if near:
            nl = sum(float(b["usd"]) for b in near if b.get("kind") == "long_liq")
            ns = sum(float(b["usd"]) for b in near if b.get("kind") == "short_liq")
            what = "лонгів" if nl >= ns else "шортів"
            parts.append(f"Біля зони входу вже були ліквідації {what} на {_usd(max(nl, ns))}.")
    except (TypeError, ValueError):
        pass
    parts.append("Це контекст, а не сигнал: нічого не блокує.")
    return {**base, "state": ON, "text": " ".join(parts)}


def news_source() -> Dict[str, Any]:
    import office_calendar as cal

    base = {"key": "news", "name": "Новини й календар"}
    if not cal.block_enabled():
        return {**base, "state": OFF, "text": "Календар новин вимкнено в налаштуваннях."}
    if cal.load()["status"] != "DATA_OK":
        return {**base, "state": OFF, "text": "Календар новин зараз недоступний — пауза перед новинами не діє."}
    return {**base, "state": ON, "text": "Календар новин підключено: за 30 хв до і 15 хв після важливої новини нові входи не відкриваємо."}


def sources_for(symbol: str, direction: str, zone_lo: Any = None, zone_hi: Any = None, db: Optional[str] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for fn in (lambda: depth_source(symbol, db), lambda: liq_source(symbol, direction, zone_lo, zone_hi, db), news_source):
        try:
            out.append(fn())
        except Exception as exc:  # noqa: BLE001
            out.append({"key": "?", "name": "Джерело", "state": OFF, "text": f"Не вдалося перевірити ({type(exc).__name__})."})
    return out

"""Рівні монети і короткий розбір «як аналітик» для екрана Лева (ЛИШЕ ЧИТАННЯ, нічого не надсилає і не відкриває).
ДЖЕРЕЛО способу читати рівень — матеріали власниці (скриншоти А. Герчика, 28.11.2026; docs/strategies/GERCHIK_LEVELS_UA.md); рівнів автора Офіс не показує — шукає власні (рішення власниці 28.11.2026): «повернення в лонгову зону вище рівня згенерує сильний сигнал на купівлю на кілька днів»; вище рівня — лонг, нижче — шорт.
ГІПОТЕЗА (наша автоматизація, не методика автора): як саме Офіс знаходить рівні на денних свічках — мінімум/максимум поточного й минулого року, мінімуми/максимуми місяців за 24 місяці,
денні розвороти за 60 діб (3 доби з обох боків); близькі рівні (у межах 2%) зливаються в одну зону; «прокол і повернення» = за останні 5 діб мінімум був нижче рівня, а останнє денне закриття — вище.
Ймовірностей і прогнозів не дає: лише «де сходинки і що означає прохід кожної»."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]
MERGE_PCT = 2.0; RECLAIM_DAYS = 5; TOUCH_PCT = 0.6
_CACHE: Dict[str, Any] = {}
# Частоти з перевірки на денних свічках біткоїна 2022–2026 (levels_hist.py, журнал BT): (як часто, скільки випадків). Лише опис історії, не обіцянка.
HIST = {"DOWN": {"near": ("у 7 випадках із 10", 212), "mid": ("приблизно пів на пів", 16)}, "RECLAIM": {"near": ("у 7 випадках із 10", 200), "mid": ("у 4 випадках із 10", 24)}}


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def _ts(row: dict) -> float:
    return datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).timestamp()


def _px(x: float) -> str:
    if x >= 1000: return f"{x:,.0f}".replace(",", " ")
    if x >= 1: return f"{x:.2f}".replace(".", ",")
    return f"{x:.5f}".rstrip("0").replace(".", ",")


def find_levels(days: List[Dict[str, float]], sym: str = "") -> List[Dict[str, Any]]:
    """days: закриті денні свічки за зростанням часу [{t, h, l, c}]. Повертає рівні {p, kind, label, w} (w — вага: рік 3, розворот 2, місяць 1)."""
    if len(days) < 30: return []
    out: List[Dict[str, Any]] = []; last = _dt(days[-1]["t"]); yr = last.year
    for y, nm in ((yr, f"{yr} року"), (yr - 1, f"{yr - 1} року")):
        ds = [d for d in days if _dt(d["t"]).year == y]
        if len(ds) < 20: continue
        lo = min(ds, key=lambda d: d["l"]); hi = max(ds, key=lambda d: d["h"])
        out.append({"p": lo["l"], "kind": "low", "label": f"мінімум {nm}", "w": 3, "t": lo["t"]}); out.append({"p": hi["h"], "kind": "high", "label": f"максимум {nm}", "w": 3, "t": hi["t"]})
    by: Dict[tuple, list] = {}
    for d in days: by.setdefault((_dt(d["t"]).year, _dt(d["t"]).month), []).append(d)
    for (y, m), ds in sorted(by.items())[-25:-1]:                                            # 24 завершені місяці
        if len(ds) < 15: continue
        lo = min(ds, key=lambda d: d["l"]); hi = max(ds, key=lambda d: d["h"]); nm = f"{MONTHS[m - 1]} {y}"
        out.append({"p": lo["l"], "kind": "low", "label": f"мінімум {nm}", "w": 1, "t": lo["t"]}); out.append({"p": hi["h"], "kind": "high", "label": f"максимум {nm}", "w": 1, "t": hi["t"]})
    rec = days[-60:]
    for i in range(3, len(rec) - 1):
        a = rec[max(0, i - 3):i + 4]; d = rec[i]; dm = f"{_dt(d['t']).day:02d}.{_dt(d['t']).month:02d}"
        if d["l"] == min(x["l"] for x in a): out.append({"p": d["l"], "kind": "low", "label": f"найнижча точка {dm}", "w": 2, "t": d["t"]})
        if d["h"] == max(x["h"] for x in a): out.append({"p": d["h"], "kind": "high", "label": f"найвища точка {dm}", "w": 2, "t": d["t"]})
    out.sort(key=lambda z: z["p"]); merged: List[Dict[str, Any]] = []
    for z in out:
        if merged and (z["p"] / merged[-1]["lo"] - 1) * 100 <= MERGE_PCT:
            g = merged[-1]; g["n"] += 1; g["hi"] = z["p"]; g["labels"].append((z["w"], z["t"], z["label"]))
            if (z["w"], z["t"]) > (g["w"], g["t"]): g.update({"p": z["p"], "kind": z["kind"], "w": z["w"], "t": z["t"]})
        else: merged.append(dict(z, n=1, lo=z["p"], hi=z["p"], labels=[(z["w"], z["t"], z["label"])]))
    for g in merged:
        ls = []
        for x in sorted(g["labels"], reverse=True):
            if x[2] not in ls: ls.append(x[2])
        g["label"] = ls[0] + (f" · {ls[1]}" if len(ls) > 1 else ""); g.pop("labels")
        lo_, hi_ = g["lo"] * (1 - TOUCH_PCT / 100), g["hi"] * (1 + TOUCH_PCT / 100); g["touch"] = sum(1 for d in days if lo_ <= d["l"] <= hi_ or lo_ <= d["h"] <= hi_)   # скільки днів ціна краєм свічки спиралась на цю зону
    return merged


def analyse(sym: str, days: List[Dict[str, float]], price: Optional[float] = None) -> Dict[str, Any]:
    """Сходинки рівнів навколо ціни і текст Лева. price — жива ціна (якщо немає, останнє денне закриття)."""
    lv = find_levels(days, sym); name = sym.replace("USDT", "")
    if not lv: return {"ok": False, "sym": name, "text": "Замало історії, щоб знайти рівні."}
    px = float(price or days[-1]["c"]); last_c = days[-1]["c"]
    below = [z for z in lv if z["p"] < px][-4:][::-1]; above = [z for z in lv if z["p"] >= px][:3]
    pct = lambda p: round((p / px - 1) * 100, 1)
    zone = lambda z: _px(z["p"]) if z["hi"] / z["lo"] - 1 < 0.003 else f"{_px(z['lo'])}–{_px(z['hi'])}"
    row = lambda z, side: {"p": zone(z), "label": z["label"], "pct": pct(z["p"]), "side": side, "strong": z["w"] >= 3 or z["n"] >= 3, "n": z["n"], "touch": z["touch"], "lo": z["lo"], "hi": z["hi"]}
    ladder = [row(z, "above") for z in above[::-1]] + [{"p": _px(px), "now": True}] + [row(z, "below") for z in below]
    state = "between"; key = None; rc = days[-RECLAIM_DAYS:]; lo5 = min(d["l"] for d in rc)
    old = find_levels(days[:-RECLAIM_DAYS], sym)                                                  # рівні, що існували ДО цих 5 діб: їх проколювали, а закриття вже вище
    pierced = [z for z in old if lo5 < z["lo"] and z["hi"] < min(last_c, px)]
    if pierced: key = max(pierced, key=lambda z: z["p"]); state = "reclaim"
    elif below: key = below[0]
    pc = lambda p: str(abs(pct(p))).replace(".", ",")
    def odds(kind: str, dist: float) -> str:
        """Що частіше було на історії біткоїна (levels_hist.py, журнал BT): лише там, де випадків досить."""
        b = "near" if dist < 5 else ("mid" if dist < 10 else "far"); h = HIST[kind].get(b)
        if not h: return "Так далеко на історії було лише кілька разів — що вірогідніше, сказати не можу."
        return f"На історії біткоїна так було {h[0]} (випадків {h[1]})."
    now_l: List[str] = []; down_l: List[str] = []; up_l: List[str] = []
    if key is None:
        now_l.append(f"Ціна {_px(px)} нижче всіх рівнів за два роки. Опори знизу не бачу.")
    elif state == "reclaim":
        now_l.append(f"Рівень {zone(key)} проколювали вниз, але день закрився вище. Це знак на користь покупців на кілька днів.")
    else:
        now_l.append(f"Ціна {_px(px)} стоїть над рівнем {zone(key)}. Поки день закривається вище — перевага в покупців.")
    if key is not None:
        nxt = [z for z in lv if z["hi"] < key["lo"]][-1:]
        if nxt: down_l.append(f"Якщо день закриється нижче {_px(key['lo'])} — рівень зламано, найближча ціль {_px(nxt[0]['p'])} (−{pc(nxt[0]['p'])}%). " + odds("DOWN", abs(pct(nxt[0]["p"]))))
        else: down_l.append(f"Якщо день закриється нижче {_px(key['lo'])} — рівень зламано, а наступного рівня знизу я не бачу.")
    if above:
        a = above[0]; nx2 = f" Далі {_px(above[1]['p'])}." if len(above) > 1 else ""
        up_l.append(f"Якщо день закриється вище {_px(a['hi'])} — дорога до {_px(above[1]['p'])} відкрита (+{pc(above[1]['p'])}%)." if len(above) > 1 else f"Зверху один рівень: {_px(a['p'])} (+{pc(a['p'])}%).")
    lines = now_l + down_l + up_l
    verdict = ("Вірогідніше — вгору до " + _px(above[0]["p"]) + ", поки день не закрився нижче " + _px(key["lo"]) + ".") if (state == "reclaim" and above and key) else (("Рівень тримається. Сигналу немає, поки день не закриється за рівнем.") if key else "")
    return {"ok": True, "sym": name, "price": _px(px), "price_num": px, "state": state, "key": _px(key["lo"]) if key else None, "ladder": ladder, "text": lines, "verdict": verdict, "blocks": {"now": now_l, "down": down_l, "up": up_l},
            "note": "Рахую за денними свічками: дивлюсь на закриття дня, а не на прокол. Це карта рівнів, а не прогноз.",
            "source": "Рівні Офіс знаходить сам на денному графіку — там, де ціна кілька разів спиралась, — і перераховує щодня. Спосіб читати рівень (вище — покупці, нижче — продавці; повернення після проколу; рух від рівня до рівня) — з матеріалів, які ви надіслали.",
            "bars": [[d["t"], d["o"], d["h"], d["l"], d["c"]] for d in days[-90:] if "o" in d]}


def levels(sym: str, fetch: Optional[Callable] = None, price: Optional[float] = None, now: Optional[float] = None, tf: str = "1d") -> Dict[str, Any]:
    """Для API: денні свічки ф'ючерсів → розбір. Кеш 10 хв на монету (ціна підставляється свіжа)."""
    now = time.time() if now is None else now; sym = sym.upper()
    c = _CACHE.get(sym)
    if not c or now - c[0] > 600:
        if fetch is None:
            from office_market_data import fetch_candles_futures as fetch
        rows = fetch(sym, "1d", 800, closed_only=True)
        if not isinstance(rows, list) or len(rows) < 30: return {"ok": False, "sym": sym.replace("USDT", ""), "text": "Немає денних свічок по цій монеті."}
        days = [{"t": _ts(r), "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"])} for r in rows]
        _CACHE[sym] = c = (now, days)
    out = analyse(sym, c[1], price)
    if out.get("ok") and tf in ("1h", "4h"):                                                 # графік на дрібнішому таймфреймі; рівні лишаються денні
        try:
            k = (sym, tf); cc = _CACHE.get(k)
            if not cc or now - cc[0] > 60:
                if fetch is None:
                    from office_market_data import fetch_candles_futures as fetch
                rows = fetch(sym, tf, 120, closed_only=False)
                if isinstance(rows, list) and len(rows) > 20: _CACHE[k] = cc = (now, [[_ts(r), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])] for r in rows])
            if cc: out["bars"] = cc[1][-110:]
        except Exception:  # noqa: BLE001
            pass
    out["tf"] = tf if tf in ("1h", "4h") else "1d"
    return out


# ───────────────────────── Події рівнів: «день закрився за рівнем» (нагадування; не сигнал, ордерів немає) ─────────────────────────
# Рішення власниці 28.11.2026: нагадування в Telegram і те саме в апці, по всіх монетах Офісу. Щоб не засипати — лише СИЛЬНІ зони (спирались ≥10 днів або річний екстремум),
# одна подія на монету на добу, у Telegram — ОДНЕ зведене повідомлення на добу. Вимкнути: LEVEL_ALERTS=0.
DDL_EV = """CREATE TABLE IF NOT EXISTS lev_level_event (day TEXT NOT NULL, symbol TEXT NOT NULL, kind TEXT NOT NULL, level DOUBLE PRECISION NOT NULL, target DOUBLE PRECISION,
    pct DOUBLE PRECISION, low DOUBLE PRECISION, close DOUBLE PRECISION, created_ts DOUBLE PRECISION NOT NULL, sent INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, symbol))"""
_LAST_DAY = ""


def alerts_enabled() -> bool:
    import os
    return os.getenv("LEVEL_ALERTS", "1").strip().lower() in ("1", "true", "yes", "on")


def day_event(days: List[Dict[str, float]]) -> Optional[Dict[str, Any]]:
    """Подія ОСТАННЬОГО закритого дня відносно рівнів, відомих до нього. kind: DOWN (закрився нижче), UP (вище), RECLAIM (прокол і повернення)."""
    if len(days) < 60: return None
    lv = [z for z in find_levels(days[:-1]) if z["touch"] >= 10 or z["w"] >= 3]; c0, c1 = days[-2]["c"], days[-1]["c"]; lo5 = min(d["l"] for d in days[-RECLAIM_DAYS:]); best = None
    for z in lv:
        kind = None
        if c0 >= z["lo"] and c1 < z["lo"]: kind = "DOWN"
        elif c0 <= z["hi"] and c1 > z["hi"]: kind = "RECLAIM" if lo5 < z["lo"] else "UP"
        if not kind: continue
        nx = [q for q in lv if q["hi"] < z["lo"]][-1:] if kind == "DOWN" else [q for q in lv if q["lo"] > z["hi"]][:1]
        tgt = (nx[0]["hi"] if kind == "DOWN" else nx[0]["lo"]) if nx else None
        ev = {"kind": kind, "level": z["lo"] if kind == "DOWN" else z["hi"], "target": tgt, "pct": round((tgt / c1 - 1) * 100, 1) if tgt else None, "low": lo5, "close": c1, "touch": z["touch"]}
        if best is None or z["touch"] > best["touch"]: best = ev
    return best


def daily(db: str, fetch: Optional[Callable] = None, now: Optional[float] = None, symbols: Optional[tuple] = None) -> int:
    """Раз на добу після закриття дня (00:10+ UTC): записати події по всіх монетах. Повертає кількість нових подій. Ніколи не кидає."""
    global _LAST_DAY
    if not alerts_enabled(): return 0
    now = time.time() if now is None else now; g = _dt(now)
    if g.hour == 0 and g.minute < 10: return 0
    day = _dt(now - 86400).strftime("%Y-%m-%d")
    if _LAST_DAY == day: return 0
    try:
        from office_bridge import _execute, _fetchone
        _execute(db, DDL_EV, ())
        if _fetchone(db, "SELECT 1 FROM lev_level_event WHERE day = ? LIMIT 1", (day + "#done",)): _LAST_DAY = day; return 0
        if fetch is None:
            from office_market_data import fetch_candles_futures as fetch
        if symbols is None:
            from office_td import swing
            symbols = tuple(s for s in swing.SYMBOLS if s in swing.SYMBOLS[:12] + swing.EXTRA_CRYPTO)
        n = seen = 0
        for sym in symbols:
            try:
                rows = fetch(sym, "1d", 800, closed_only=True)
                if not isinstance(rows, list) or len(rows) < 60: continue
                days = [{"t": _ts(r), "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"])} for r in rows]
                if _dt(days[-1]["t"]).strftime("%Y-%m-%d") != day: continue
                seen += 1; _CACHE[sym] = (now, days); ev = day_event(days)
                if ev:
                    _execute(db, "INSERT INTO lev_level_event(day, symbol, kind, level, target, pct, low, close, created_ts) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING", (day, sym, ev["kind"], ev["level"], ev["target"], ev["pct"], ev["low"], ev["close"], now)); n += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[levels] {sym}: {type(exc).__name__}: {exc}", flush=True)
        if seen >= max(1, len(symbols) // 2):                                              # день закрито лише коли більшість монет прочитано; інакше повторимо
            _execute(db, "INSERT INTO lev_level_event(day, symbol, kind, level, created_ts, sent) VALUES (?,?,?,?,?,1) ON CONFLICT DO NOTHING", (day + "#done", "-", "-", 0.0, now)); _LAST_DAY = day
        print(f"[levels] {day}: монет {seen}, подій {n}", flush=True); return n
    except Exception as exc:  # noqa: BLE001
        print(f"[levels] daily: {type(exc).__name__}: {exc}", flush=True); return 0


def _ev_line(r: Dict[str, Any]) -> str:
    s = r["symbol"].replace("USDT", ""); p = lambda v: str(abs(v)).replace(".", ",")
    if r["kind"] == "DOWN": return f"{s} — нижче {_px(r['level'])}" + (f" → ціль {_px(r['target'])} (−{p(r['pct'])}%)" if r.get("target") else " → рівня нижче не бачу")
    if r["kind"] == "UP": return f"{s} — вище {_px(r['level'])}" + (f" → ціль {_px(r['target'])} (+{p(r['pct'])}%)" if r.get("target") else "")
    return f"{s} — вище {_px(r['level'])}, проколювали до {_px(r['low'])}" + (f" → ціль {_px(r['target'])} (+{p(r['pct'])}%)" if r.get("target") else "")


def digest(rows: List[Dict[str, Any]], day: str) -> str:
    """Одне повідомлення на добу. У Telegram іде лише після згоди власниці (LEVEL_ALERTS_TG=1)."""
    dm = f"{day[8:10]}.{day[5:7]}"; out = [f"📍 Рівні за добу · {dm}"]
    for kind, head in (("DOWN", "🔴 День закрився НИЖЧЕ рівня:"), ("UP", "🟢 День закрився ВИЩЕ рівня:"), ("RECLAIM", "🟢 Повернення вище рівня після проколу:")):
        xs = [r for r in rows if r["kind"] == kind]
        if xs: out.append(head); out += [_ev_line(r) for r in xs]
    out.append("Це нагадування, не сигнал. Розбір кожної монети — в апці, «Рівні»."); return "\n".join(out)


def events(db: str, days_back: int = 7, now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Для апки: події за останні дні, свіжі зверху."""
    from office_bridge import _execute, _fetchall
    now = time.time() if now is None else now; _execute(db, DDL_EV, ()); since = _dt(now - days_back * 86400).strftime("%Y-%m-%d"); out = []
    for day, sym, kind, level, target, pct, low, close in _fetchall(db, "SELECT day, symbol, kind, level, target, pct, low, close FROM lev_level_event WHERE symbol != '-' AND day >= ? ORDER BY day DESC, symbol", (since,)):
        r = {"day": day, "symbol": sym, "kind": kind, "level": level, "target": target, "pct": pct, "low": low, "close": close}
        out.append({"day": f"{day[8:10]}.{day[5:7]}", "sym": sym.replace("USDT", ""), "symbol": sym, "kind": kind, "text": _ev_line(r)})
    return out


async def deliver(db: str, send: Callable, now: Optional[float] = None) -> int:
    """Worker: надіслати зведення за добу, якщо є ненадіслані події. Позначає надісланими лише після успіху."""
    if not alerts_enabled(): return 0
    import os
    if os.getenv("LEVEL_ALERTS_TG", "0").strip().lower() not in ("1", "true", "yes", "on"): return 0   # у Telegram — лише після «так» власниці; в апці події видно завжди
    from office_bridge import _execute, _fetchall
    _execute(db, DDL_EV, ()); rs = _fetchall(db, "SELECT day, symbol, kind, level, target, pct, low, close FROM lev_level_event WHERE sent = 0 AND symbol != '-' ORDER BY day, symbol", ())
    if not rs: return 0
    day = rs[-1][0]; now = time.time() if now is None else now
    if not _fetchall(db, "SELECT 1 FROM lev_level_event WHERE day = ?", (day + "#done",)): return 0      # чекаємо, доки добу дораховано
    rows = [dict(zip(("day", "symbol", "kind", "level", "target", "pct", "low", "close"), r)) for r in rs if r[0] == day]
    mid = await send(digest(rows, day), symbol="", direction="")
    if mid:
        _execute(db, "UPDATE lev_level_event SET sent = 1 WHERE sent = 0", ()); print(f"[levels] надіслано зведення {day}: {len(rows)} подій", flush=True); return len(rows)
    return 0

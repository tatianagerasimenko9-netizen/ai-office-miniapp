"""Рівні монети і короткий розбір «як аналітик» для екрана Лева (ЛИШЕ ЧИТАННЯ, нічого не надсилає і не відкриває).
ДЖЕРЕЛО правила читання рівня — матеріали власниці (скриншоти А. Герчика, 28.11.2026): «повернення в лонгову зону вище рівня згенерує сильний сигнал на купівлю на кілька днів»; вище рівня — лонг, нижче — шорт.
ГІПОТЕЗА (наша автоматизація, не методика автора): як саме Офіс знаходить рівні на денних свічках — мінімум/максимум поточного й минулого року, мінімуми/максимуми місяців за 24 місяці,
денні розвороти за 60 діб (3 доби з обох боків); близькі рівні (у межах 2%) зливаються в одну зону; «прокол і повернення» = за останні 5 діб мінімум був нижче рівня, а останнє денне закриття — вище.
Ймовірностей і прогнозів не дає: лише «де сходинки і що означає прохід кожної»."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"]
MERGE_PCT = 2.0; RECLAIM_DAYS = 5
_CACHE: Dict[str, Any] = {}


def _dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def _ts(row: dict) -> float:
    return datetime.fromisoformat(str(row["ts"]).replace("Z", "+00:00")).timestamp()


def _px(x: float) -> str:
    if x >= 1000: return f"{x:,.0f}".replace(",", " ")
    if x >= 1: return f"{x:.2f}".replace(".", ",")
    return f"{x:.5f}".rstrip("0").replace(".", ",")


def find_levels(days: List[Dict[str, float]]) -> List[Dict[str, Any]]:
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
        ls = [x[2] for x in sorted(g["labels"], reverse=True)]; g["label"] = ls[0] + (f" · {ls[1]}" if len(ls) > 1 else ""); g.pop("labels")
    return merged


def analyse(sym: str, days: List[Dict[str, float]], price: Optional[float] = None) -> Dict[str, Any]:
    """Сходинки рівнів навколо ціни і текст Лева. price — жива ціна (якщо немає, останнє денне закриття)."""
    lv = find_levels(days); name = sym.replace("USDT", "")
    if not lv: return {"ok": False, "sym": name, "text": "Замало історії, щоб знайти рівні."}
    px = float(price or days[-1]["c"]); last_c = days[-1]["c"]
    below = [z for z in lv if z["p"] < px][-4:][::-1]; above = [z for z in lv if z["p"] >= px][:3]
    pct = lambda p: round((p / px - 1) * 100, 1)
    zone = lambda z: _px(z["p"]) if z["hi"] / z["lo"] - 1 < 0.003 else f"{_px(z['lo'])}–{_px(z['hi'])}"
    row = lambda z, side: {"p": zone(z), "label": z["label"], "pct": pct(z["p"]), "side": side, "strong": z["w"] >= 3 or z["n"] >= 3, "n": z["n"]}
    ladder = [row(z, "above") for z in above[::-1]] + [{"p": _px(px), "now": True}] + [row(z, "below") for z in below]
    lines: List[str] = []; state = "between"; key = None
    rc = days[-RECLAIM_DAYS:]; lo5 = min(d["l"] for d in rc)
    old = find_levels(days[:-RECLAIM_DAYS])                                                       # рівні, що існували ДО цих 5 діб: їх проколювали, а закриття вже вище
    pierced = [z for z in old if lo5 < z["lo"] and z["hi"] < min(last_c, px)]
    if pierced:
        key = max(pierced, key=lambda z: z["p"]); state = "reclaim"
        lines.append(f"Рівень {zone(key)} ({key['label']}) за останні дні проколювали вниз до {_px(lo5)}, але день закрився вище. Повернення вище рівня — сильний знак на користь покупців на кілька днів.")
        lines.append(f"Це діє, поки день закривається вище {_px(key['lo'])}. Закриття дня нижче — рівень зламано, і зона стає шортовою.")
    elif below:
        key = below[0]
        lines.append(f"Ціна {_px(px)} стоїть над рівнем {_px(key['p'])} ({key['label']}). Вище нього — лонгова зона від рівня, нижче — шортова.")
    else:
        lines.append(f"Ціна {_px(px)} нижче всіх рівнів, які я бачу за два роки: опори знизу немає.")
    if key is not None:
        nxt = [z for z in lv if z["hi"] < key["lo"]][-1:]
        if nxt: lines.append(f"Якщо день закриється нижче {_px(key['lo'])}, наступна сходинка — {_px(nxt[0]['p'])} ({nxt[0]['label']}), це {str(pct(nxt[0]['p'])).replace('.', ',')}% від ціни зараз.")
    if above:
        a = above[0]; lines.append(f"Зверху найближчий рівень — {_px(a['p'])} ({a['label']}), +{str(pct(a['p'])).replace('.', ',')}%. Поки ціна під ним, це стеля." + (f" Далі {_px(above[1]['p'])}." if len(above) > 1 else ""))
    return {"ok": True, "sym": name, "price": _px(px), "state": state, "key": _px(key["lo"]) if key else None, "ladder": ladder, "text": lines,
            "note": "Рахую за денними свічками: дивлюсь на закриття дня, а не на прокол. Це карта рівнів, а не прогноз.",
            "source": "Правило «вище рівня — лонг, нижче — шорт; повернення вище рівня — сильний сигнал» — з матеріалів Герчика, які ви надіслали. Самі рівні Офіс знаходить автоматично."}


def levels(sym: str, fetch: Optional[Callable] = None, price: Optional[float] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Для API: денні свічки ф'ючерсів → розбір. Кеш 10 хв на монету (ціна підставляється свіжа)."""
    now = time.time() if now is None else now; sym = sym.upper()
    c = _CACHE.get(sym)
    if not c or now - c[0] > 600:
        if fetch is None:
            from office_market_data import fetch_candles_futures as fetch
        rows = fetch(sym, "1d", 800, closed_only=True)
        if not isinstance(rows, list) or len(rows) < 30: return {"ok": False, "sym": sym.replace("USDT", ""), "text": "Немає денних свічок по цій монеті."}
        days = [{"t": _ts(r), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"])} for r in rows]
        _CACHE[sym] = c = (now, days)
    return analyse(sym, c[1], price)

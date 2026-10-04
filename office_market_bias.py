"""Перевага ринку (LONG / SHORT / ЗМІШАНИЙ) із чесних лічильників, відповідність сигналу ринку, підсумок активних планів.

Жодних вигаданих ваг і відсотків («70/30»): показуємо, скільки з перевірених ознак за LONG, скільки за SHORT.
Пороги нижче — лише межа «майже не змінилось» і правило більшості; вони ІНФОРМАЦІЙНІ, на історії не калібровані
і нічого не блокують (сигнали, стопи, цілі, RR не змінюються). Чого не рахуємо (S&P/Nasdaq, DXY, нафта) — прямо в NOT_CONNECTED.
Вхід — свічки у форматі office_market_data (dict з open/high/low/close/ts), по зростанню часу.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

FLAT_PCT = 0.2          # |зміна| менша — «майже не змінилась» (інформаційна межа)
BREADTH_HI = 0.6        # частка зростаючих монет ≥ цього — ознака LONG; ≤ 1−цього — ознака SHORT
LEAD_MIN = 2            # перевага визнається, якщо ознак «за» більше, ніж «проти», щонайменше на стільки
INDEP_CORR = 0.3        # кореляція руху монети з BTC нижча — «рухається незалежно»
NOT_CONNECTED = ["S&P 500 / Nasdaq", "індекс долара DXY", "нафта"]

BASKET = ("ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "BCH", "TRX", "NEAR", "APT", "ARB", "OP", "SUI", "INJ", "ATOM", "AAVE")


def _f(v: Any) -> Optional[float]:
    try:
        x = None if v is None else float(v)
    except (TypeError, ValueError):
        return None
    return None if x is None or x != x else x


def ret_pct(candles: Any, bars: int) -> Optional[float]:
    """Зміна закриття за `bars` свічок (від закриття свічки bars тому до останнього закриття), %."""
    rows = [c for c in (candles if isinstance(candles, list) else []) if _f((c or {}).get("close")) is not None]
    if len(rows) < bars + 1:
        return None
    a, b = float(rows[-1 - bars]["close"]), float(rows[-1]["close"])
    return round((b / a - 1.0) * 100.0, 3) if a else None


def corr(a: Any, b: Any, n: int = 48) -> Optional[float]:
    """Кореляція відсоткових змін двох рядів свічок (останні n); None, якщо замало даних."""
    ra = [float(c["close"]) for c in (a if isinstance(a, list) else []) if _f((c or {}).get("close")) is not None]
    rb = [float(c["close"]) for c in (b if isinstance(b, list) else []) if _f((c or {}).get("close")) is not None]
    m = min(len(ra), len(rb), n + 1)
    if m < 12:
        return None
    ra, rb = ra[-m:], rb[-m:]
    xa = [ra[i] / ra[i - 1] - 1.0 for i in range(1, m)]
    xb = [rb[i] / rb[i - 1] - 1.0 for i in range(1, m)]
    ma, mb = sum(xa) / len(xa), sum(xb) / len(xb)
    va = sum((x - ma) ** 2 for x in xa)
    vb = sum((x - mb) ** 2 for x in xb)
    if va <= 0 or vb <= 0:
        return None
    return round(sum((x - ma) * (y - mb) for x, y in zip(xa, xb)) / (va * vb) ** 0.5, 3)


def _txt(v: Optional[float], nd: int = 1) -> str:
    return "—" if v is None else f"{v:+.{nd}f}%".replace(".", ",").replace("-", "−")


def _vote(x: Optional[float]) -> int:
    if x is None or abs(x) < FLAT_PCT:
        return 0
    return 1 if x > 0 else -1


def assess(*, btc_1h: Any, eth_1h: Any, basket_1h: Optional[Dict[str, Any]] = None, btc_week_dist_pct: Optional[float] = None, bph: int = 1) -> Dict[str, Any]:
    """Перевага ринку за свічками BTC, ETH і кошика великих монет (4 год і 1 год) та положенням BTC щодо Weekly Open.
    bph — скільки свічок у годині (1 для 1h, 4 для 15m): зміну беремо рівно за 1 і 4 години."""
    b1, b4 = ret_pct(btc_1h, bph), ret_pct(btc_1h, 4 * bph)
    e4 = ret_pct(eth_1h, 4 * bph)
    up = down = n = 0
    for _, cs in (basket_1h or {}).items():
        r = ret_pct(cs, 4 * bph)
        if r is None:
            continue
        n += 1
        up += r > 0
        down += r < 0
    facts: List[Dict[str, Any]] = []

    def add(key: str, vote: int, text: str) -> None:
        facts.append({"key": key, "vote": vote, "text": text})

    if b4 is not None:
        add("btc4", _vote(b4), f"BTC {_txt(b4)} за 4 год")
    if btc_week_dist_pct is not None:
        add("btcw", _vote(btc_week_dist_pct), f"BTC {_txt(btc_week_dist_pct)} від Weekly Open")
    if e4 is not None:
        add("eth4", _vote(e4), f"ETH {_txt(e4)} за 4 год")
    if n >= 8:
        share = up / n
        add("breadth", 1 if share >= BREADTH_HI else -1 if share <= 1 - BREADTH_HI else 0, f"{up} із {n} великих монет ростуть за 4 год")
    longs = sum(1 for f in facts if f["vote"] > 0)
    shorts = sum(1 for f in facts if f["vote"] < 0)
    if not facts:
        bias = "UNKNOWN"
    elif longs - shorts >= LEAD_MIN and longs * 2 > len(facts):   # перевага = відрив і більшість усіх перевірених ознак (а не лише двоє з чотирьох)
        bias = "LONG"
    elif shorts - longs >= LEAD_MIN and shorts * 2 > len(facts):
        bias = "SHORT"
    else:
        bias = "MIXED"
    return {"bias": bias, "long": longs, "short": shorts, "checked": len(facts), "facts": facts, "btc_1h": b1, "btc_4h": b4, "eth_4h": e4,
            "breadth": {"up": up, "down": down, "n": n}, "not_connected": NOT_CONNECTED}


BIAS_UA = {"LONG": "LONG", "SHORT": "SHORT", "MIXED": "ЗМІШАНА", "UNKNOWN": "не визначена"}


def alignment(market: Dict[str, Any], *, direction: str, coin: str, coin_1h: Any, btc_1h: Any, corr_btc: Optional[float] = None, bph: int = 1) -> Dict[str, Any]:
    """Сигнал проти ринку: WITH / COUNTER / MIXED / INDEPENDENT + порівняння руху монети з BTC за 1 год."""
    d = str(direction or "").upper()
    c1, b1 = ret_pct(coin_1h, bph), ret_pct(btc_1h, bph)
    rel = round(c1 - b1, 2) if c1 is not None and b1 is not None else None
    bias = market.get("bias")
    if bias in ("LONG", "SHORT"):
        state = "WITH" if bias == d else "COUNTER"
    else:
        state = "MIXED"
    # кореляція на ~47 вимірах шумна: зберігаємо для дослідження, але користувачу як факт НЕ показуємо
    return {"state": state, "coin": coin, "coin_1h": c1, "btc_1h": b1, "rel_pp": rel, "corr_btc": corr_btc, "weak_corr": corr_btc is not None and corr_btc < INDEP_CORR, "bias": bias}


def signal_lines(market: Dict[str, Any], al: Dict[str, Any]) -> List[str]:
    """Рядки для READY-картки; лише те, що реально пораховано."""
    if not market or market.get("bias") in (None, "UNKNOWN"):
        return []
    flat_n = (market.get("checked") or 0) - market.get("long", 0) - market.get("short", 0)
    out = [f"Ринок: перевага {BIAS_UA.get(market['bias'], market['bias'])}"
           + (f" ({market['long']} за LONG, {market['short']} за SHORT, {flat_n} без руху — із {market['checked']})" if market.get("checked") else "")]
    if al.get("btc_1h") is not None:
        out.append(f"BTC 1 год: {_txt(al['btc_1h'])}")
    if al.get("coin_1h") is not None:
        out.append(f"{al['coin']} 1 год: {_txt(al['coin_1h'])}")
    if al.get("rel_pp") is not None:
        if abs(al["rel_pp"]) < 0.15:
            out.append(f"{al['coin']} рухається так само, як BTC (різниця {abs(al['rel_pp']):.1f}".replace(".", ",") + " п.п.)")
        else:
            word = "сильніший" if al["rel_pp"] >= 0 else "слабший"
            out.append(f"{al['coin']} {word} за BTC на {abs(al['rel_pp']):.1f}".replace(".", ",") + " п.п.")
    out.append({"WITH": "Напрямок: разом із ринком ✅", "COUNTER": "Напрямок: проти ринку ⚠️", "MIXED": "Напрямок: ринок змішаний, переваги немає",
                "INDEPENDENT": f"Напрямок: монета рухається незалежно від BTC (кореляція {str(al.get('corr_btc')).replace('.', ',').replace('-', '−')})"}[al["state"]])
    return out


def card_lines(market: Dict[str, Any], al: Optional[Dict[str, Any]]) -> List[str]:
    """Два рядки для Telegram-картки: «Ринок: …» і «BTC 1г: … · МОНЕТА: … → …». Нічого, чого немає в даних."""
    if not market or market.get("bias") in (None, "UNKNOWN"):
        return []
    flat_n = (market.get("checked") or 0) - market.get("long", 0) - market.get("short", 0)
    icon = {"LONG": "🟢 перевага LONG", "SHORT": "🔴 перевага SHORT"}.get(market["bias"], "🟡 без переваги")
    line = f"Ринок: {icon} — {market.get('long', 0)} LONG / {market.get('short', 0)} SHORT / {flat_n} нейтр."
    if al and al.get("state") == "WITH":
        line += " · ✅ за ринком"
    elif al and al.get("state") == "COUNTER":
        line += " · ⚠️ проти ринку"
    out = [line]
    if al and al.get("btc_1h") is not None and al.get("coin_1h") is not None:
        rel = al.get("rel_pp")
        tail = ""
        if rel is not None:
            tail = (" → так само" if abs(rel) < 0.15 else f" → {'сильніша' if rel > 0 else 'слабша'} на {abs(rel):.1f}".replace(".", ",") + " п.п.")
        out.append(f"BTC 1г: {_txt(al['btc_1h'])} · {al['coin']}: {_txt(al['coin_1h'])}{tail}")
    return out


def portfolio(plans: Sequence[Dict[str, Any]], *, corrs: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Підсумок активних планів: скільки LONG / SHORT; якщо майже всі в один бік — попередження про одну спільну ставку."""
    lg = sum(1 for p in plans if str(p.get("direction")).upper() == "LONG")
    sh = sum(1 for p in plans if str(p.get("direction")).upper() == "SHORT")
    n = lg + sh
    cs = [v for v in (corrs or {}).values() if v is not None]
    avg = round(sum(cs) / len(cs), 2) if cs else None
    warn = ""
    if n >= 4 and max(lg, sh) / n >= 0.75:
        side = "LONG" if lg > sh else "SHORT"
        warn = f"{max(lg, sh)} із {n} планів — {side}." + (f" Середня кореляція з BTC {str(avg).replace('.', ',')}: це майже одна спільна ставка на рух BTC." if avg is not None and avg >= 0.5 else " Залежність від BTC не перевірена.")
    return {"long": lg, "short": sh, "n": n, "avg_corr": avg, "warning": warn}


def brief_lines(market: Dict[str, Any], port: Optional[Dict[str, Any]] = None) -> List[str]:
    """«📊 РИНОК ЗАРАЗ»: перевага, 3–4 числа, активні плани, висновок."""
    if not market or market.get("bias") in (None, "UNKNOWN"):
        return ["📊 РИНОК ЗАРАЗ", "Даних для висновку замало."]
    out = ["📊 РИНОК ЗАРАЗ", f"Перевага: {BIAS_UA[market['bias']]}"]
    out += [f["text"] for f in market["facts"]]
    if port and port.get("n"):
        out.append(f"Активні плани: {port['long']} LONG / {port['short']} SHORT")
        if port.get("warning"):
            out.append(port["warning"])
    out.append({"LONG": "Висновок: ринок зараз більше підтримує LONG.", "SHORT": "Висновок: ринок зараз більше підтримує SHORT.",
                "MIXED": "Висновок: чіткої переваги немає."}[market["bias"]])
    return out

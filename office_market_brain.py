"""Market Brain: живий цикл ранньої переваги. Не «куди пішов BTC», а «де накопичується перевага ДО основного руху».

Стани (кожен з боком LONG/SHORT): ⚪ немає переваги → 🟡 накопичується → 🟠 зміщується → 🟢/🔴 підтверджено → ⚠️ вхід запізнілий;
також ⚠️ перевага слабшає і 🔄 можливий розворот. Кожна зміна стану має причину в цифрах, рівень підтвердження і рівень скасування.
Пам'ять: поточний стан + історія переходів зі знімком ознак на момент кожного переходу.
РЕЖИМ СПОСТЕРЕЖЕННЯ: модуль пише журнал станів, але нічого не шле й не змінює сигнали, поки дослідження (scripts/brain_study.py) на історії без
look-ahead не покаже, які ознаки справді передують рухам. Правила нижче — гіпотези з констант office_brain_features, а не доведена модель.
Чисті функції: на вхід — ознаки (office_brain_features.compute), на вихід — новий стан і, якщо стався перехід, запис про нього.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

import office_brain_features as bf

NEUTRAL = "NEUTRAL"
ETH_REL_PP = 0.3          # ETH слабший/сильніший за BTC за 60 хв щонайменше на стільки п.п. — ознака ризику (гіпотеза)
LATE_ATR_MULT = 1.0       # рух за рівнем підтвердження більший за стільки ATR(15m) — гнатися пізно
CONFIRM_STEPS = 2         # новий стан (крім скасування/підтвердження) має втриматись стільки перевірок поспіль
HISTORY_MAX = 200
STATES = ("NEUTRAL", "ACCUM", "SHIFT", "CONFIRMED", "LATE", "WEAKENING", "REVERSAL")
STATE_UA = {"NEUTRAL": "⚪ Переваги немає", "ACCUM": "🟡 Накопичується {s}", "SHIFT": "🟠 Перевага зміщується в {s}", "CONFIRMED": "{d} {s} підтверджено",
            "LATE": "⚠️ {s}: вхід уже запізнілий", "WEAKENING": "⚠️ Перевага {s} слабшає", "REVERSAL": "🔄 Можливий розворот у {s}"}


def name(state: str, side: Optional[str]) -> str:
    if state == "NEUTRAL" or not side:
        return STATE_UA["NEUTRAL"]
    return STATE_UA[state].format(s=side, d="🟢" if side == "LONG" else "🔴")


def _px(v: Any) -> str:
    x = bf._f(v)
    if x is None:
        return "—"
    return (f"{x:,.0f}" if abs(x) >= 1000 else f"{x:,.2f}" if abs(x) >= 10 else f"{x:.5g}").replace(",", " ").replace(".", ",")


def _pc(v: Any, nd: int = 1) -> str:
    x = bf._f(v)
    return "—" if x is None else f"{x:+.{nd}f}%".replace(".", ",").replace("-", "−")


# ------------------------------------------------------------------ докази
def evidence(f: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """Чесні лічильники доказів за кожну сторону; кожен доказ — з числами. Нема даних → доказу немає."""
    L: List[Dict[str, str]] = []
    S: List[Dict[str, str]] = []
    if not f.get("ok"):
        return {"LONG": L, "SHORT": S}
    su, sd = f.get("sweep_up"), f.get("sweep_down")
    if su:
        S.append({"key": "sweep", "text": f"Ліквідність зверху ({bf.LEVEL_UA.get(su['kind'], su['kind'])} {_px(su['level'])}) забрали: максимум {_px(su['extreme'])}, ціна повернулась до {_px(su['back_close'])}"})
    if sd:
        L.append({"key": "sweep", "text": f"Ліквідність знизу ({bf.LEVEL_UA.get(sd['kind'], sd['kind'])} {_px(sd['level'])}) забрали: мінімум {_px(sd['extreme'])}, ціна повернулась до {_px(sd['back_close'])}"})
    oi, p30, fu, ls = f.get("oi_30m"), f.get("price_30m"), f.get("funding_pct"), f.get("ls_ratio")
    if oi is not None and p30 is not None and oi >= bf.OI_BUILD_PCT and abs(p30) <= bf.PRICE_FLAT_PCT:
        crowd_long = (fu is not None and fu >= bf.FUNDING_CROWD_PCT) or (ls is not None and ls >= bf.LS_CROWD_HI)
        crowd_short = (fu is not None and fu <= -bf.FUNDING_CROWD_PCT) or (ls is not None and ls <= bf.LS_CROWD_LO)
        extra = (f"; фандинг {_pc(fu, 3)}" if fu is not None else "") + (f"; покупців/продавців {str(round(ls, 2)).replace('.', ',')}" if ls is not None else "")
        base = f"Відкритий інтерес за 30 хв {_pc(oi)}, а ціна {_pc(p30)}{extra}"
        if crowd_long and not crowd_short:
            S.append({"key": "crowd", "text": base + ": багато нових лонгів, ціна не росте"})
        elif crowd_short and not crowd_long:
            L.append({"key": "crowd", "text": base + ": багато нових шортів, ціна не падає"})
    # рівень втрачено / повернуто за останні 60 хв
    price, p60 = f.get("price"), f.get("price_60m")
    if price and p60 is not None:
        then = price / (1.0 + p60 / 100.0)
        for k, v in sorted((f.get("levels") or {}).items(), key=lambda kv: abs(kv[1] - price)):
            if abs(v / price - 1.0) * 100.0 > bf.LIQ_MAX_DIST_PCT:
                continue
            if then > v >= price:
                S.append({"key": "level", "text": f"Рівень {bf.LEVEL_UA.get(k, k)} {_px(v)} втрачено: година тому ціна була {_px(then)}, зараз {_px(price)}"})
                break
            if then < v <= price:
                L.append({"key": "level", "text": f"Рівень {bf.LEVEL_UA.get(k, k)} {_px(v)} повернуто: година тому ціна була {_px(then)}, зараз {_px(price)}"})
                break
    b = f.get("breadth")
    if b and b["n"]:
        if b["down"] / b["n"] >= bf.BREADTH_HI:
            S.append({"key": "breadth", "text": f"{b['down']} із {b['n']} великих монет нижчі, ніж година тому"})
        elif b["up"] / b["n"] >= bf.BREADTH_HI:
            L.append({"key": "breadth", "text": f"{b['up']} із {b['n']} великих монет вищі, ніж година тому"})
    e60 = f.get("eth_60m")
    if e60 is not None and p60 is not None:
        d = e60 - p60
        if d <= -ETH_REL_PP:
            S.append({"key": "eth", "text": f"ETH слабший за BTC на {abs(d):.1f} п.п. за годину".replace(".", ",")})
        elif d >= ETH_REL_PP:
            L.append({"key": "eth", "text": f"ETH сильніший за BTC на {abs(d):.1f} п.п. за годину".replace(".", ",")})
    return {"LONG": L, "SHORT": S}


def levels_for(side: str, f: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """(рівень підтвердження, рівень скасування) для сторони: SHORT — підтвердження нижче ціни (останній мінімум), скасування вище (максимум виносу)."""
    liq = f.get("liquidity") or {}
    if side == "SHORT":
        conf = f.get("swing_low") or ((liq.get("below") or [{}])[0].get("px"))
        inv = (f.get("sweep_up") or {}).get("extreme") or f.get("swing_high") or ((liq.get("above") or [{}])[-1].get("px"))
    else:
        conf = f.get("swing_high") or ((liq.get("above") or [{}])[0].get("px"))
        inv = (f.get("sweep_down") or {}).get("extreme") or f.get("swing_low") or ((liq.get("below") or [{}])[-1].get("px"))
    return bf._f(conf), bf._f(inv)


# ------------------------------------------------------------------ пам'ять і крок
def new_memory() -> Dict[str, Any]:
    return {"state": NEUTRAL, "side": None, "since": None, "confirm": None, "invalid": None, "n_side": 0, "keys": [], "pending": None, "history": [], "price0": None}


def _beyond(side: str, price: float, level: Optional[float], above_is_short: bool = False) -> bool:
    if level is None:
        return False
    return price < level if side == "SHORT" else price > level


def _raw(mem: Dict[str, Any], f: Dict[str, Any], ev: Dict[str, List[Dict[str, str]]]) -> Tuple[str, Optional[str], str, bool]:
    """(стан, сторона, пояснення, негайно). «Негайно» — без очікування CONFIRM_STEPS: скасування, підтвердження, запізнення."""
    price = f["price"]
    nL, nS = len(ev["LONG"]), len(ev["SHORT"])
    cur, cs = mem["state"], mem["side"]
    opp = "LONG" if cs == "SHORT" else "SHORT"
    if cur != NEUTRAL and cs:
        # скасування: ціна пішла за рівень, що ламає гіпотезу
        inv = mem.get("invalid")
        if inv is not None and _beyond(opp, price, inv):
            n_opp = len(ev[opp])
            if n_opp >= 2:
                return "REVERSAL", opp, f"ціна {_px(price)} за рівнем скасування {_px(inv)}, і за {opp} вже {n_opp} доказів", True
            return NEUTRAL, None, f"ціна {_px(price)} за рівнем скасування {_px(inv)}", True
        conf = mem.get("confirm")
        atr = f.get("atr15_pct")
        if cur in ("ACCUM", "SHIFT", "WEAKENING") and _beyond(cs, price, conf):
            return "CONFIRMED", cs, f"ціна {_px(price)} за рівнем підтвердження {_px(conf)}", True
        if cur in ("CONFIRMED", "LATE") and conf is not None and atr:
            moved = abs(price / conf - 1.0) * 100.0
            if _beyond(cs, price, conf) and moved > LATE_ATR_MULT * atr:
                return "LATE", cs, f"ціна пройшла {moved:.2f}% за рівнем {_px(conf)} (ATR 15 хв {atr:.2f}%)".replace(".", ","), True
            if _beyond(cs, price, conf):
                return cur, cs, "", False
    # за доказами
    for side, n, o in (("LONG", nL, nS), ("SHORT", nS, nL)):
        if n >= 2 and n - o >= 2:
            keys = {e["key"] for e in ev[side]}
            structural = bool(keys & {"sweep", "level"})
            if n >= 3 and structural:
                return "SHIFT", side, f"{n} доказів за {side}, проти {o}", False
            return "ACCUM", side, f"{n} доказів за {side}, проти {o}", False
    if cur in ("ACCUM", "SHIFT", "CONFIRMED", "LATE") and cs and len(ev[cs]) >= 1:
        return "WEAKENING", cs, f"доказів за {cs} лишилось {len(ev[cs])}", False
    if cur in ("WEAKENING", "REVERSAL") and cs and len(ev[cs]) >= 1:
        return cur, cs, "", False
    return NEUTRAL, None, "переваги немає", False


def step(mem: Dict[str, Any], f: Dict[str, Any], now: float) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Один крок живого циклу. Повертає (нова пам'ять, запис про перехід або None). Вхідна пам'ять не змінюється."""
    m = copy.deepcopy(mem)
    if not f.get("ok"):
        return m, None
    ev = evidence(f)
    state, side, why, now_ = _raw(m, f, ev)
    if state == m["state"] and side == m["side"]:
        m["pending"] = None
        m["n_side"] = len(ev[side]) if side else 0
        m["keys"] = [e["key"] for e in ev[side]] if side else []
        return m, None
    if not now_:
        p = m.get("pending")
        if p and p["state"] == state and p["side"] == side:
            p["count"] += 1
        else:
            m["pending"] = {"state": state, "side": side, "count": 1}
            return m, None
        if m["pending"]["count"] < CONFIRM_STEPS:
            return m, None
    prev = {"state": m["state"], "side": m["side"]}
    conf, inv = (levels_for(side, f) if side else (None, None))
    if m["side"] == side and side and state in ("CONFIRMED", "LATE", "WEAKENING"):
        conf, inv = m.get("confirm"), m.get("invalid")   # рівні гіпотези не «пливуть» услід за ціною
    reasons = [why] if why else []
    if side:
        reasons += [e["text"] for e in ev[side]][:4]
    tr = {"t": now, "from": prev, "to": {"state": state, "side": side}, "price": f["price"], "reasons": reasons, "confirm_level": conf, "invalid_level": inv,
          "n_long": len(ev["LONG"]), "n_short": len(ev["SHORT"]), "keys": [e["key"] for e in ev[side]] if side else [],
          "snapshot": {k: f.get(k) for k in ("price", "price_30m", "price_60m", "oi_30m", "oi_60m", "funding_pct", "ls_ratio", "breadth", "eth_60m", "atr15_pct",
                                                "sweep_up", "sweep_down", "swing_low", "swing_high")}}
    m.update(state=state, side=side, since=now, confirm=conf, invalid=inv, n_side=len(ev[side]) if side else 0,
             keys=tr["keys"], pending=None, price0=f["price"] if prev["state"] == NEUTRAL else m.get("price0"))
    m["history"] = (m["history"] + [tr])[-HISTORY_MAX:]
    return m, tr


# ------------------------------------------------------------------ повідомлення й антиспам
def message(tr: Dict[str, Any], btc_before: Optional[float] = None) -> str:
    """Коротко, простою мовою, з цифрами: було → стало → що саме змінилося → рівень підтвердження → рівень скасування."""
    to, fr = tr["to"], tr["from"]
    lines = [name(to["state"], to["side"]), "", f"Було: {name(fr['state'], fr['side'])}"]
    px = f"BTC: {_px(btc_before)} → {_px(tr['price'])}" if btc_before else f"BTC: {_px(tr['price'])}"
    lines.append(px)
    lines += [r[:1].upper() + r[1:] + ("" if r.endswith(".") else ".") for r in tr["reasons"]]
    side = to["side"]
    if side and tr.get("confirm_level") is not None and to["state"] in ("ACCUM", "SHIFT", "WEAKENING"):
        lines.append(f"Підтвердження {side}: BTC {'нижче' if side == 'SHORT' else 'вище'} {_px(tr['confirm_level'])}.")
    if side and tr.get("invalid_level") is not None and to["state"] != "NEUTRAL":
        lines.append(f"Скасування: BTC {'вище' if side == 'SHORT' else 'нижче'} {_px(tr['invalid_level'])}.")
    if to["state"] == "CONFIRMED" and tr.get("confirm_level") is not None:
        lines.append(f"{side} підтверджено, але гнатися за ціною пізно. Чекаємо повернення до {_px(tr['confirm_level'])}.")
    if to["state"] == "LATE":
        lines.append("Новий вхід за рухом не відкриваємо.")
    return "\n".join(lines)


def should_notify(tr: Optional[Dict[str, Any]], notified: Dict[str, Any], now: float, *, cooldown_sec: float = 900.0, per_hour: int = 6) -> Tuple[bool, str]:
    """Повідомляємо лише про суттєве: зміна стану (не NEUTRAL→NEUTRAL), скасування/розворот — одразу; однаковий перехід не частіше за cooldown;
    не більше per_hour повідомлень на годину. Дрібна зміна ціни сама по собі — не причина."""
    if not tr:
        return False, "перехід відсутній"
    key = f"{tr['to']['state']}|{tr['to']['side']}"
    recent = [t for t in notified.get("times", []) if now - t < 3600.0]
    urgent = tr["to"]["state"] in ("REVERSAL", "LATE") or (tr["to"]["state"] == "NEUTRAL" and tr["from"]["state"] in ("SHIFT", "CONFIRMED"))
    if not urgent and len(recent) >= per_hour:
        return False, f"ліміт {per_hour} на годину"
    if now - float((notified.get("last") or {}).get(key, 0.0)) < cooldown_sec and not urgent:
        return False, "такий самий перехід щойно був"
    if tr["to"]["state"] == "NEUTRAL" and tr["from"]["state"] in ("ACCUM", "WEAKENING", "NEUTRAL"):
        return False, "слабка перевага зникла — не причина писати"
    return True, "зміна стану"


def mark_notified(notified: Dict[str, Any], tr: Dict[str, Any], now: float) -> Dict[str, Any]:
    n = copy.deepcopy(notified) if notified else {}
    n.setdefault("last", {})[f"{tr['to']['state']}|{tr['to']['side']}"] = now
    n["times"] = [t for t in n.get("times", []) if now - t < 3600.0] + [now]
    return n


# ------------------------------------------------------------------ вже видані READY
def reassess(mem: Dict[str, Any], plans: List[Dict[str, Any]], *, strong_pp: float = 0.5) -> Dict[str, Any]:
    """Як новий контекст стосується активних READY. plan: {symbol, direction, entered(bool|None), rel_btc_pp(float|None)}.
    Проти контексту = протилежна сторона до стану ЗМІЩУЄТЬСЯ/ПІДТВЕРДЖЕНО/РОЗВОРОТ. Сильна власна слабкість монети (слабша за BTC ≥ strong_pp п.п.
    для SHORT / сильніша для LONG) лишає сценарій чинним. Без входу й проти контексту — кандидат на «сценарій скасовано, не входити»."""
    st, side = mem.get("state"), mem.get("side")
    active = st in ("SHIFT", "CONFIRMED", "REVERSAL") and side
    res = {"against": [], "with": [], "neutral": [], "own_strength": [], "would_cancel": []}
    for p in plans:
        d = str(p.get("direction") or "").upper()
        tag = p.get("symbol")
        if not active:
            res["neutral"].append(tag)
        elif d == side:
            res["with"].append(tag)
        else:
            rel = p.get("rel_btc_pp")
            strong = rel is not None and ((d == "SHORT" and rel <= -strong_pp) or (d == "LONG" and rel >= strong_pp))
            if strong:
                res["own_strength"].append(tag)
            else:
                res["against"].append(tag)
                if p.get("entered") is False:
                    res["would_cancel"].append(tag)
    return res


def reassess_message(mem: Dict[str, Any], prev_name: str, plans: List[Dict[str, Any]], r: Dict[str, Any]) -> Optional[str]:
    n = len(plans)
    if not n or not (r["against"] or r["own_strength"]):
        return None
    dirs = {str(p.get("direction")).upper() for p in plans}
    head = f"Із {n} активних {'/'.join(sorted(dirs))}:"
    lines = ["⚠️ КОНТЕКСТ ЗМІНИВСЯ", "", f"Було: {prev_name}", f"Зараз: {name(mem['state'], mem['side'])}", "", head]
    if r["against"]:
        lines.append(f"{len(r['against'])} проти нового контексту: " + ", ".join(r["against"]))
    if r["own_strength"]:
        lines.append(f"{len(r['own_strength'])} лишаються чинними через власний рух монети: " + ", ".join(r["own_strength"]))
    if r["would_cancel"]:
        lines.append("Входу ще не було — не входити: " + ", ".join(r["would_cancel"]))
    return "\n".join(lines)

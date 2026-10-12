"""Проста українська для карток радара (Telegram і Mini App). Лише подання: машинні коди (WATCH/BLOCKED/LONG/SHORT, card_id, enum) у БД не змінюються.

Правила мови: без «READY/WATCH/PAPER/LONG/SHORT/SL/TP» у головному тексті; технічний код — лише дрібним підписом «Технічно: …».
Навчальна угода = картка з paper-супроводом: ціна реальна, гроші й ордери — ні."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

LEVEL_UA = {
    "PDH": "максимум попереднього дня", "PDL": "мінімум попереднього дня", "PWH": "максимум минулого тижня", "PWL": "мінімум минулого тижня",
    "PMH": "максимум минулого місяця", "PML": "мінімум минулого місяця", "D1H": "денний максимум", "D1L": "денний мінімум", "W1H": "тижневий максимум", "W1L": "тижневий мінімум",
    "ASIA_H": "максимум азійської сесії", "ASIA_L": "мінімум азійської сесії", "LONDON_H": "максимум лондонської сесії", "LONDON_L": "мінімум лондонської сесії",
    "NEW_YORK_H": "максимум нью-йоркської сесії", "NEW_YORK_L": "мінімум нью-йоркської сесії", "H4SW": "локальний пік/впадина на 4-годинному графіку",
    "D1SW": "локальний пік/впадина на денному графіку", "W1SW": "локальний пік/впадина на тижневому графіку", "M15SW": "локальний пік/впадина на 15-хвилинному графіку",
    "H1SW": "локальний пік/впадина на годинному графіку", "ORIGIN_LOW": "початок руху",
}
LEVEL_SHORT = {"H4SW": "пік/впадина 4 год", "D1SW": "пік/впадина доби", "W1SW": "пік/впадина тижня", "M15SW": "пік/впадина 15 хв", "H1SW": "пік/впадина 1 год"}
FINAL_PAPER = ("SL", "TP1", "TP2", "TP3", "NO_ENTRY", "TIMEOUT", "INVALIDATED")


def level_ua(kind: Optional[str]) -> str:
    return LEVEL_UA.get(str(kind or ""), "ключовий рівень") if kind else "ключовий рівень"


def dir_ua(direction: str) -> str:
    return "Очікуємо падіння" if str(direction).upper() == "SHORT" else "Очікуємо зростання"


def dir_icon(direction: str) -> str:
    return "🔻" if str(direction).upper() == "SHORT" else "🟢"


def coin(symbol: str) -> str:
    """Біржовий тикер не перейменовуємо; 1000-контракти пояснюємо."""
    base = str(symbol or "").upper()
    base = base[:-4] if base.endswith("USDT") else base
    m = re.match(r"^(1000+)([A-Z0-9]+)$", base)
    if m:
        return f"{base} (контракт на {m.group(1)} токенів {m.group(2)})"
    return base


def num(x: Any, symbol: str = "") -> str:
    try:
        import office_ready_card as card

        return card._num(x, symbol)
    except Exception:  # noqa: BLE001
        return "—" if x is None else str(x)


def pct(v: float) -> str:
    return (f"{v:.2f}" if v < 10 else f"{v:.1f}").replace(".", ",")


def limit_note_ua(gate_reason: Optional[str]) -> str:
    g = str(gate_reason or "")
    if "3 стоп" in g or "стопи за добу" in g:
        return "для реальної торгівлі сьогодні вичерпано денний ліміт ризику (3 стопи)"
    if "READY за добу" in g or "кількості" in g:
        return "для реальної торгівлі сьогодні вичерпано денну кількість сигналів"
    if "кластер" in g or "ALT" in g or "ємність" in g:
        return "для реальної торгівлі зараз вичерпано обмеження сумарного ризику"
    return "для реальної торгівлі зараз діє обмеження ризику"


def plain_need(text: Optional[str]) -> Optional[str]:
    """Технічну умову Brain («бичаче закриття M15 вище X») — простою мовою."""
    if not text:
        return text
    t = str(text)
    t = re.sub(r"(бичаче|ведмеже)\s+закриття\s+M15", "закриття 15-хвилинної свічки", t)
    t = t.replace("закриття M15", "закриття 15-хвилинної свічки").replace("M15", "15-хвилинної свічки").replace("displacement", "різкий рух")
    return t


def kyiv(ts: Any) -> str:
    try:
        import office_ready_core as rc

        return rc.kyiv_stamp(float(ts)) + " (Київ)"
    except Exception:  # noqa: BLE001
        return "—"


def targets(c: Dict[str, Any]) -> List[Dict[str, Any]]:
    e, sl = c.get("entry"), c.get("sl")
    out = []
    if not e or not sl:
        return out
    risk = abs(e - sl)
    for i, k in enumerate(("tp1", "tp2", "tp3"), 1):
        p = c.get(k)
        if p:
            out.append({"n": i, "price": p, "pct": abs(p - e) / e * 100.0, "mult": abs(p - e) / risk if risk else None, "active": True})
    far = c.get("far_targets")
    if far:
        import json

        try:
            for f in json.loads(far):
                out.append({"n": f["n"], "price": f["p"], "pct": f["pct"], "mult": f.get("mult"), "active": False})
        except (ValueError, KeyError, TypeError):
            pass
    return sorted(out, key=lambda t: t["n"])


STOP_STATUS_UA = {"SL": "стоп спрацював", "TP1": "ціль 1 досягнута", "TP2": "ціль 2 досягнута", "TP3": "ціль 3 досягнута", "ENTERED": "угода ще відкрита", "WAITING_ENTRY": "чекаємо вхід",
                  "NO_ENTRY": "вхід не відбувся", "TIMEOUT": "строк вийшов", "INVALID": "не застосовний", "INVALIDATED": "сценарій скасовано до входу"}


def stops_view(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Три варіанти стопа для показу: ціна, ризик, відношення до цілей, обґрунтованість, пояснення, результат і висновок після стопа."""
    import json

    from office2 import stops as SV

    try:
        st = json.loads(c.get("stops_json") or "null")
        ev = json.loads(c.get("stop_eval") or "null") or {}
    except ValueError:
        return None
    if not st or not c.get("entry"):
        return None
    sym, e = c["symbol"], c["entry"]
    expl = SV.explain_ua(st)
    items = []
    for i, k in enumerate(("v1", "v2", "v3")):
        v = st.get(k)
        if not v:
            continue
        risk = abs(e - v["sl"])
        mult = {}
        for n_, key in ((1, "tp1"), (2, "tp2"), (3, "tp3")):
            p = c.get(key)
            mult[n_] = pct(abs(p - e) / risk) if p and risk else None
        r = ev.get(k) or {}
        after = (r.get("after") or {}).get("verdict")
        items.append({"key": k, "name": SV.NAMES[k], "sl": v["sl"], "sl_txt": num(v["sl"], sym), "risk_pct": pct(v.get("risk_pct") or 0.0), "justified": bool(v.get("justified")), "liq": v.get("liq"),
                      "mult1": mult[1], "mult2": mult[2], "mult3": mult[3], "explain": expl[i] if i < len(expl) else "", "status": STOP_STATUS_UA.get(r.get("status") or "", "ще не оцінено"),
                      "r_net": r.get("r_net"), "after": SV.VERDICT_UA.get(after) if after else None})
    rec = st.get("recommended")
    return {"items": items, "recommended": rec, "recommended_name": SV.NAMES.get(rec) if rec else None,
            "summary": (f"Структурно обґрунтований: {SV.NAMES[rec]}." if rec else "Жоден із трьох варіантів не пройшов усі перевірки (за екстремумом події, поза шумом, не біля очевидного рівня)."),
            "note": "Показуємо для порівняння. Фактична навчальна угода веде за стопом 1 (поточний); інші варіанти оцінюються окремо."}


def postmortem_view(c: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Розбір завершеної навчальної угоди простою мовою (дані з radar_watch.postmortem_card)."""
    import json

    try:
        pm = json.loads(c.get("postmortem_json") or "null")
    except ValueError:
        return None
    if not pm:
        return None
    af = pm.get("after_r") or {}
    after = [f"через {k.rstrip('h')} год: {v:+.1f}× ризику від ціни виходу" for k, v in af.items() if v is not None]
    return {"summary": pm.get("summary"), "flags": [f.get("t") for f in pm.get("flags") or []], "after": after, "note": pm.get("note"),
            "final": bool(pm.get("final")), "timing": pm.get("timing") or {}}


ZONE_PART_UA = {"OTE 62–79%": "відкат 62–79% імпульсу", "OB": "блок ордерів (OB)", "FVG": "незаповнений розрив (FVG)", "BPR": "перетин розривів (BPR)"}


def _dt(ts: Any) -> str:
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(float(ts), ZoneInfo("Europe/Kyiv")).strftime("%d.%m %H:%M")
    except Exception:  # noqa: BLE001
        return ""


def _a(x: Any) -> str:
    try:
        return f"{float(x):.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return ""


REASONS_VERSION = 3
MODULE_UA = {"HTF MN/W1/4D/3D/D1/H4/H1": "Старші таймфрейми", "OB / FVG / OTE (premium-discount)": "Положення зони в діапазоні", "Gerchik mirror level + люфт": "Дзеркальний рівень (Герчик)",
             "Wyckoff (spring/upthrust, тест)": "Вайкофф", "Bulkowski (формалізовані фігури)": "Фігури (Булковскі)", "regression channel": "Регресійний канал",
             "volume / taker-delta / CVD": "Обсяг і дельта", "Strong Candle (наша реалізація sc-ours-1)": "Сильна свічка", "M5/M1 тригер": "Мікро-підтвердження M5"}


def plural_bars(n: Any) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{n} " + ("бар" if n % 10 == 1 and n % 100 != 11 else "бари" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "барів")


def plain_fact(t: str, long_: bool) -> str:
    """Факти Brain простою мовою: без LONG/SHORT-жаргону, наукової нотації і крапки як десяткового роздільника."""
    t = re.sub(r"\s*[+-]?\d+(?:\.\d+)?e[+-]?\d+\s*", " ", str(t))
    up, dn = ("зростання", "падіння") if long_ else ("падіння", "зростання")
    t = t.replace("ПРОТИ LONG", "проти зростання").replace("ПРОТИ SHORT", "проти падіння").replace("ЗА LONG", "за зростання").replace("ЗА SHORT", "за падіння")
    t = t.replace("low ", "мінімум ").replace("high ", "максимум ")
    t = re.sub(r"(\d)\.(\d)", r"\1,\2", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def reasons_from_thesis(th: Dict[str, Any], direction: str, sym: str) -> Dict[str, Any]:
    """Пронумеровані ПРИЧИНИ з фактів сценарію Brain (рівень, подія, зсув структури, нога й зона, відкат, тригер, запас ходу, докази модулів). Кожна причина — лише те, що є в даних:
    немає факту — немає пункту. Суперечності (alignment/докази проти) — окремо. Спільне для Telegram і Mini App (формується на сервері один раз)."""
    long_ = str(direction).upper() != "SHORT"
    ev = th.get("event") or {}
    lvl, br, leg = th.get("level") or ev.get("level") or {}, th.get("break") or {}, th.get("leg") or {}
    seq = th.get("sequence") or []
    R: List[Dict[str, str]] = []

    def add(kind: str, text: str) -> None:
        if text:
            R.append({"kind": kind, "text": text})

    # 1) рівень і подія
    if ev.get("src") == "ORIGIN" and ev.get("origin"):
        o = ev["origin"]
        imp = o.get("impulse") or {}
        t = f"Початок руху: імпульс {_a(imp.get('size_atr'))} ATR ({_a(imp.get('size_pct'))}%)"
        if o.get("retrace") is not None:
            t += f", відкат {int(round(float(o['retrace']) * 100))}% імпульсу"
        if (o.get("attacks") or {}).get("n"):
            t += f", атак на рівень {o['attacks']['n']}"
        if o.get("compression"):
            t += ", є підтиснення"
        add("event", t + ".")
    elif lvl.get("p"):
        how = "повторний тест рівня" if ev.get("class") == "LATE_SWEEP" else "зняття ліквідності за рівнем"
        t = f"Рівень: {level_ua(lvl.get('kind'))} {num(lvl['p'], sym)} — {how}" + (f" {_dt(ev['ts'])}" if ev.get("ts") else "")
        if ev.get("extreme"):
            t += f" (екстремум {num(ev['extreme'], sym)})"
        pr = ev.get("prior") or {}
        if pr.get("closes_beyond"):
            t += f"; перед цим за {pr.get('bars')} барів — закриттів за рівнем: {pr['closes_beyond']}"
        add("event", t + ".")
    # 2) зсув структури
    if br.get("level"):
        add("structure", f"Зсув структури: закриття {'вище' if long_ else 'нижче'} {num(br['level'], sym)}" + (f" {_dt(br['ts'])}" if br.get("ts") else "")
            + (f", тіло свічки {_a(br['body_atr'])} ATR" if br.get("body_atr") else "") + (f", утримується {plural_bars(br['bars_held'])}" if br.get("bars_held") else "") + ".")
    # 3) нога й зона
    zn = th.get("entry_zone") or th.get("zone")
    if leg.get("from") and leg.get("to") and zn:
        parts = " + ".join(ZONE_PART_UA.get(x, x) for x in (th.get("zone_parts") or []))
        add("zone", f"Імпульс {num(leg['from'], sym)}→{num(leg['to'], sym)} ({_a(leg.get('atr'))} ATR); зона інтересу {num(min(zn), sym)}–{num(max(zn), sym)}" + (f": {parts}" if parts else "") + ".")
    # 4) відкат / тригер — лише підтверджені кроки послідовності
    for st in seq:
        step, val = str(st.get("step") or ""), st.get("value")
        if not st.get("ok") or not val:
            continue
        if step.startswith("ретрейс"):
            add("retrace", "Відкат у зону: " + plain_fact(val, long_) + ".")
        elif step.startswith("тригер"):
            add("trigger", "Підтвердження на 15 хв: " + plain_fact(val, long_) + ".")
    # 5) запас ходу
    tg = th.get("targets") or (th.get("preview") or {}).get("targets") or []
    if tg:
        bits = []
        for i, x in enumerate(tg[:2], 1):
            bits.append(f"ціль {i} {num(x.get('p'), sym)}" + (f" ({LEVEL_SHORT.get(x['kind']) or level_ua(x['kind'])})" if i == 1 and x.get("kind") else ""))
        add("room", "Запас ходу: " + "; ".join(bits) + ".")
    # 6) докази модулів (лише ті, що підтримують), далі суперечності
    for m in th.get("evidence") or []:
        if isinstance(m, dict) and (m.get("supports") or 0) > 0 and m.get("finding") and "—" != str(m.get("finding")).strip():
            add("evidence", f"{MODULE_UA.get(m.get('module'), m.get('module'))}: {plain_fact(m['finding'], long_).removeprefix('M5: ')}.")
    against = [plain_fact(m.get("text"), long_) for m in (th.get("alignment") or []) if isinstance(m, dict) and "ПРОТИ" in str(m.get("verdict", "")) and m.get("text")]
    against += [f"{MODULE_UA.get(m.get('module'), m.get('module'))}: {plain_fact(m['finding'], long_)}" for m in (th.get("evidence") or []) if isinstance(m, dict) and (m.get("supports") or 0) < 0 and m.get("finding")]
    inv = th.get("invalidation") or {}
    return {"v": REASONS_VERSION, "reasons": R, "against": against[:2], "wait": plain_need((th.get("need") or {}).get("text")),
            "cancel": (f"ціна закріпиться за {num(inv['price'], sym)} (екстремум події)" if inv.get("price") else None)}


def reasons_view(c: Dict[str, Any], limit: int = 5) -> Optional[Dict[str, Any]]:
    import json

    try:
        d = json.loads(c.get("reasons_json") or "null")
    except ValueError:
        return None
    if not d:
        return None
    rs = d.get("reasons") or []
    order = {"event": 0, "structure": 1, "zone": 2, "retrace": 3, "room": 4, "trigger": 5, "evidence": 6}
    top = sorted(rs, key=lambda r: order.get(r["kind"], 9))[:limit]
    return {"items": [{"n": i + 1, **r} for i, r in enumerate(top)], "extra": max(0, len(rs) - len(top)), "against": d.get("against") or [], "wait": d.get("wait"), "cancel": d.get("cancel")}


def present(c: Dict[str, Any]) -> Dict[str, Any]:
    """Усі готові до показу тексти картки (один раз на сервері: Telegram і Mini App показують однаково)."""
    blocked = c.get("kind") == "BLOCKED"
    armed = c.get("stage") == "ARMED"
    sym = c["symbol"]
    long_ = str(c["direction"]).upper() != "SHORT"
    if blocked:
        title, badge = "🎓 Навчальний сигнал", "Навчальна угода, без грошей"
        status = "умови входу підтверджені (навчальна угода)"
        todo = f"Нічого не робити. Це навчальна угода без грошей: {limit_note_ua(c.get('gate_reason'))}. Дивимось, чим закінчиться."
    else:
        title, badge = "👀 Спостерігаємо", "Спостереження"
        status = "ціна вже в зоні входу, чекаємо підтвердження" if armed else "чекаємо, поки ціна підійде до зони входу"
        todo = "Не входити. Система лише спостерігає. Якщо умови підтвердяться — з'явиться навчальна угода."
    why = f"Ціна працює біля рівня: {level_ua(c.get('level_kind'))}" + (f" {num(c['level_price'], sym)}" if c.get("level_price") else "")
    ps = c.get("paper_status") or ""
    paper = {"": "ще не оцінено", "WAITING_ENTRY": "чекаємо, поки ціна дійде до входу", "ENTERED": "навчальна угода відкрита, ціна пішла від входу",
             "TP1": "ціль 1 досягнута", "TP2": "ціль 2 досягнута", "TP3": "ціль 3 досягнута", "SL": "стоп спрацював", "NO_ENTRY": "ціна не дійшла до входу — угода не відкрилась",
             "TIMEOUT": "строк вийшов", "INVALIDATED": "сценарій скасовано до входу — позиція не відкривалась"}.get(ps, ps)
    res = None
    if c.get("r_net") is not None and ps in ("SL", "TP1", "TP2", "TP3", "ENTERED"):
        res = f"умовний результат {c['r_net']:+.2f}".replace(".", ",") + f" від ризику (≈ {c['r_net'] * 10:+.1f} $ при ризику 10 $, з комісіями)".replace(".", ",")
    e, sl = c.get("entry"), c.get("sl")
    return {"title": title, "badge": badge, "status": status, "todo": todo, "why": why, "need": plain_need(c.get("need_text")), "dir": dir_ua(c["direction"]), "icon": dir_icon(c["direction"]),
            "coin": coin(sym), "plan_ok": bool(c.get("plan_ok")), "reject": c.get("reject"), "zone": (num(c["zone_lo"], sym) + "–" + num(c["zone_hi"], sym)) if c.get("zone_lo") and c.get("zone_hi") else None,
            "entry": num(e, sym) if e else None, "sl": num(sl, sym) if sl else None, "sl_pct": pct(abs(sl - e) / e * 100.0) if e and sl else None,
            "targets": [dict(t, price_txt=num(t["price"], sym), pct_txt=pct(t["pct"]), mult_txt=(pct(t["mult"]) if t.get("mult") else None)) for t in targets(c)],
            "expires": kyiv(c.get("expires_ts")), "paper": paper, "result": res, "entry_note": c.get("entry_note"),
            "stops": stops_view(c), "plan": reasons_view(c), "postmortem": postmortem_view(c), "tech": f"{c.get('kind')} · {c['direction']} · {c.get('stage')}", "limit_note": limit_note_ua(c.get("gate_reason")) if blocked else None, "long": long_}


def card_url(card_id: str, base_url: str = "https://ai-office-miniapp.onrender.com") -> str:
    """Canonical deep link to this exact radar card, not the generic symbol chart."""
    from urllib.parse import quote

    return base_url.rstrip("/") + "/v2?tab=radar&card=" + quote(link_id(card_id), safe="")


def _limit_short(gate_reason: Optional[str]) -> str:
    g = str(gate_reason or "")
    if "3 стоп" in g or "стопи за добу" in g:
        return "денний ліміт 3 стопи"
    if "READY за добу" in g or "кількості" in g:
        return "денна кількість сигналів вичерпана"
    if "кластер" in g or "ALT" in g or "ємність" in g:
        return "ліміт сумарного ризику"
    return "діє обмеження ризику"


def _stop_line(p: Dict[str, Any]) -> tuple:
    """(рядок стопа, чи є обґрунтований стоп). У Telegram — лише рекомендований стоп; немає такого — чесне попередження."""
    st = p.get("stops") or {}
    rec = next((x for x in st.get("items") or [] if x["key"] == st.get("recommended")), None) if st.get("recommended") else None
    if rec:
        return f"Стоп: {rec['sl_txt']} (−{rec['risk_pct']}%), структурно обґрунтований.", True
    if st.get("items"):
        return "Стоп: безпечний стоп не підтверджений.", False
    return (f"Стоп: {p['sl']} (−{p['sl_pct']}%)." if p.get("sl") else "Стоп не розраховано."), None


def card_text(c: Dict[str, Any], base_url: str = "https://ai-office-miniapp.onrender.com") -> str:
    """Підпис картки Telegram (≤1024, щоб лінк на картку не обрізався): монета · напрям · статус → пронумеровані ПРИЧИНИ (лише підтверджені факти) → чекаємо → вхід/стоп/цілі →
    скасування → висновок → лінк. Три варіанти стопа й усі докази — у картці Mini App."""
    p = present(c)
    learning = c.get("kind") == "BLOCKED"
    coin_short = p["coin"].split(" ")[0]
    status = "навчальна угода" if learning else "спостереження"
    plan = p.get("plan") or {"items": [], "extra": 0, "against": [], "wait": None, "cancel": None}
    stop_txt, stop_ok = _stop_line(p)
    act = [x for x in p["targets"] if x["active"]]
    tail: List[str] = []
    if learning:
        entry_bits = []
        if p.get("zone"):
            entry_bits.append("зона " + p["zone"])
        if p.get("entry"):
            entry_bits.append("ціна підтвердження " + p["entry"])
        if entry_bits:
            tail.append("Вхід (умовний): " + ", ".join(entry_bits) + ".")
        tail.append(stop_txt)
        if act:
            tail.append("Цілі: " + " / ".join(f"{x['price_txt']}" + (f" (≈{x['mult_txt']}×)" if x.get("mult_txt") else "") for x in act[:2]) + ".")
        if plan.get("cancel"):
            tail.append("Скасування: " + plan["cancel"] + ".")
        if plan.get("against"):
            tail.append("Проти: " + plan["against"][0] + ".")
    else:
        # СПОСТЕРЕЖЕННЯ: зона інтересу ≠ підтвердження ≠ точка входу ≠ стоп. Вхід, стоп і цілі тут НЕ показуються: вони з'являться лише після підтвердження закритою свічкою.
        if p.get("zone"):
            tail.append("Зона інтересу: " + p["zone"] + ".")
        tail.append("Потрібне підтвердження: " + (plan.get("wait") or p.get("need") or "закриття свічки за умовою методики") + ".")
        if plan.get("cancel"):
            tail.append("Скасування: " + plan["cancel"] + ".")
        if plan.get("against"):
            tail.append("Проти: " + plan["against"][0] + ".")
        tail.append("Вхід, стоп і цілі — після підтвердження.")
    if learning:
        concl = "НАВЧАЛЬНА УГОДА — реальний вхід не дозволений" + (f" ({_limit_short(c.get('gate_reason'))})" if c.get("gate_reason") else "") + "."
    else:
        concl = "СПОСТЕРІГАЄМО — вхід не підтверджений, входити не можна."
    if learning and stop_ok is False:
        concl = concl.rstrip(".") + ". Безпечний стоп не підтверджений. Вхід не дозволений."
    tail_end = ["Висновок: " + concl, f"⏳ До {p['expires']}", "📊 Відкрити графік:", card_url(c["card_id"], base_url)]
    items = list(plan["items"])

    def build(rs: List[Dict[str, Any]], cut: int) -> str:
        head = [f"{coin_short} · {p['dir'].lower()} · {status}", "ПЛАН І ПРИЧИНИ:"]
        if rs:
            head += [f"{i + 1}. " + (r["text"] if len(r["text"]) <= cut else r["text"][:cut - 1].rstrip() + "…") for i, r in enumerate(rs)]
            omitted = plan.get("extra", 0) + len(items) - len(rs)
            if omitted:
                head.append(f"+ ще підтверджень: {omitted} — у картці.")
        else:
            head.append("Підтверджених причин у даних поки немає — не вигадуємо.")
        return "\n".join(head + tail + tail_end)

    for n in range(len(items), 2, -1):                     # спершу зберігаємо причини, потім скорочуємо їхній текст
        for cut in (170, 130):
            txt = build(items[:n], cut)
            if len(txt) <= 1024:
                return txt
    return build(items[:3], 90)[:1024]


def link_id(card_id: str) -> str:
    """Короткий посилальний ідентифікатор без «|» і «%»: W|O2|ab12 → W-ab12 (на сервері розпізнається й старий формат)."""
    m = re.match(r"^([WB])\|(?:O2\|)?([0-9a-f]{6,})$", str(card_id))
    return f"{m.group(1)}-{m.group(2)}" if m else str(card_id)


def parse_link_id(token: str) -> List[str]:
    """Можливі card_id за посиланням: переживає подвійне кодування, старий формат, замінені роздільники."""
    from urllib.parse import unquote

    t = str(token or "").strip()
    for _ in range(3):
        u = unquote(t)
        if u == t:
            break
        t = u
    cands = [t]
    m = re.match(r"^(?:([WB])[-_~:|.]?)?(?:O2[-_~:|.])?([0-9a-fA-F]{6,})$", t)
    if m:
        hx = m.group(2).lower()
        for k in ([m.group(1)] if m.group(1) else ["W", "B"]):
            cands.append(f"{k}|O2|{hx}")
    return list(dict.fromkeys(cands))


def followup_text(c: Dict[str, Any]) -> str:
    p = present(c)
    parts = {"ENTERED": "ціна дійшла до входу — навчальна угода відкрита (без грошей)", "TP1": "ціль 1 досягнута", "TP2": "ціль 2 досягнута", "TP3": "ціль 3 досягнута",
             "SL": "стоп спрацював", "NO_ENTRY": "ціна так і не дійшла до входу — навчальна угода не відкрилась", "TIMEOUT": "строк вийшов", "INVALIDATED": "сценарій скасовано до входу — навчальна угода не відкривалась"}
    s = "; ".join(parts.get(m, m) for m in c["_new"])
    tail = f" {p['result']}." if p.get("result") and any(m in ("SL", "TP1", "TP2", "TP3") for m in c["_new"]) else ""
    return f"🎓 {p['coin'].split(' ')[0]}: {s}.{tail} Навчальна угода, не ордер."

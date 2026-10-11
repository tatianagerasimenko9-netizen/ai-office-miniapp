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
FINAL_PAPER = ("SL", "TP1", "TP2", "TP3", "NO_ENTRY", "TIMEOUT")


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
                  "NO_ENTRY": "вхід не відбувся", "TIMEOUT": "строк вийшов", "INVALID": "не застосовний"}


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
             "TIMEOUT": "строк вийшов"}.get(ps, ps)
    res = None
    if c.get("r_net") is not None and ps in ("SL", "TP1", "TP2", "TP3", "ENTERED"):
        res = f"умовний результат {c['r_net']:+.2f}".replace(".", ",") + f" від ризику (≈ {c['r_net'] * 10:+.1f} $ при ризику 10 $, з комісіями)".replace(".", ",")
    e, sl = c.get("entry"), c.get("sl")
    return {"title": title, "badge": badge, "status": status, "todo": todo, "why": why, "need": plain_need(c.get("need_text")), "dir": dir_ua(c["direction"]), "icon": dir_icon(c["direction"]),
            "coin": coin(sym), "plan_ok": bool(c.get("plan_ok")), "reject": c.get("reject"), "zone": (num(c["zone_lo"], sym) + "–" + num(c["zone_hi"], sym)) if c.get("zone_lo") and c.get("zone_hi") else None,
            "entry": num(e, sym) if e else None, "sl": num(sl, sym) if sl else None, "sl_pct": pct(abs(sl - e) / e * 100.0) if e and sl else None,
            "targets": [dict(t, price_txt=num(t["price"], sym), pct_txt=pct(t["pct"]), mult_txt=(pct(t["mult"]) if t.get("mult") else None)) for t in targets(c)],
            "expires": kyiv(c.get("expires_ts")), "paper": paper, "result": res, "entry_note": c.get("entry_note"),
            "stops": stops_view(c), "tech": f"{c.get('kind')} · {c['direction']} · {c.get('stage')}", "limit_note": limit_note_ua(c.get("gate_reason")) if blocked else None, "long": long_}


def card_text(c: Dict[str, Any], base_url: str = "https://ai-office-miniapp.onrender.com") -> str:
    from urllib.parse import quote

    p = present(c)
    L = [f"{p['title']} — без реальних грошей", f"{p['icon']} {p['dir']} · {p['coin']}", f"Статус: {p['status']}.", f"Що робити: {p['todo']}", "", p["why"] + "."]
    if p.get("need") and not c.get("kind") == "BLOCKED":
        L.append(f"Чекаємо: {p['need']}")
    if p["zone"]:
        L.append(f"Зона входу: {p['zone']}")
    L.append(f"Вхід (навчальний): {p['entry']}" + (f" — {p['entry_note']}" if p.get("entry_note") else ""))
    L.append(f"Стоп (якщо ідея не спрацювала): {p['sl']} (−{p['sl_pct']}%)")
    for t in p["targets"]:
        if t["active"]:
            L.append(f"Ціль {t['n']}: {t['price_txt']} (+{t['pct_txt']}%; ≈{t['mult_txt']}× розміру стопа)")
        else:
            L.append(f"Ціль {t['n']}: {t['price_txt']} (+{t['pct_txt']}%) — далека, у навчальному результаті не враховуємо")
    sv = p.get("stops")
    if sv:
        L.append("")
        L.append("Три варіанти стопа (для порівняння):")
        for it in sv["items"]:
            L.append(f"• {it['name']}: {it['sl_txt']} (−{it['risk_pct']}%){' ✅ обґрунтований' if it['justified'] else ' ⚠️ ' + ('біля очевидного рівня' if it['liq'] else 'сумнівний')}")
        L.append(sv["summary"])
        L.append("")
    L.append(f"⏳ Діє до {p['expires']}")
    L.append("Графік і результат: " + base_url.rstrip("/") + "/v2?tab=radar&card=" + quote(link_id(c["card_id"]), safe=""))
    L.append(f"Технічно: {p['tech']}")
    return "\n".join(L)


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
             "SL": "стоп спрацював", "NO_ENTRY": "ціна так і не дійшла до входу — навчальна угода не відкрилась", "TIMEOUT": "строк вийшов"}
    s = "; ".join(parts.get(m, m) for m in c["_new"])
    tail = f" {p['result']}." if p.get("result") and any(m in ("SL", "TP1", "TP2", "TP3") for m in c["_new"]) else ""
    return f"🎓 {p['coin'].split(' ')[0]}: {s}.{tail} Навчальна угода, не ордер."

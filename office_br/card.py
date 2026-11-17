"""Telegram-картка B&R · TEST: явно тестова, окрема нумерація «B&R-№», не плутається з основним Office2 («AI Office · №N»)."""
from __future__ import annotations

import json
from typing import Any, Dict


def _n(x: float, sym: str) -> str:
    try:
        from office_price_format import format_px

        return format_px(float(x), sym).replace(".", ",")
    except Exception:  # noqa: BLE001
        return f"{float(x):.6g}".replace(".", ",")


def tag(seq: Any) -> str:
    return f"B&R-{int(seq)}" if seq else "B&R"


TD_TAG = "#ТЕСТ"


def is_td(row: Dict[str, Any]) -> bool:
    return str(row.get("sig_id", "")).startswith(("TD|", "SW|"))


STRATS = {"TD": ("ІНТРАДЕЙ", "🟨", "#ffd500", "#2a2200", "15 хв · угоди до 2 діб"), "SW": ("СВІНГ", "🟦", "#0057b7", "#ffffff", "4 год · угоди до 10 діб")}


def strat(row: Dict[str, Any]):
    """(назва, емодзі, колір шапки, колір тексту на шапці, підпис) за префіксом sig_id: TD → ІНТРАДЕЙ, SW → СВІНГ."""
    return STRATS.get(str(row.get("sig_id", "")).split("|", 1)[0], STRATS["TD"])


def is_swing(row: Dict[str, Any]) -> bool:
    return str(row.get("sig_id", "")).startswith("SW|")


def hold_hours(row: Dict[str, Any]) -> int:
    """Скільки тримати: ІНТРАДЕЙ — до 48 год, СВІНГ — до 10 діб."""
    return 240 if is_swing(row) else 48


def hold_text(row: Dict[str, Any]) -> str:
    return "до 10 діб" if is_swing(row) else "до 48 год"


def head(row: Dict[str, Any]) -> str:
    """Префікс повідомлень: «B&R LIVE · B&R-n» або «ІНТРАДЕЙ №n» / «СВІНГ №n»."""
    return f"{strat(row)[0]} №{int(row['seq'])}" if is_td(row) else f"B&R LIVE · B&R-{row['seq']}"


def _td_hyp(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("hyp_json")
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:  # noqa: BLE001
        return {}


def cluster_line(row: Dict[str, Any]) -> str | None:
    """Скільки інших монет дали сигнал у той самий бік тієї ж години (один рух, ризик складається). Немає даних або 0 — рядка немає."""
    c = _td_hyp(row).get("cluster") or {}
    try:
        n = int(c.get("n") or 0)
    except Exception:  # noqa: BLE001
        return None
    if n < 1: return None
    word = "монета" if n % 10 == 1 and n % 100 != 11 else ("монети" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "монет")
    verb = "дала" if n % 10 == 1 and n % 100 != 11 else "дали"
    syms = ", ".join(c.get("syms") or [])
    return f"Ще {n} {word}" + (f" ({syms})" if syms else "") + f" {verb} сигнал у той самий бік цієї години. Це один рух, ризик складається."


def warn_line(row: Dict[str, Any]) -> str | None:
    """Попередження: «Слабкий сигнал» (ГІПОТЕЗА, історія 2024-2026; hyp['warn']) або «Обережно» (hyp['caution'] — напр. акції в СВІНГу: історії лише ~10 міс.). Немає — рядка немає."""
    h = _td_hyp(row)
    w = [str(x) for x in (h.get("warn") or []) if x]
    c = [str(x) for x in (h.get("caution") or []) if x]
    if w:
        return "Слабкий сигнал: " + "; ".join(w + c)
    return ("Обережно: " + "; ".join(c)) if c else None


def td_size(row: Dict[str, Any]) -> float:
    """Сума позиції в USDT (без плеча), щоб стоп коштував рівно $10: 10 / відстань до стопа."""
    entry, sl = float(row["entry"]), float(row["sl"])
    return 10.0 * entry / abs(entry - sl) if entry != sl else 0.0


def usd_fmt(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def build_td_card(row: Dict[str, Any]) -> str:
    """Проста картка TD: вхід, стоп, ціль у ціні, % і $ (при ризику $10 на угоду). Без службових термінів."""
    sym, d = row["symbol"], row["direction"]
    entry, sl = float(row["entry"]), float(row["sl"])
    risk = abs(entry - sl)
    tg = json.loads(row["targets_json"]) if isinstance(row.get("targets_json"), str) else row.get("targets") or []
    pc = lambda p: f"{abs(p - entry) / entry * 100:.2f}".replace(".", ",")
    hy = _td_hyp(row)
    L = [
        f"{strat(row)[1]} {strat(row)[0]} №{int(row['seq'])} · {sym} {'▲ LONG' if d == 'LONG' else '▼ SHORT'}",
        f"💰 Сума ${usd_fmt(td_size(row))}",
        f"🟡 Вхід {_n(entry, sym)} (ліміт)",
        f"🔴 Стоп {_n(sl, sym)} · −{pc(sl)}% = −$10",
    ]
    for t in tg[:1]:
        usd = 10 * abs(float(t["p"]) - entry) / risk if risk > 0 else 0.0
        L.append(f"🟢 Ціль {_n(t['p'], sym)} · +{pc(t['p'])}% = +${usd:.0f} (ліміт)")
    wl = warn_line(row)
    if wl: L.append("⚠️ " + wl.split(" (", 1)[0])
    n = (hy.get("cluster") or {}).get("n") or 0
    if n:
        syms = ", ".join((hy.get("cluster") or {}).get("syms") or [])
        word = "монета" if n % 10 == 1 and n % 100 != 11 else ("монети" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "монет")
        L.append(f"➕ Ще {n} {word}" + (f" ({syms})" if syms else "") + " у той самий бік — це один рух")
    if hy.get("why"): L.append("📌 " + str(hy["why"]))
    L.append("⏱ тримати " + str(hy.get("hold") or hold_text(row)))
    L.append(TD_TAG)
    return "\n".join(L)


def r_levels(row: Dict[str, Any]) -> list:
    """Ціни, на яких угода має +1R/+2R/+3R (від входу, за відстанню до стопа): лише орієнтири; справжня ціль — окремий рядок. ІНТРАДЕЙ ціль 3R → показуємо +1R, +2R; СВІНГ ціль 6R → +1R, +2R, +3R (🔒 на +2R = можна беззбиток)."""
    try:
        e, sl = float(row["entry"]), float(row["sl"]); risk = abs(e - sl)
        if risk <= 0: return []
        side = 1 if row["direction"] == "LONG" else -1
        top = 3 if is_swing(row) else 2
        return [(k, e + side * k * risk) for k in range(1, top + 1)]
    except Exception:  # noqa: BLE001
        return []


def build_td_caption_html(row: Dict[str, Any]) -> str:
    """Підпис під картинкою (HTML): назва, вхід/стоп/ціль стовпчиком із кружечками (ціни копіюються дотиком), «ще монети», скільки тримати, #ТЕСТ.
    Попередження «слабкий сигнал», сума та $/% — на картинці, не дублюються."""
    import html, re
    hy = _td_hyp(row); sym, d = row["symbol"], row["direction"]
    plain = lambda x: re.sub(r"[\s\u00a0\u202f]", "", _n(x, sym)).replace(",", ".")
    tg = json.loads(row["targets_json"]) if isinstance(row.get("targets_json"), str) else row.get("targets") or []
    L = [f"{strat(row)[1]} <b>{html.escape(strat(row)[0])} №{int(row['seq'])}</b> · {html.escape(sym)} {'▲ LONG' if d == 'LONG' else '▼ SHORT'}",
         f"🟡 вхід  <code>{plain(row['entry'])}</code> (ліміт)",
         f"🔴 стоп  <code>{plain(row['sl'])}</code>"]
    if tg: L.append(f"🟢 ціль  <code>{plain(tg[0]['p'])}</code> (ліміт)")
    lv = r_levels(row)
    if lv: L.append("📍 орієнтири: " + " · ".join(f"+{k}R <code>{plain(p)}</code>" + (" 🔒 беззбиток" if k == 2 and is_swing(row) else "") for k, p in lv))
    n = (hy.get("cluster") or {}).get("n") or 0
    if n:
        syms = ", ".join((hy.get("cluster") or {}).get("syms") or [])
        word = "монета" if n % 10 == 1 and n % 100 != 11 else ("монети" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "монет")
        L.append(f"➕ Ще {n} {word}" + (f" ({html.escape(syms)})" if syms else "") + " у той самий бік — це один рух")
    if hy.get("why"): L.append("📌 " + html.escape(str(hy["why"])))
    L.append("⏱ тримати " + html.escape(str(hy.get("hold") or hold_text(row))))
    L.append(TD_TAG)
    return "\n".join(L)


def build_caption(row: Dict[str, Any], v2_line: str | None = None):
    """(текст, parse_mode) підпису під зображенням: для ІНТРАДЕЙ/СВІНГ — HTML, для B&R — як було."""
    if is_td(row):
        return build_td_caption_html(row), "HTML"
    return build_card(row, v2_line), None


def build_card(row: Dict[str, Any], v2_line: str | None = None) -> str:
    if is_td(row):
        return build_td_card(row)
    sym, d = row["symbol"], row["direction"]
    long_ = d == "LONG"
    entry, sl = float(row["entry"]), float(row["sl"])
    risk = abs(entry - sl)
    tg = json.loads(row["targets_json"]) if isinstance(row.get("targets_json"), str) else row.get("targets") or []
    pc = lambda p: f"{abs(p - entry) / entry * 100:.2f}".replace(".", ",")
    rr = lambda p: f"{abs(p - entry) / risk:.2f}".replace(".", ",") if risk > 0 else "—"
    L = [
        f"B&R LIVE · {tag(row.get('seq'))} · {sym} · {d}",
        f"Пробій: {_n(row['level'], sym)} — закриття {'вище' if long_ else 'нижче'} підтверджено",
        f"🟡 ВХІД {_n(entry, sym)}",
        f"🔴 SL {_n(sl, sym)} (−{pc(sl)}%)",
    ]
    for i, t in enumerate(tg[:3], 1):
        L.append(f"🟢 TP{i}  {_n(t['p'], sym)}  (+{pc(t['p'])}% · {rr(t['p'])}R){' · ' + t['src'] if t.get('src', '').startswith('R') else ''}")
    L.append(f"❌ Скасування: закриття {'нижче' if long_ else 'вище'} {_n(row['level'], sym)} до входу")
    if v2_line:
        L.append(v2_line)
    L.append("⚠️ Replay V1/V2 збитковий · тільки ручне рішення. Office не відкриває ордерів.")
    return "\n".join(L)


def event_text(row: Dict[str, Any], level: str, price: Any = None) -> str:
    names = {"ENTRY": "вхід досягнуто", "TP1": "TP1 досягнуто", "TP2": "TP2 досягнуто", "TP3": "TP3 досягнуто", "SL": "стоп-лосс", "CANCEL": "скасовано"}
    px = f" ({_n(price, row['symbol'])})" if price is not None else ""
    return f"{head(row)} · {row['symbol'].replace('USDT', '')} {row['direction']}: {names.get(level, level)}{px}"


def reminder_text(row: Dict[str, Any], level: str) -> str:
    """Price-triggered manual-action prompt, never an assertion of an executed order."""
    base = f"{head(row)} · {row['symbol'].replace('USDT', '')} {row['direction']}"
    tag_ = (" " + TD_TAG) if is_td(row) else ""
    actions = {
        "ENTRY": "🟡 Ціну входу торкнуто",
        "TP1": "🟢 TP1 досягнуто",
        "TP2": "🟢 TP2 досягнуто",
        "TP3": "🟢 TP3 досягнуто",
        "SL": "🔴 SL досягнуто",
    }
    return base + " · " + actions.get(level, level) + tag_

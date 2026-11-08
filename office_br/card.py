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


TD_TAG = "#ЗверхуВниз #ТЕСТ"


def is_td(row: Dict[str, Any]) -> bool:
    return str(row.get("sig_id", "")).startswith("TD|")


def head(row: Dict[str, Any]) -> str:
    """Префікс повідомлень: «B&R LIVE · B&R-n» або «ЗВЕРХУ ВНИЗ ТЕСТ · №n»."""
    return f"ЗВЕРХУ ВНИЗ ТЕСТ · №{int(row['seq'])}" if is_td(row) else f"B&R LIVE · B&R-{row['seq']}"


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


def build_td_card(row: Dict[str, Any]) -> str:
    """Проста картка «Зверху вниз»: вхід, стоп, ціль у ціні, % і $ (при ризику $10 на угоду). Без службових термінів."""
    sym, d = row["symbol"], row["direction"]
    entry, sl = float(row["entry"]), float(row["sl"])
    risk = abs(entry - sl)
    tg = json.loads(row["targets_json"]) if isinstance(row.get("targets_json"), str) else row.get("targets") or []
    pc = lambda p: f"{abs(p - entry) / entry * 100:.2f}".replace(".", ",")
    L = [
        f"🧪 ТЕСТ · ЗВЕРХУ ВНИЗ · №{int(row['seq'])}",
        f"{sym} · {'▲ LONG' if d == 'LONG' else '▼ SHORT'}",
        f"🟡 Вхід {_n(entry, sym)}",
        f"🔴 Стоп {_n(sl, sym)} (−{pc(sl)}% · −$10)",
    ]
    for t in tg[:1]:
        usd = 10 * abs(float(t["p"]) - entry) / risk if risk > 0 else 0.0
        L.append(f"🟢 Ціль {_n(t['p'], sym)} (+{pc(t['p'])}% · +${usd:.0f} при ризику $10)")
    cl = cluster_line(row)
    if cl: L.append("⚠️ " + cl)
    L.append("⏱ Тримати до цілі або стопа, максимум 48 год. Стоп виставити на біржі одразу після входу.")
    L.append("Тестова стратегія · ручне рішення · Office не відкриває ордерів.")
    L.append(TD_TAG)
    return "\n".join(L)


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

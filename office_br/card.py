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


def build_card(row: Dict[str, Any]) -> str:
    sym, d = row["symbol"], row["direction"]
    long_ = d == "LONG"
    entry, sl = float(row["entry"]), float(row["sl"])
    risk = abs(entry - sl)
    tg = json.loads(row["targets_json"]) if isinstance(row.get("targets_json"), str) else row.get("targets") or []
    pc = lambda p: f"{abs(p - entry) / entry * 100:.2f}".replace(".", ",")
    rr = lambda p: f"{abs(p - entry) / risk:.2f}".replace(".", ",") if risk > 0 else "—"
    L = [
        f"{tag(row.get('seq'))} · {sym} · {d}",
        f"Пробій: {_n(row['level'], sym)} — закриття {'вище' if long_ else 'нижче'} підтверджено",
        f"🟡 ВХІД {_n(entry, sym)}",
        f"🔴 SL {_n(sl, sym)} (−{pc(sl)}%)",
    ]
    for i, t in enumerate(tg[:3], 1):
        L.append(f"🟢 TP{i}  {_n(t['p'], sym)}  (+{pc(t['p'])}% · {rr(t['p'])}R){' · ' + t['src'] if t.get('src', '').startswith('R') else ''}")
    L.append(f"❌ Скасування: закриття {'нижче' if long_ else 'вище'} {_n(row['level'], sym)} до входу")
    return "\n".join(L)


def event_text(row: Dict[str, Any], level: str, price: Any = None) -> str:
    names = {"ENTRY": "вхід досягнуто", "TP1": "TP1 досягнуто", "TP2": "TP2 досягнуто", "TP3": "TP3 досягнуто", "SL": "стоп-лосс", "CANCEL": "скасовано"}
    px = f" ({_n(price, row['symbol'])})" if price is not None else ""
    return f"B&R LIVE · {tag(row.get('seq'))} · {row['symbol'].replace('USDT', '')} {row['direction']}: {names.get(level, level)}{px}"


def reminder_text(row: Dict[str, Any], level: str) -> str:
    """Price-triggered manual-action prompt, never an assertion of an executed order."""
    base = f"B&R LIVE · {tag(row.get('seq'))} · {row['symbol'].replace('USDT', '')} {row['direction']}"
    actions = {
        "ENTRY": "🟡 Ціна торкнулася планового входу. Якщо ти відкрила позицію вручну — підтвердь це в Mini App. Торкання ≠ виконання ордера.",
        "TP1": "🟢 TP1 досягнуто. Якщо позиція відкрита: розглянь фіксацію 30% вручну. Після фактичної фіксації — розглянь перенесення SL у беззбиток. Office нічого не виконував.",
        "TP2": "🟢 TP2 досягнуто. Якщо позиція відкрита: розглянь фіксацію ще 40% вручну. Office нічого не виконував.",
        "TP3": "🟢 TP3 досягнуто. Якщо позиція відкрита: розглянь закриття залишку вручну. Office нічого не виконував.",
        "SL": "🔴 Рівня SL досягнуто. Перевір фактичний стан позиції на біржі. Office не виконував ордерів.",
    }
    return base + "\n" + actions.get(level, level)

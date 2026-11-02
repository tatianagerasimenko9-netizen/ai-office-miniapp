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


def is_td(row: Dict[str, Any]) -> bool:
    return str(row.get("sig_id", "")).startswith("TD|")


def head(row: Dict[str, Any]) -> str:
    """Префікс повідомлень: «B&R LIVE · B&R-n» або «TD ТЕСТ · TD-n»."""
    return f"TD ТЕСТ · TD-{int(row['seq'])}" if is_td(row) else f"B&R LIVE · B&R-{row['seq']}"


def _td_hyp(row: Dict[str, Any]) -> Dict[str, Any]:
    raw = row.get("hyp_json")
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:  # noqa: BLE001
        return {}


def build_td_card(row: Dict[str, Any]) -> str:
    sym, d = row["symbol"], row["direction"]
    entry, sl = float(row["entry"]), float(row["sl"])
    risk = abs(entry - sl)
    tg = json.loads(row["targets_json"]) if isinstance(row.get("targets_json"), str) else row.get("targets") or []
    pc = lambda p: f"{abs(p - entry) / entry * 100:.2f}".replace(".", ",")
    hyp = _td_hyp(row)
    ft = hyp.get("feats") or {}

    def fx(key: str, spec: str = "{:.1f}") -> str:
        v = ft.get(key)
        return spec.format(v).replace(".", ",") if isinstance(v, (int, float)) and v == v else "—"

    score = str(round(float(hyp.get("score", 0) or 0), 2)).replace(".", ",")
    thr = str(round(float(hyp.get("threshold", 0) or 0), 2)).replace(".", ",")
    L = [
        f"🧪 ТЕСТ · TD-V1 · TD-{int(row['seq'])} · {sym} · {d}",
        "Стратегія-кандидат (гіпотеза): старші ТФ → вхід на M15 з малим стопом. Не гроші.",
        f"📊 Старші ТФ (H1): оцінка моделі {score} ≥ поріг {thr} (верхні 3%)",
        f"   • тижневий рівень: попереду {fx('W_ahead')} ATR · позаду {fx('W_behind')} ATR",
        f"   • 4-год рівень: попереду {fx('H4_ahead')} ATR · позаду {fx('H4_behind')} ATR",
        f"   • положення в діапазоні 3 діб: {fx('pos72', '{:.0%}')} (0% — низ, 100% — верх; у бік угоди)",
        "🕯 M15: підтвердження — свічка в бік угоди закрилась за екстремумом попередньої",
        f"🟡 ВХІД {_n(entry, sym)}",
        f"🔴 SL {_n(sl, sym)} (−{pc(sl)}%) · за екстремумом останніх 8 M15-свічок",
    ]
    for t in tg[:1]:
        rr = abs(float(t["p"]) - entry) / risk if risk > 0 else 0.0
        L.append(f"🟢 TP {_n(t['p'], sym)} (+{pc(t['p'])}% · {str(round(rr, 1)).replace('.', ',')}R) · ціль із плану H1 (3R від H1-стопа)")
    L.append("⏱ Вихід за часом: 48 год. Часткових TP у цій версії немає.")
    L.append("⚠️ ТЕСТОВА СТРАТЕГІЯ V1 (гіпотеза) · лише спостереження/ручне рішення · Office не відкриває ордерів.")
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
    actions = {
        "ENTRY": "🟡 Ціну входу торкнуто",
        "TP1": "🟢 TP1 досягнуто",
        "TP2": "🟢 TP2 досягнуто",
        "TP3": "🟢 TP3 досягнуто",
        "SL": "🔴 SL досягнуто",
    }
    return base + " · " + actions.get(level, level)

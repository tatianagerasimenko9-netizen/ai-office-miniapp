"""Вечірнє ДЗ Марічки/Лева: перевірені факти, без вигаданих рівнів і фейкових угод.

Не створює ENTER / позиції / WATCHING. Не змінює T0–T7.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

SOURCE_KLINES = "Binance Futures klines"
SOURCE_DEPTH = "Binance Futures depth"
SOURCE_LS = "Binance globalLongShortAccountRatio"
SOURCE_FUNDING = "Binance premiumIndex"
SOURCE_CALC = "розрахунок офісу по свічках"


def _f(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def zone_side(*, low: float, high: float, price: float) -> str:
    """Де зона відносно ціни: above / below / through."""
    lo, hi = (low, high) if low <= high else (high, low)
    if hi < price:
        return "below"
    if lo > price:
        return "above"
    return "through"


def geometry_label(side: str, *, claimed_below: bool = False, claimed_above: bool = False) -> str:
    ua = {"below": "нижче ціни", "above": "вище ціни", "through": "перетинає ціну"}[side]
    if claimed_below and side != "below":
        return f"{ua} — не «знизу»"
    if claimed_above and side != "above":
        return f"{ua} — не «зверху»"
    return ua


def interpret_long_short(ratio: Optional[float], long_account: Optional[float] = None) -> Dict[str, Any]:
    """L/S = longShortRatio (лонги/шорти рахунків). <1 → більше шортів, не «натовп у лонгах»."""
    out: Dict[str, Any] = {
        "ratio": ratio,
        "long_share_pct": None,
        "crowd": "",
        "text": "L/S: немає даних",
        "ok": False,
    }
    if ratio is None:
        return out
    r = float(ratio)
    if long_account is not None:
        la = float(long_account)
        out["long_share_pct"] = round(la * 100.0, 2) if 0.0 <= la <= 1.0 else round(la, 2)
    if r < 1.0:
        crowd = "більше шортів (не натовп у лонгах)"
    elif r > 1.0:
        crowd = "більше лонгів"
    else:
        crowd = "баланс лонг/шорт"
    share = ""
    if out["long_share_pct"] is not None:
        share = f", частка лонг-рахунків ≈ {out['long_share_pct']:.1f}%"
    out["crowd"] = crowd
    out["text"] = f"L/S (long/short) = {r:.4g} → {crowd}{share}"
    out["ok"] = True
    return out


def rr_at_entry(*, direction: str, entry: float, sl: float, tp: float) -> Optional[float]:
    side = str(direction or "").upper()
    risk = abs(float(entry) - float(sl))
    if risk <= 0:
        return None
    if side == "LONG":
        reward = float(tp) - float(entry)
    elif side == "SHORT":
        reward = float(entry) - float(tp)
    else:
        return None
    if reward <= 0:
        return None
    return round(reward / risk, 2)


def rr_for_entry_range(
    *,
    direction: str,
    entry_low: float,
    entry_high: float,
    sl: float,
    tp: float,
) -> Dict[str, Any]:
    """RR залежить від точки входу; одне число на весь діапазон не видаємо, якщо кінці різняться."""
    lo, hi = sorted((float(entry_low), float(entry_high)))
    a = rr_at_entry(direction=direction, entry=lo, sl=sl, tp=tp)
    b = rr_at_entry(direction=direction, entry=hi, sl=sl, tp=tp)
    mid = rr_at_entry(direction=direction, entry=(lo + hi) / 2.0, sl=sl, tp=tp)
    vals = [x for x in (a, b, mid) if x is not None]
    if not vals:
        return {"ok": False, "text": "RR: немає даних (перевір entry/SL/TP)"}
    mn, mx = min(vals), max(vals)
    if abs(mx - mn) <= 0.15:
        return {"ok": True, "rr_min": mn, "rr_max": mx, "text": f"RR ≈ 1:{mn:.1f} (вхід {lo:g}–{hi:g})"}
    return {
        "ok": True,
        "rr_min": mn,
        "rr_max": mx,
        "text": (
            f"RR залежить від входу: 1:{mn:.1f} … 1:{mx:.1f} "
            f"(не одне «1:3» на весь діапазон {lo:g}–{hi:g})"
        ),
    }


def format_dom_measured(dom: Dict[str, Any]) -> str:
    """Лише виміряне: стіни ≥ порогу або їх відсутність. Без «ніхто не захищає»."""
    if not isinstance(dom, dict) or not dom:
        return "стакан: немає даних"
    if str(dom.get("description") or "") == "DOM недоступний":
        return "стакан: DOM недоступний (немає знімка depth)"
    bids = int(dom.get("total_whale_bids") or 0)
    asks = int(dom.get("total_whale_asks") or 0)
    parts = [f"стіни ≥$500k у top-100: bid {bids}, ask {asks}"]
    bs = dom.get("biggest_support")
    br = dom.get("biggest_resistance")
    if isinstance(bs, dict) and bs.get("price") is not None:
        parts.append(f"найбільший bid {bs.get('size_str')} @ {bs.get('price')}")
    if isinstance(br, dict) and br.get("price") is not None:
        parts.append(f"найбільший ask {br.get('size_str')} @ {br.get('price')}")
    if bids == 0 and asks == 0:
        parts.append("великих стін у знімку немає (це не доказ «немає китів на ринку»)")
    return "стакан: " + "; ".join(parts)


def _zone_from_fvg(fvg: Any, price: float) -> Optional[Dict[str, Any]]:
    if not isinstance(fvg, dict):
        return None
    lo = _f(fvg.get("low"))
    hi = _f(fvg.get("high"))
    if lo is None or hi is None:
        return None
    kind = str(fvg.get("type") or "").upper()
    side = zone_side(low=lo, high=hi, price=price)
    return {
        "kind": kind,
        "low": lo,
        "high": hi,
        "side": side,
        "label": (
            f"{kind.title()} FVG {lo:g}–{hi:g} ({geometry_label(side)})"
        ),
    }


def _zone_from_ob(ob: Any, *, kind: str, price: float) -> Optional[Dict[str, Any]]:
    if not isinstance(ob, dict):
        return None
    lo = _f(ob.get("low"))
    hi = _f(ob.get("high"))
    if lo is None or hi is None:
        return None
    side = zone_side(low=lo, high=hi, price=price)
    return {
        "kind": kind,
        "low": lo,
        "high": hi,
        "side": side,
        "label": f"{kind} OB {lo:g}–{hi:g} ({geometry_label(side)})",
    }


def collect_allowed_prices(facts: Dict[str, Any]) -> Set[float]:
    nums: Set[float] = set()

    def add(v: Any) -> None:
        x = _f(v)
        if x is not None and x > 0:
            nums.add(round(x, 6))

    for k in (
        "price",
        "weekly_high",
        "weekly_low",
        "pdh",
        "pdl",
        "equilibrium",
        "asia_high",
        "asia_low",
        "london_high",
        "london_low",
        "ny_high",
        "ny_low",
    ):
        add(facts.get(k))
    for z in facts.get("zones") or []:
        if isinstance(z, dict):
            add(z.get("low"))
            add(z.get("high"))
    sw = facts.get("sweep") or {}
    if isinstance(sw, dict):
        add(sw.get("sweep_level"))
    return nums


def extract_prices(text: str) -> List[float]:
    found: List[float] = []
    for m in re.finditer(r"(?<![A-Za-z])(\d+(?:\.\d+)?)(?![A-Za-z])", text or ""):
        raw = m.group(1)
        if raw.isdigit() and len(raw) <= 2:
            continue
        x = _f(raw)
        if x is None or x <= 0:
            continue
        if x > 1_000_000:
            continue
        found.append(x)
    return found


def unexplained_levels(text: str, allowed: Set[float], *, rel: float = 0.0015) -> List[float]:
    bad: List[float] = []
    for x in extract_prices(text):
        if x >= 80 and x <= 100 and ("edge" in text.lower() or "/100" in text):
            continue
        if any(abs(x - a) <= max(abs(a) * rel, 1e-8) for a in allowed):
            continue
        # відсотки ATR / L/S
        if x <= 100 and ("%" in text or "ATR" in text or "L/S" in text):
            continue
        bad.append(x)
    # unique
    out: List[float] = []
    for x in bad:
        if not any(abs(x - y) <= 1e-9 for y in out):
            out.append(x)
    return out


def build_homework_facts(
    *,
    symbol: str,
    price: float,
    weekly_high: Optional[float],
    weekly_low: Optional[float],
    session: Dict[str, Any],
    structure: Dict[str, Any],
    pd_arr: Dict[str, Any],
    sweep: Dict[str, Any],
    fvg: Dict[str, Any],
    order_blocks: Dict[str, Any],
    dom: Dict[str, Any],
    ls: Dict[str, Any],
    oi: Dict[str, Any],
    atr_day_used: Optional[float],
    funding: Optional[Dict[str, Any]] = None,
    edge: Optional[Dict[str, Any]] = None,
    probability: Optional[Dict[str, Any]] = None,
    asof: Optional[str] = None,
) -> Dict[str, Any]:
    px = float(price or 0.0)
    sess = session if isinstance(session, dict) else {}
    ls_d = ls if isinstance(ls, dict) else {}
    hist = ls_d.get("history")
    last = hist[-1] if isinstance(hist, list) and hist and isinstance(hist[-1], dict) else {}
    ratio = _f(ls_d.get("current_ratio"))
    long_acc = _f(last.get("long_pct"))
    ls_info = interpret_long_short(ratio, long_acc)

    zones: List[Dict[str, Any]] = []
    fvg_d = fvg if isinstance(fvg, dict) else {}
    for key in ("bullish_fvg", "bearish_fvg"):
        z = _zone_from_fvg(fvg_d.get(key), px)
        if z:
            zones.append(z)
    ob_d = order_blocks if isinstance(order_blocks, dict) else {}
    bz = _zone_from_ob(ob_d.get("bullish_ob"), kind="Bullish", price=px)
    if bz:
        zones.append(bz)
    rz = _zone_from_ob(ob_d.get("bearish_ob"), kind="Bearish", price=px)
    if rz:
        zones.append(rz)

    geo_ok = True
    geo_notes: List[str] = []
    for z in zones:
        if z.get("kind") == "BULLISH" and z.get("side") == "above":
            geo_ok = False
            geo_notes.append(f"{z['label']} — не зона «знизу»")
        if z.get("kind") == "BEARISH" and z.get("side") == "below":
            geo_ok = False
            geo_notes.append(f"{z['label']} — не зона «зверху»")

    edge_ok = isinstance(edge, dict) and edge.get("day_used_pct") is not None and str(edge.get("verdict") or "") not in (
        "Помилка розрахунку",
        "Немає символу",
    )
    prob_ok = (
        isinstance(probability, dict)
        and probability.get("recommendation") is not None
        and str(probability.get("reason") or "")
        and str(probability.get("symbol") or "")
    )
    fund_v = None
    if isinstance(funding, dict):
        fund_v = _f(funding.get("funding_rate_pct"))

    facts: Dict[str, Any] = {
        "symbol": str(symbol or "").upper(),
        "asof_utc": asof or _now_iso(),
        "price": px,
        "price_source": f"{SOURCE_KLINES} 1d close",
        "weekly_high": weekly_high,
        "weekly_low": weekly_low,
        "weekly_source": f"{SOURCE_KLINES} 1w (до 3 свічок)",
        "pdh": _f(sess.get("pdh")),
        "pdl": _f(sess.get("pdl")),
        "pdh_pdl_source": f"{SOURCE_KLINES} попередня 1d свічка",
        "asia_high": _f(sess.get("asia_high")),
        "asia_low": _f(sess.get("asia_low")),
        "london_high": _f(sess.get("london_high")),
        "london_low": _f(sess.get("london_low")),
        "ny_high": _f(sess.get("ny_high")),
        "ny_low": _f(sess.get("ny_low")),
        "structure_event": str((structure or {}).get("event") or "") if isinstance(structure, dict) else "",
        "structure_source": SOURCE_CALC + " 4h swings",
        "pd_zone": str((pd_arr or {}).get("zone") or "") if isinstance(pd_arr, dict) else "",
        "equilibrium": _f((pd_arr or {}).get("equilibrium")) if isinstance(pd_arr, dict) else None,
        "sweep": sweep if isinstance(sweep, dict) else {},
        "zones": zones,
        "geo_ok": geo_ok,
        "geo_notes": geo_notes,
        "dom_text": format_dom_measured(dom if isinstance(dom, dict) else {}),
        "ls": ls_info,
        "oi": (oi or {}).get("oi") if isinstance(oi, dict) else None,
        "atr_day_used": atr_day_used,
        "funding_pct": fund_v,
        "edge": edge if edge_ok else None,
        "probability": probability if prob_ok else None,
        "confirmed": bool(px > 0 and geo_ok),
    }
    return facts


def format_facts_block(facts: Dict[str, Any]) -> str:
    lines = [
        f"ФАКТИ (не вигадуй інші числа). Знімок UTC {facts.get('asof_utc')}",
        f"Символ: {facts.get('symbol')} · ціна {facts.get('price')} ({facts.get('price_source')})",
        f"Тиждень high/low: {facts.get('weekly_high')} / {facts.get('weekly_low')} ({facts.get('weekly_source')})",
        f"PDH/PDL: {facts.get('pdh')} / {facts.get('pdl')} ({facts.get('pdh_pdl_source')})",
        (
            f"Сесії Asia {facts.get('asia_high')}/{facts.get('asia_low')} · "
            f"London {facts.get('london_high')}/{facts.get('london_low')} · "
            f"NY {facts.get('ny_high')}/{facts.get('ny_low')}"
        ),
        f"4H структура: {facts.get('structure_event') or 'немає'} ({facts.get('structure_source')})",
        f"PD: {facts.get('pd_zone') or 'немає'} · рівновага {facts.get('equilibrium')}",
        f"Sweep: {facts.get('sweep') or 'немає'}",
    ]
    zones = facts.get("zones") or []
    if zones:
        lines.append("Зони FVG/OB: " + "; ".join(str(z.get("label")) for z in zones if isinstance(z, dict)))
    else:
        lines.append("Зони FVG/OB: немає в знімку")
    if facts.get("geo_notes"):
        lines.append("Геометрія: " + "; ".join(facts["geo_notes"]))
    lines.append(str(facts.get("dom_text") or "стакан: немає даних"))
    ls = facts.get("ls") or {}
    lines.append(str(ls.get("text") or "L/S: немає даних"))
    if facts.get("atr_day_used") is not None:
        lines.append(f"ATR day_used: {float(facts['atr_day_used']):.0f}% (денні свічки)")
    if facts.get("funding_pct") is None:
        lines.append("Funding: немає даних")
    else:
        lines.append(f"Funding: {float(facts['funding_pct']):.4f}% ({SOURCE_FUNDING})")
    edge = facts.get("edge")
    if isinstance(edge, dict):
        lines.append(
            f"Edge Score: {edge.get('edge_score')}/100 grade={edge.get('grade')} "
            f"has_edge={edge.get('has_edge')} (чеклист сетапу, не ймовірність ціни)"
        )
    else:
        lines.append("Edge Score: немає даних")
    prob = facts.get("probability")
    if isinstance(prob, dict):
        lines.append(
            f"Probability Engine (узгодженість факторів, не прогноз ціни): "
            f"LONG {prob.get('long_prob')}% / SHORT {prob.get('short_prob')}% / "
            f"NO TRADE {prob.get('no_trade_prob')}% · {prob.get('confidence')} · {prob.get('recommendation')}"
        )
    else:
        lines.append("Probability Engine: немає даних")
    if not facts.get("confirmed"):
        lines.append("СТАТУС: дані не підтверджені — готовий торговий план заборонено.")
    return "\n".join(lines)


def marichka_system_prompt() -> str:
    return (
        "Ти Марічка. Домашнє завдання на завтра українською.\n"
        "Бери ТІЛЬКИ числа з блоку ФАКТИ. Не вигадуй ціни, FVG, OB, funding, Edge, Probability.\n"
        "FVG/OB описуй з того боку, який указано у фактах (вище/нижче ціни).\n"
        "L/S: ratio < 1 означає більше шортів, не «натовп у лонгах».\n"
        "Стакан — лише виміряні стіни; не пиши «ніхто не захищає».\n"
        "Edge і Probability — різні шкали; не називай їх імовірністю руху ціни.\n"
        "Якщо СТАТУС «дані не підтверджені» або сетапу немає — так і скажи, без entry/SL/TP.\n"
        "Не обрізай думку; якщо плану немає — коротко чому."
    )


def validate_card_text(text: str, facts: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[str] = []
    low = (text or "").lower()
    if "натовп у лонгах" in low or "натовп в лонгах" in low:
        ls = facts.get("ls") or {}
        ratio = ls.get("ratio")
        if ratio is not None and float(ratio) < 1.0:
            issues.append("L/S витлумачено як натовп у лонгах при ratio<1")
    if "знизу" in low:
        for z in facts.get("zones") or []:
            if z.get("kind") == "BULLISH" and z.get("side") == "above" and "fvg" in low:
                issues.append("Bullish FVG названо знизу, хоча зона вище ціни")
                break
    if "ніхто не захищає" in low or "китів немає" in low or "немає китів" in low:
        issues.append("стакан: наратив без виміряних стін")
    extra = unexplained_levels(text, collect_allowed_prices(facts))
    # відфільтрувати RR / відсотки / score
    extra = [x for x in extra if not (1.0 <= x <= 5.0)]  # RR like 2.5
    extra = [x for x in extra if x not in (15, 30, 45, 46, 70, 85, 100)]
    if extra:
        issues.append("числа поза фактами: " + ", ".join(f"{x:g}" for x in extra[:8]))
    if not facts.get("confirmed"):
        issues.append("геометрія або ціна не підтверджені")
    ok = not issues
    return {"ok": ok, "issues": issues}


def recent_setups_note(rows: Sequence[Dict[str, Any]]) -> str:
    if not rows:
        return "Останні сетапи радара/сканера: немає рядків. Це не журнал угод і не /position."
    lines = [
        "Останні статуси сетапів (SKIP / ATR_DEAD / EXPIRED — НЕ угоди журналу, НЕ /position):"
    ]
    for s in rows[:5]:
        if not isinstance(s, dict):
            continue
        oc = str(s.get("outcome") or s.get("status") or "").upper()
        lines.append(
            f"- {s.get('symbol')} {s.get('direction')} статус/outcome={oc} "
            f"(сетап, не підтверджена угода)"
        )
    return "\n".join(lines)


def lev_system_prompt() -> str:
    return (
        "Ти Лев. Підсумок домашнього завдання.\n"
        "Не додавай рівнів, яких немає у ФАКТАХ монети.\n"
        "Не рахуй SKIP, ATR_DEAD, EXPIRED, WATCHING угодами.\n"
        "RR лише для конкретних entry, SL і TP з фактів; якщо вхід-діапазон — покажи мін–макс RR.\n"
        "Якщо хоч одна картка «дані не підтверджені» — не складай готовий торговий план "
        "з entry/SL/TP. Напиши, що дані не підтверджені.\n"
        "Probability ≠ Edge ≠ ймовірність ціни."
    )


def split_telegram_chunks(text: str, limit: int = 3500) -> List[str]:
    raw = str(text or "")
    if len(raw) <= limit:
        return [raw] if raw else []
    chunks: List[str] = []
    rest = raw
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    return chunks


def homework_card_text(*, facts: Dict[str, Any], llm_text: str, issues: List[str]) -> str:
    head = format_facts_block(facts)
    body = (llm_text or "").strip()
    if issues or not facts.get("confirmed"):
        flag = "дані не підтверджені — готового торгового плану немає.\n" + "; ".join(issues)
        return f"{facts.get('symbol')}\n{head}\n\n{flag}\n\nСпостереження:\n{body}"
    return f"{facts.get('symbol')}\n{head}\n\n{body}"

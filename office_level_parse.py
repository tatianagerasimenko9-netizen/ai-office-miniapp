"""Парсинг цін і валідація WATCHING-зон.

Пробіл як роздільник тисяч («82 963–83 434») не повинен давати 82–963.
Некоректна зона не йде в БД і не блокує T3 для правильної зони.
Історичні рядки не переписуємо.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

# Ширина зони очікування відносно середини (снайперський діапазон).
MAX_ZONE_WIDTH_PCT = 0.12
# Відстань середини/краю зони від mark — інакше це не та монета/масштаб.
MAX_ZONE_DISTANCE_PCT = 0.25
# Співвідношення high/low без mark: 82 vs 963 відсікається.
MAX_BOUND_RATIO = 1.12

# Тисячі через пробіл/нерозривний пробіл або кому; десяткова крапка/кома.
PRICE_NUM = (
    r"(?:\d{1,3}(?:[ \u00a0]\d{3})+(?:[.,]\d+)?"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
    r"|\d+(?:[.,]\d+)?)"
)


def parse_price_token(raw: Any) -> Optional[float]:
    """Один токен ціни: '82 963', '80,328', '0,1453', '0.03826'."""
    try:
        s = str(raw or "").strip().replace("\u00a0", " ")
        if not s:
            return None
        s = re.sub(r"(?<=\d)[ ](?=\d)", "", s)
        if "," in s and "." in s:
            s = s.replace(",", "")
        elif "," in s:
            if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
                s = s.replace(",", "")
            else:
                test = s.replace(",", ".")
                v_test = float(test)
                if abs(v_test) >= 1000:
                    s = s.replace(",", "")
                elif abs(v_test) < 100:
                    s = s.replace(",", ".")
                else:
                    s = s.replace(",", "")
        return float(s)
    except Exception:
        return None


def zone_is_plausible(
    entry_low: Any,
    entry_high: Any = None,
    current_price: Any = None,
) -> bool:
    """True лише якщо межі схожі на реальну зону очікування, не на уламок парсера."""
    if entry_low is None:
        return False
    try:
        lo = float(entry_low)
        hi = float(entry_high) if entry_high is not None else lo
    except (TypeError, ValueError):
        return False
    if lo <= 0 or hi <= 0:
        return False
    a, b = (min(lo, hi), max(lo, hi))
    mid = (a + b) / 2.0
    if mid <= 0:
        return False
    width_pct = (b - a) / mid
    if width_pct > MAX_ZONE_WIDTH_PCT:
        return False
    if a > 0 and (b / a) > MAX_BOUND_RATIO:
        return False
    if current_price is None or current_price == "":
        return True
    try:
        px = float(current_price)
    except (TypeError, ValueError):
        return True
    if px <= 0:
        return True
    dist = min(abs(a - px), abs(b - px), abs(mid - px)) / px
    if dist > MAX_ZONE_DISTANCE_PCT:
        return False
    if a < px * 0.05 or b > px * 20:
        return False
    return True


def apply_zone_sanity(
    levels: Dict[str, Optional[float]],
    current_price: Any = None,
) -> Dict[str, Optional[float]]:
    """Обнуляє entry, якщо зона неправдоподібна. SL/TP не чіпаємо окремо без entry."""
    out = dict(levels)
    lo, hi = out.get("entry_low"), out.get("entry_high")
    if lo is None:
        return out
    if zone_is_plausible(lo, hi if hi is not None else lo, current_price):
        return out
    out["entry_low"] = None
    out["entry_high"] = None
    return out


def _extract_line_value(label: str, line_text: str, hint: Optional[float] = None) -> Optional[float]:
    patterns = [
        rf"{label}\s*:\s*([^\n\r]+)",
        rf"{label}\s*[—–\-]\s*([^\n\r]+)",
        rf"{label}\s+({PRICE_NUM}[^\n\r]*)",
    ]
    chunk = ""
    for pat in patterns:
        m = re.search(pat, line_text, flags=re.IGNORECASE)
        if m:
            chunk = str(m.group(1) or "")
            break
    if not chunk:
        return None
    nums = re.findall(PRICE_NUM, chunk)
    values: list[float] = []
    for n in nums:
        v = parse_price_token(n)
        if v is not None:
            values.append(v)
    if not values:
        return None
    if hint is not None:
        near = [v for v in values if 0.5 * hint <= v <= 1.5 * hint]
        if near:
            return near[0]
    big = [v for v in values if v >= 10]
    return big[0] if big else values[0]


def parse_signal_levels_from_text(text: str) -> Dict[str, Optional[float]]:
    """Entry / чекаю зону / OTE з пробілами в тисячах і десятковими альтами."""
    out: Dict[str, Optional[float]] = {
        "entry_low": None,
        "entry_high": None,
        "sl": None,
        "tp1": None,
        "tp2": None,
        "rr": None,
    }
    src = str(text or "").replace("`", "")
    range_pat = rf"({PRICE_NUM})\s*[-–—\u2212]\s*({PRICE_NUM})"

    def _range_from(match: Optional[re.Match[str]]) -> bool:
        if not match:
            return False
        a = parse_price_token(match.group(1))
        b = parse_price_token(match.group(2))
        if a is None or b is None:
            return False
        out["entry_low"] = min(a, b)
        out["entry_high"] = max(a, b)
        return True

    m_entry = re.search(
        rf"Entry[^:\n]{{0,24}}:\s*{range_pat}",
        src,
        flags=re.IGNORECASE,
    )
    if not m_entry:
        m_entry = re.search(rf"Entry:\s*{range_pat}", src, flags=re.IGNORECASE)
    if _range_from(m_entry):
        pass
    else:
        m_one = re.search(
            rf"Entry[^:\n]{{0,24}}:\s*({PRICE_NUM})",
            src,
            flags=re.IGNORECASE,
        )
        if not m_one:
            m_one = re.search(rf"Entry:\s*({PRICE_NUM})", src, flags=re.IGNORECASE)
        if m_one:
            v = parse_price_token(m_one.group(1))
            if v is not None:
                out["entry_low"] = v
                out["entry_high"] = v
        else:
            m_nc = re.search(rf"Entry\s+{range_pat}", src, flags=re.IGNORECASE)
            if _range_from(m_nc):
                pass
            else:
                m_one_nc = re.search(rf"Entry\s+({PRICE_NUM})", src, flags=re.IGNORECASE)
                if m_one_nc:
                    v = parse_price_token(m_one_nc.group(1))
                    if v is not None:
                        out["entry_low"] = v
                        out["entry_high"] = v

    zone_pattern = re.search(
        r"(?:зона|зони|зон[уі]|повернення\s+(?:в|до)|жд[уеи]\s+повернення\s+(?:в|до)"
        r"|жд[уеи]\s+повернення\s+в\s+зон[уі]|"
        r"OTE\s+(?:SHORT|LONG|Шорт|Лонг)?\s*зона|чекаю\s+зону:)\s*"
        + range_pat,
        src,
        flags=re.IGNORECASE,
    )
    if zone_pattern and out["entry_low"] is None:
        _range_from(zone_pattern)

    entry_hint = out["entry_low"] or out["entry_high"]
    sl_v = _extract_line_value("SL", src, hint=entry_hint)
    if sl_v is not None:
        out["sl"] = sl_v
    tp1_v = _extract_line_value("TP1", src, hint=entry_hint)
    if tp1_v is not None:
        out["tp1"] = tp1_v
    tp2_v = _extract_line_value("TP2", src, hint=entry_hint)
    if tp2_v is not None:
        out["tp2"] = tp2_v
    m_rr = re.search(r"RR:\s*([0-9]+(?:\.[0-9]+)?)", src, flags=re.IGNORECASE)
    if m_rr:
        out["rr"] = float(m_rr.group(1))
    return out

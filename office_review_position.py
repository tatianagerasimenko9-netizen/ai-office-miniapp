"""T1: /review — розбір сетапу; /position — лише явна угода Тетяни.

Не вигадуємо entry, SL, PnL. Чужий сигнал (сканер / ENTER офісу) не є позицією.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

from office_bridge import (
    _execute,
    _now_iso,
    journal_open_trade,
    log_event,
)
from office_market_state import market_state_upsert

REVIEW_PREFIXES = ("/review", "!review", "/розбір", "!розбір")
POSITION_PREFIXES = ("/position", "!position", "/позиція", "!позиція")
POSITION_STATUSES = ("OPEN", "CLOSED")


def parse_t1_command(text: str) -> Optional[Tuple[str, str]]:
    """Повернути ('review'|'position', тіло) або None."""
    s = (text or "").strip()
    if not s:
        return None
    low = s.lower()
    for p in POSITION_PREFIXES:
        if low.startswith(p):
            return "position", s[len(p) :].strip()
    for p in REVIEW_PREFIXES:
        if low.startswith(p):
            return "review", s[len(p) :].strip()
    return None


def scanner_enter_opens_position(_action: Any = None) -> bool:
    """ENTER по картці сканера — не відкриває позицію Тетяни."""
    return False


def scanner_review_notice(symbol: str, action: str) -> str:
    sym = str(symbol or "").strip().upper() or "—"
    act = str(action or "").strip().upper() or "—"
    return (
        f"Розбір чужого сигналу · {sym}\n"
        f"Вердикт офісу: {act}. Це не твоя позиція і не ордер.\n"
        "Супровід / PnL не запускаємо. Щоб завести реальну угоду: "
        "/position СИМВОЛ LONG|SHORT entry=… sl=… status=OPEN"
    )


def _extract_usdt_or_empty(text: str) -> str:
    up = (text or "").upper()
    m = re.search(r"\b[A-Z0-9]{2,15}USDT\b", up)
    return m.group(0) if m else ""


def _extract_direction(text: str) -> str:
    up = (text or "").upper()
    short_tokens = ("SHORT", "SELL", "ШОРТ", "ПРОДАЖ", "🔴")
    long_tokens = ("LONG", "BUY", "ЛОНГ", "КУПІВЛ", "🟢")
    if any(tok in up for tok in short_tokens):
        return "SHORT"
    if any(tok in up for tok in long_tokens):
        return "LONG"
    return ""


def _extract_labeled_price(text: str, labels: tuple[str, ...]) -> Optional[float]:
    if not (text or "").strip():
        return None
    lab = "|".join(re.escape(x) for x in labels)
    pat = re.compile(
        rf"(?:{lab})\s*[:=]?\s*([0-9]+(?:[.,][0-9]+)?)",
        re.IGNORECASE,
    )
    m = pat.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        return None
    if val <= 0:
        return None
    return val


def _extract_status(text: str) -> str:
    low = (text or "").lower()
    m = re.search(r"status\s*[:=]?\s*(open|closed|відкрит|закрит)", low)
    if m:
        g = m.group(1)
        if g.startswith("open") or g.startswith("відкрит"):
            return "OPEN"
        return "CLOSED"
    if re.search(r"\bclosed\b|\bзакрит", low) and re.search(r"status|статус", low):
        return "CLOSED"
    if re.search(r"\bopen\b|\bвідкрит", low) and re.search(r"status|статус", low):
        return "OPEN"
    return ""


def _extract_pnl(text: str) -> Optional[float]:
    m = re.search(r"\bpnl\s*[:=]?\s*([+-]?[0-9]+(?:[.,][0-9]+)?)", text or "", re.I)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def build_review_card(body: str) -> Dict[str, Any]:
    """Картка розбору: лише те, що є в тексті. Без журналу і без вигаданих цін."""
    body = (body or "").strip()
    symbol = _extract_usdt_or_empty(body)
    direction = _extract_direction(body)
    entry = _extract_labeled_price(body, ("entry", "вхід", "вход"))
    sl = _extract_labeled_price(body, ("sl", "stop", "стоп"))
    tp = _extract_labeled_price(body, ("tp", "take", "тейк"))
    lines = ["Розбір сетапу (/review) — не позиція."]
    if not symbol:
        lines.append("Символ не вказано — дефолтний тикер не підставляю.")
    else:
        lines.append(f"Монета: {symbol}")
    lines.append(f"Напрямок: {direction or 'не вказано'}")
    lines.append(f"Entry: {entry if entry is not None else 'немає в тексті — не вигадую'}")
    lines.append(f"SL: {sl if sl is not None else 'немає в тексті — не вигадую'}")
    lines.append(f"TP: {tp if tp is not None else 'немає в тексті — не вигадую'}")
    lines.append("PnL: не рахую. Журнал угод не чіпаю. Супровід не запускаю.")
    lines.append("Реальна угода лише через /position з entry, SL і status.")
    return {
        "kind": "review",
        "opens_position": False,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "message": "\n".join(lines),
    }


def handle_review_command(text: str, db_path: str = "") -> Dict[str, Any]:
    parsed = parse_t1_command(text)
    body = parsed[1] if parsed and parsed[0] == "review" else (text or "")
    card = build_review_card(body)
    if db_path:
        log_event(
            db_path,
            "T1_REVIEW",
            {
                "symbol": card.get("symbol") or "",
                "direction": card.get("direction") or "",
                "opens_position": False,
            },
        )
        if card.get("symbol"):
            try:
                market_state_upsert(
                    db_path,
                    str(card["symbol"]),
                    office_decision="WATCH",
                    intent="REVIEW",
                    trade="none",
                    signal={
                        "direction": card.get("direction") or None,
                        "entry": card.get("entry"),
                        "sl": card.get("sl"),
                    },
                )
            except Exception:
                pass
    return card


def handle_position_command(text: str, db_path: str = "") -> Dict[str, Any]:
    parsed = parse_t1_command(text)
    body = parsed[1] if parsed and parsed[0] == "position" else (text or "")
    symbol = _extract_usdt_or_empty(body)
    direction = _extract_direction(body)
    entry = _extract_labeled_price(body, ("entry", "вхід", "вход"))
    sl = _extract_labeled_price(body, ("sl", "stop", "стоп"))
    status = _extract_status(body)
    pnl_in_text = _extract_pnl(body)

    missing = []
    if not symbol:
        missing.append("символ")
    if direction not in ("LONG", "SHORT"):
        missing.append("напрямок")
    if entry is None:
        missing.append("entry")
    if sl is None:
        missing.append("SL")
    if status not in POSITION_STATUSES:
        missing.append("status=OPEN|CLOSED")

    if missing:
        msg = (
            "Позицію не відкриваю: не вистачає "
            + ", ".join(missing)
            + ".\nФормат: /position BTCUSDT LONG entry=100 sl=95 status=OPEN\n"
            "PnL сам не вигадую."
        )
        return {
            "kind": "position",
            "ok": False,
            "opens_position": False,
            "trade_id": None,
            "message": msg,
        }

    # PnL на OPEN ігноруємо — не пишемо вигаданий результат.
    if status != "CLOSED":
        pnl_in_text = None

    trade_id = f"pos-{symbol}-{_now_iso().replace(':', '').replace('+', '')}"
    if db_path:
        journal_open_trade(
            db_path,
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,  # type: ignore[arg-type]
            entry_price=entry,
            stop_loss=sl,
            take_profit=None,
            setup_name="T1_MY_POSITION",
            timeframe="",
            entry_reason="Explicit /position by owner",
            context={"t1": True, "status_requested": status, "source": "slash_position"},
        )
        if status == "CLOSED":
            _execute(
                db_path,
                "UPDATE trade_journal SET status = ?, ts_close_utc = ? WHERE trade_id = ?",
                ("CLOSED", _now_iso(), trade_id),
            )
            if pnl_in_text is not None:
                _execute(
                    db_path,
                    "UPDATE trade_journal SET pnl_pct = ? WHERE trade_id = ?",
                    (pnl_in_text, trade_id),
                )
        try:
            market_state_upsert(
                db_path,
                symbol,
                office_decision="SIGNAL",
                intent="MY_POSITION",
                trade="MANUAL",
            )
        except Exception:
            pass
        log_event(
            db_path,
            "T1_POSITION",
            {"trade_id": trade_id, "symbol": symbol, "status": status, "pnl": pnl_in_text},
            trade_id,
        )

    pnl_line = "PnL: не вигадую."
    if status == "CLOSED" and pnl_in_text is not None:
        pnl_line = f"PnL: {pnl_in_text}% (як ти вказала)."
    elif status == "CLOSED":
        pnl_line = "PnL: не вказано — лишаю порожнім."

    msg = (
        f"Моя позиція (/position) · {symbol} {direction}\n"
        f"Entry: {entry} | SL: {sl} | status: {status}\n"
        f"{pnl_line}\n"
        "Це явна угода, не розбір чужого сигналу."
    )
    return {
        "kind": "position",
        "ok": True,
        "opens_position": True,
        "trade_id": trade_id if db_path else "pending",
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "sl": sl,
        "status": status,
        "message": msg,
    }

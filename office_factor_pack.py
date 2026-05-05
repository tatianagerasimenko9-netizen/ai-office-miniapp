"""
Factor Pack v2 — єдина структура ринкових факторів для ролей офісу (MASTER п.25).

Джерела даних підключаються поступово: зараз Binance USDT-M (24h + premium index).
Поля без джерела лишаються None — агенти не вигадують ICT/FVG з повітря.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


SCHEMA_VERSION = "2.0"


@dataclass
class FactorPackV2:
    """Канонічний знімок факторів для bridge / журналу / майбутнього UI."""

    schema_version: str = SCHEMA_VERSION

    # Funding / ціни (Binance futures premium index)
    funding_rate_pct: Optional[float] = None
    mark_price: Optional[float] = None
    index_price: Optional[float] = None

    # Ліквідність / обсяг
    liquidity_quote_usdt_24h: Optional[float] = None
    liquidity_tier: Optional[str] = None  # low | medium | high (евристика по обсягу)

    # Волатильність / ATR-проксі
    atr_pct_proxy: Optional[float] = None  # HL range % з 24h ticker
    hl_range_pct: Optional[float] = None

    # Геп (сесійний) — поки None, доки немає окремого джерела
    gap_session_pct: Optional[float] = None

    # ICT / структура — лише коли є обчислення або ручний ввід; інакше None
    fvg_state: Optional[str] = None  # unknown | none | bullish | bearish
    order_block_state: Optional[str] = None
    bollinger_state: Optional[str] = None  # unknown | wide | squeeze
    mirror_level_hint: Optional[str] = None

    # Багатотаймфрейм / SMC — опційні теги з майбутнього аналізатора
    timeframe_bias: Optional[Dict[str, str]] = None  # {"15m": "up", "4h": "range"}
    ict_smc_tags: List[str] = field(default_factory=list)

    ote_zone_near: Optional[bool] = None
    equilibrium_near: Optional[bool] = None

    # Контекст desk
    btc_relative_strength_pct: Optional[float] = None  # alt 24h - btc 24h
    regime: Optional[str] = None
    session_hint: Optional[str] = None

    # Якість даних
    sources: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    def to_json_safe(self) -> Dict[str, Any]:
        raw = asdict(self)
        out: Dict[str, Any] = {}
        for k, v in raw.items():
            if v is None:
                continue
            if isinstance(v, list) and len(v) == 0:
                continue
            if isinstance(v, dict) and len(v) == 0:
                continue
            out[k] = v
        out.setdefault("schema_version", SCHEMA_VERSION)
        return out


def _liquidity_tier(quote_vol: float) -> str:
    if quote_vol >= 80_000_000:
        return "high"
    if quote_vol >= 20_000_000:
        return "medium"
    return "low"


def build_factor_pack_from_desk_inputs(
    *,
    btc_ticker: Dict[str, float],
    alt_ticker: Dict[str, float],
    premium: Optional[Dict[str, float]] = None,
    gold_symbol: Optional[str] = None,
    gold_change_pct: Optional[float] = None,
    score_hint: int = 12,
    regime: str = "TREND",
    session: str = "LONDON",
) -> FactorPackV2:
    """Збирає FactorPack з уже отриманих полів Binance (relay)."""
    qv = float(alt_ticker.get("quote_volume_usdt") or 0.0)
    vol_pct = float(alt_ticker.get("volatility_pct") or 0.0)
    btc_pct = float(btc_ticker.get("pct") or 0.0)
    alt_pct = float(alt_ticker.get("pct") or 0.0)

    funding = None
    mark_p = None
    idx_p = None
    if premium:
        funding = premium.get("funding_rate_pct")
        mark_p = premium.get("mark_price")
        idx_p = premium.get("index_price")

    tags: List[str] = []
    if regime.upper() == "CHOP":
        tags.append("chop_regime")
    if score_hint < 12:
        tags.append("weak_score")

    note_parts: List[str] = []
    if gold_symbol and gold_change_pct is not None:
        note_parts.append(f"gold_proxy {gold_symbol} 24h {gold_change_pct:+.2f}%")

    return FactorPackV2(
        funding_rate_pct=float(funding) if funding is not None else None,
        mark_price=float(mark_p) if mark_p is not None else None,
        index_price=float(idx_p) if idx_p is not None else None,
        liquidity_quote_usdt_24h=qv,
        liquidity_tier=_liquidity_tier(qv),
        atr_pct_proxy=vol_pct,
        hl_range_pct=vol_pct,
        btc_relative_strength_pct=round(alt_pct - btc_pct, 4),
        regime=regime,
        session_hint=session,
        ict_smc_tags=tags,
        fvg_state="unknown",
        order_block_state="unknown",
        bollinger_state="unknown",
        sources=["binance_futures_24h", "binance_premium_index"]
        if premium
        else ["binance_futures_24h"],
        notes="; ".join(note_parts) if note_parts else None,
    )


def merge_factor_meta(meta: Dict[str, Any], pack: FactorPackV2) -> Dict[str, Any]:
    """Додає factor_pack_v2 до meta OfficeSignal / desk."""
    out = dict(meta or {})
    out["factor_pack_v2"] = pack.to_json_safe()
    return out

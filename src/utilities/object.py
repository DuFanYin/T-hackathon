"""
Event payload object types for the trading system.

Each concrete event type (see `utilities/events.py`) should carry one of
these simple data models as its `Event.data` payload.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional


# ---------------- SYMBOL ----------------


@dataclass
class SymbolData:
    """
    Aggregated state for a single traded symbol.

    This is the canonical view that:
    - `MarketEngine` updates from bars (last_price from bar close)
    - `StrategyEngine` reads for trading decisions
    - `StrategyEngine` may reference for pricing/PnL
    """

    symbol: str
    # Latest trade/close price (from ticker LastPrice or last bar close).
    last_price: float = 0.0
    # Top of book snapshot (from ticker MaxBid/MinAsk).
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    # 24h volume and notional (from ticker CoinTradeValue/UnitTradeValue).
    volume_24h: Optional[float] = None
    notional_24h: Optional[float] = None
    # 24h percentage change (from ticker Change, e.g. 0.0059 == +0.59%).
    change_24h: Optional[float] = None
    # Static trading rules from exchangeInfo (if known).
    price_precision: Optional[int] = None
    amount_precision: Optional[int] = None
    min_order_notional: Optional[float] = None
    # Timestamp of the latest update applied to this symbol.
    ts: Optional[datetime] = None


@dataclass
class TradingPair:
    """
    One `/v3/exchangeInfo` `TradePairs` entry (Roostoo Public API).

    The API nests rules under each pair key (e.g. ``"BTC/USD"``). JSON fields:
    ``Coin``, ``CoinFullName``, ``Unit``, ``UnitFullName``, ``CanTrade``,
    ``PricePrecision``, ``AmountPrecision``, ``MiniOrder``.
    """

    pair: str  # TradePairs dict key, e.g. "BTC/USD"
    symbol: str  # internal symbol, e.g. "BTCUSDT"
    coin: str = ""
    coin_full_name: str = ""
    unit: str = ""
    unit_full_name: str = ""
    can_trade: bool = True
    price_precision: int = 0
    amount_precision: int = 0
    mini_order: float = 0.0

    @staticmethod
    def quantize_to_decimal_places(value: float, decimals: int) -> float:
        """
        Round `value` to `decimals` fractional digits (half-up), matching exchange PricePrecision / AmountPrecision.
        Used before place_order so payloads match Roostoo step rules from /v3/exchangeInfo.
        """
        d = int(decimals)
        if d < 0:
            return float(value)
        factor = 10.0**d
        return math.floor(float(value) * factor + 0.5) / factor

    def quantize_quantity(self, quantity: float) -> float:
        return self.quantize_to_decimal_places(float(quantity), int(self.amount_precision))

    def quantize_price(self, price: float) -> float:
        return self.quantize_to_decimal_places(float(price), int(self.price_precision))

    @classmethod
    def from_exchange_entry(cls, roostoo_pair: str, spec: Mapping[str, Any] | None, *, symbol: str) -> TradingPair:
        s: Mapping[str, Any] = spec if isinstance(spec, Mapping) else {}

        def _st(k: str, d: str = "") -> str:
            v = s.get(k, d)
            return d if v is None else str(v)

        try:
            mini = float(s.get("MiniOrder", 0.0) or 0.0)
        except (TypeError, ValueError):
            mini = 0.0

        return cls(
            pair=str(roostoo_pair),
            symbol=str(symbol),
            coin=_st("Coin"),
            coin_full_name=_st("CoinFullName"),
            unit=_st("Unit"),
            unit_full_name=_st("UnitFullName"),
            can_trade=bool(s.get("CanTrade", True)),
            price_precision=int(s.get("PricePrecision", 0) or 0),
            amount_precision=int(s.get("AmountPrecision", 0) or 0),
            mini_order=mini,
        )


# ---------------- BAR ----------------

@dataclass
class BarData:
    """OHLC bar for a symbol (one candle)."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    ts: Optional[datetime] = None
    # Candle interval (e.g. "5m"). Used for per-interval bar storage in MarketEngine.
    interval: Optional[str] = None


# ---------------- ORDER ----------------


@dataclass
class OrderRequest:
    """
    Request to place a new order.

    Intended payload for `INTENT_PLACE_ORDER`.
    """

    symbol: str
    side: str  # "BUY" / "SELL"
    quantity: float
    price: float
    order_type: str = "LIMIT"  # e.g. "LIMIT", "MARKET"
    client_order_id: Optional[str] = None
    strategy_name: Optional[str] = None  # for position attribution
    extra: Optional[dict[str, Any]] = None


@dataclass
class CancelOrderRequest:
    """
    Request to cancel an existing order.

    Intended payload for `INTENT_CANCEL_ORDER`.
    """

    order_id: str
    symbol: Optional[str] = None
    client_order_id: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


@dataclass
class OrderData:
    """Order lifecycle information (event payload for `EVENT_ORDER`)."""

    order_id: str
    symbol: str
    side: str  # "BUY" / "SELL"
    quantity: float
    price: float
    status: str  # e.g. "NEW", "PARTIALLY_FILLED", "FILLED", "CANCELLED"
    order_type: str = "LIMIT"  # e.g. "LIMIT", "MARKET"

    # Fill info (from Roostoo OrderDetail / OrderMatched)
    filled_quantity: float = 0.0
    filled_avg_price: float = 0.0

    # Exchange metadata
    role: Optional[str] = None  # "MAKER" / "TAKER"
    stop_type: Optional[str] = None  # e.g. "GTC"
    commission_coin: Optional[str] = None
    commission_value: float = 0.0
    commission_percent: float = 0.0

    # Raw exchange-side value changes (not all strategies need these)
    coin_change: float = 0.0
    unit_change: float = 0.0

    # Timing fields (optional)
    create_ts: Optional[int] = None  # exchange create timestamp (ms)
    finish_ts: Optional[int] = None  # exchange finish timestamp (ms)

    strategy_name: Optional[str] = None  # for position attribution
    ts: Optional[datetime] = None


# ---------------- POSITION (crypto: simple per-symbol) ----------------


@dataclass
class PositionData:
    """Single-symbol position for crypto; quantity is always >= 0 (long only, no short)."""

    symbol: str
    quantity: float = 0.0  # always >= 0
    avg_cost: float = 0.0
    cost_value: float = 0.0
    realized_pnl: float = 0.0
    mid_price: float = 0.0  # mark price for unrealized PnL

    def current_value(self) -> float:
        return self.quantity * self.mid_price if self.mid_price else 0.0


@dataclass
class StrategyHolding:
    """Per-strategy holdings: positions by symbol + summary (crypto, no combos)."""

    positions: dict[str, PositionData] = field(default_factory=dict)  # symbol -> position
    total_cost: float = 0.0
    current_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    pnl: float = 0.0


# ---------------- LOG ----------------


@dataclass
class LogData:
    """Structured log message carried by `EVENT_LOG`."""

    msg: str
    level: str = "INFO"  # e.g. "DEBUG", "INFO", "WARN", "ERROR"
    source: Optional[str] = None  # which engine/component emitted the log
    extra: Optional[dict[str, Any]] = None
    ts: Optional[datetime] = None


# ---------------- TIMER ----------------


@dataclass
class TimerData:
    """Payload for `EVENT_TIMER` (optional; many handlers can ignore data)."""

    ts: datetime
    tick: int | None = None  # monotonically increasing timer tick, if desired


__all__ = [
    "BarData",
    "SymbolData",
    "OrderRequest",
    "CancelOrderRequest",
    "OrderData",
    "PositionData",
    "StrategyHolding",
    "LogData",
    "TimerData",
]


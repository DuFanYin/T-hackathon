"""
Event payload object types for the trading system.

Each concrete event type (see `utilities/events.py`) should carry one of
these simple data models as its `Event.data` payload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


# ---------------- SYMBOL ----------------


@dataclass(slots=True)
class SymbolData:
    """
    Aggregated state for a single traded symbol.

    This is the canonical view that:
    - `MarketEngine` updates from bars (last_price from bar close)
    - `StrategyEngine` reads for trading decisions
    - `PositionEngine` may reference for pricing/PnL
    """

    symbol: str
    last_price: float = 0.0
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    volume_24h: Optional[float] = None
    ts: Optional[datetime] = None


# ---------------- BAR ----------------

@dataclass(slots=True)
class BarData:
    """OHLC bar for a symbol (one candle)."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: Optional[float] = None
    ts: Optional[datetime] = None


# ---------------- ORDER ----------------


@dataclass(slots=True)
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


@dataclass(slots=True)
class CancelOrderRequest:
    """
    Request to cancel an existing order.

    Intended payload for `INTENT_CANCEL_ORDER`.
    """

    order_id: str
    symbol: Optional[str] = None
    client_order_id: Optional[str] = None
    extra: Optional[dict[str, Any]] = None


@dataclass(slots=True)
class OrderData:
    """Order lifecycle information (event payload for `EVENT_ORDER`)."""

    order_id: str
    symbol: str
    side: str  # "BUY" / "SELL"
    quantity: float
    price: float
    status: str  # e.g. "NEW", "PARTIALLY_FILLED", "FILLED", "CANCELLED"
    strategy_name: Optional[str] = None  # for position attribution
    ts: Optional[datetime] = None


# ---------------- POSITION (crypto: simple per-symbol) ----------------


@dataclass(slots=True)
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


@dataclass(slots=True)
class StrategyHolding:
    """Per-strategy holdings: positions by symbol + summary (crypto, no combos)."""

    positions: dict[str, PositionData] = field(default_factory=dict)  # symbol -> position
    total_cost: float = 0.0
    current_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    pnl: float = 0.0


# ---------------- TRADE ----------------


@dataclass(slots=True)
class TradeData:
    """Executed trade (fill) information."""

    trade_id: str
    order_id: str
    symbol: str
    side: str  # "BUY" / "SELL"
    quantity: float
    price: float
    strategy_name: Optional[str] = None  # for position attribution when position engine has no on_order
    ts: Optional[datetime] = None


# ---------------- LOG ----------------


@dataclass(slots=True)
class LogData:
    """Structured log message carried by `EVENT_LOG`."""

    msg: str
    level: str = "INFO"  # e.g. "DEBUG", "INFO", "WARN", "ERROR"
    source: Optional[str] = None  # which engine/component emitted the log
    extra: Optional[dict[str, Any]] = None
    ts: Optional[datetime] = None


# ---------------- RISK ALERT ----------------


@dataclass(slots=True)
class RiskAlertData:
    """Payload for `EVENT_RISK_ALERT`."""

    msg: str
    severity: str = "WARN"  # e.g. "WARN", "CRITICAL"
    code: Optional[str] = None  # machine‑readable code/id
    source: Optional[str] = None
    ts: Optional[datetime] = None


# ---------------- TIMER ----------------


@dataclass(slots=True)
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
    "TradeData",
    "PositionData",
    "StrategyHolding",
    "LogData",
    "RiskAlertData",
    "TimerData",
]


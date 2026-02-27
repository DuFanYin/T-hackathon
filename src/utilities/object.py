"""
Event payload object types for the trading system.

Each concrete event type (see `utilities/events.py`) should carry one of
these simple data models as its `Event.data` payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


# ---------------- SYMBOL ----------------


@dataclass(slots=True)
class SymbolData:
    """
    Aggregated state for a single traded symbol.

    This is the canonical view that:
    - `MarketDataEngine` updates from incoming ticks
    - `StrategyEngine` reads for trading decisions
    - `PositionEngine` may reference for pricing/PnL
    """

    symbol: str
    last_price: float = 0.0
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    volume_24h: Optional[float] = None
    ts: Optional[datetime] = None


# ---------------- TICK ----------------


@dataclass(slots=True)
class TickData:
    """Raw market data snapshot for a single symbol (one event)."""

    symbol: str
    last_price: float
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
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
    ts: Optional[datetime] = None


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
    "SymbolData",
    "TickData",
    "OrderRequest",
    "CancelOrderRequest",
    "OrderData",
    "TradeData",
    "LogData",
    "RiskAlertData",
    "TimerData",
]


"""
Utility primitives shared across the trading system.

This module exposes:
- Event type constants (see `events.py`)
- Intent type constants (see `intents.py`)
"""

from .events import (
    EVENT_TICK,
    EVENT_ORDER,
    EVENT_TRADE,
    EVENT_POSITION,
    EVENT_ACCOUNT,
    EVENT_BALANCE,
    EVENT_LOG,
    EVENT_RISK_ALERT,
    EVENT_TIMER,
)
from .intents import (
    INTENT_PLACE_ORDER,
    INTENT_CANCEL_ORDER,
    INTENT_SYNC_POSITIONS,
    INTENT_SHUTDOWN,
)

__all__ = [
    # Events
    "EVENT_TICK",
    "EVENT_ORDER",
    "EVENT_TRADE",
    "EVENT_POSITION",
    "EVENT_ACCOUNT",
    "EVENT_BALANCE",
    "EVENT_LOG",
    "EVENT_RISK_ALERT",
    "EVENT_TIMER",
    # Intents
    "INTENT_PLACE_ORDER",
    "INTENT_CANCEL_ORDER",
    "INTENT_SYNC_POSITIONS",
    "INTENT_SHUTDOWN",
]


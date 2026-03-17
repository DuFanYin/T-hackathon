"""
Utility primitives shared across the trading system.

This module exposes:
- BaseEngine (see `base_engine.py`)
- Event type constants (see `events.py`)
- Intent type constants (see `intents.py`)
"""

from .base_engine import BaseEngine
from .interval import Interval
from .events import (
    EVENT_BAR,
    EVENT_LOG,
    EVENT_ORDER,
    EVENT_RISK_ALERT,
    EVENT_TIMER,
)
from .intents import (
    INTENT_CANCEL_ORDER,
    INTENT_LOG,
    INTENT_PLACE_ORDER,
)

__all__ = [
    "BaseEngine",
    "Interval",
    "EVENT_BAR",
    "EVENT_LOG",
    "EVENT_ORDER",
    "EVENT_RISK_ALERT",
    "EVENT_TIMER",
    "INTENT_CANCEL_ORDER",
    "INTENT_LOG",
    "INTENT_PLACE_ORDER",
]


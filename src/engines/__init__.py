"""
Engine module skeletons.

This package defines minimal class structures for:
- Main engine
- Event engine
- Position engine
- Gateway/market engine
- Strategy engine
- Risk engine
"""

from .engine_main import MainEngine
from .engine_event import Event, EventEngine
from .engine_position import PositionEngine
from .engine_gateway import GatewayEngine
from .engine_strategy import StrategyEngine
from .engine_risk import RiskEngine

__all__ = [
    "MainEngine",
    "Event",
    "EventEngine",
    "PositionEngine",
    "GatewayEngine",
    "StrategyEngine",
    "RiskEngine",
]


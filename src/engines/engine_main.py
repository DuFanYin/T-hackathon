"""
Engine-prefixed main engine module.

This file mirrors the content of the previous `main_engine.py` but
uses the `engine_*.py` naming convention to align with OTrader.
"""

from __future__ import annotations

from typing import Optional

from .engine_event import Event, EventEngine
from .engine_gateway import GatewayEngine
from .engine_position import PositionEngine
from .engine_risk import RiskEngine
from .engine_strategy import StrategyEngine


class MainEngine:
    """
    Root object that wires together long‑lived engines and exposes a simple façade.

    It is intentionally minimal at this stage:
    - Event loop startup/shutdown
    - Construction of engine singletons
    - Thin pass‑throughs for connectivity and order flow
    """

    def __init__(self, event_engine: Optional[EventEngine] = None) -> None:
        # Shared event bus for the whole process
        self.event_engine: EventEngine = event_engine or EventEngine()

        # Core engines (their internal implementations can evolve independently)
        self.gateway_engine = GatewayEngine()
        self.strategy_engine = StrategyEngine()
        self.position_engine = PositionEngine()
        self.risk_engine = RiskEngine()

        # Let the event engine configure all routing based on this main engine
        self.event_engine.configure(self)
        self.event_engine.start()

    # ------------------------------------------------------------------
    # Connectivity façade
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Establish connections to external exchanges through the gateway engine.

        The concrete behavior is implemented inside `GatewayEngine.connect`.
        """
        if hasattr(self.gateway_engine, "connect"):
            self.gateway_engine.connect()

    def disconnect(self) -> None:
        """
        Close connections to external exchanges and stop the event engine.
        """
        if hasattr(self.gateway_engine, "disconnect"):
            self.gateway_engine.disconnect()

        self.event_engine.stop()

    # ------------------------------------------------------------------
    # Order / trading façade
    # ------------------------------------------------------------------

    def send_order(self, order_request: object) -> Optional[str]:
        """
        Forward an order request to the gateway.

        `order_request` is intentionally kept generic for now; later it can become
        a typed dataclass (symbol, side, qty, price, type, etc.).
        """
        if not hasattr(self.gateway_engine, "send_order"):
            return None
        return self.gateway_engine.send_order(order_request)  # type: ignore[no-any-return]

    def cancel_order(self, cancel_request: object) -> None:
        """
        Forward a cancel request to the gateway.
        """
        if hasattr(self.gateway_engine, "cancel_order"):
            self.gateway_engine.cancel_order(cancel_request)

    # ------------------------------------------------------------------
    # Event helper
    # ------------------------------------------------------------------

    def put_event(self, event_type: str, data: object | None = None) -> None:
        """Utility to publish an event into the shared event engine."""
        self.event_engine.put(Event(event_type, data))

    # ------------------------------------------------------------------
    # Intent handling (delegates to EventEngine)
    # ------------------------------------------------------------------

    def handle_intent(self, intent_type: str, payload: object | None = None) -> object | None:
        """Thin wrapper over `EventEngine.handle_intent`."""
        return self.event_engine.handle_intent(intent_type, payload)


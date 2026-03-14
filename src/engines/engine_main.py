"""
Main engine: composition root and façade for the trading system.
"""

from __future__ import annotations

from typing import Optional

from .engine_event import Event, EventEngine
from .engine_gateway import GatewayEngine
from .engine_market import MarketEngine
from .engine_position import PositionEngine
from .engine_risk import RiskEngine
from .engine_strategy import StrategyEngine


# Hard-coded trading pairs; market and gateway auto-create from this list.
TRADING_PAIRS = ["BTCUSDT", "ETHUSDT"]


class MainEngine:
    """Builds all engines, starts the event loop, and exposes put_event, handle_intent, send_order, cancel_order."""

    def __init__(self, event_engine: Optional[EventEngine] = None, trading_pairs: Optional[list[str]] = None) -> None:
        self.trading_pairs: list[str] = trading_pairs if trading_pairs is not None else list(TRADING_PAIRS)

        self.event_engine: EventEngine = event_engine or EventEngine(main_engine=self)
        if event_engine is not None:
            self.event_engine.set_main_engine(self)

        self.market_engine = MarketEngine(main_engine=self, trading_pairs=self.trading_pairs)
        self.gateway_engine = GatewayEngine(main_engine=self, trading_pairs=self.trading_pairs)
        self.strategy_engine = StrategyEngine(main_engine=self)
        self.position_engine = PositionEngine(main_engine=self)
        self.risk_engine = RiskEngine(main_engine=self)

        self.event_engine.start()

    def add_strategy(self, strategy_name: str, trading_pair: str) -> None:
        """Add a strategy for the trading pair. strategy_name is the class name (from AVAILABLE_STRATEGIES)."""
        self.strategy_engine.add_strategy_for_pair(strategy_name, trading_pair)

    def get_strategy(self, strategy_name: str):
        """Return the strategy instance with the given name (e.g. Strat1Pine_BTCUSDT), or None."""
        return self.strategy_engine.get_strategy(strategy_name)

    def init_strategy(self, strategy_name: str) -> None:
        """Call on_init() on the strategy."""
        self.strategy_engine.init_strategy(strategy_name)

    def start_strategy(self, strategy_name: str) -> None:
        """Start the strategy (independent start control)."""
        self.strategy_engine.start_strategy(strategy_name)

    def stop_strategy(self, strategy_name: str) -> None:
        """Stop the strategy (independent stop control)."""
        self.strategy_engine.stop_strategy(strategy_name)

    # ------------------------------------------------------------------
    # Connectivity façade
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Delegate to gateway (if it implements connect)."""
        if hasattr(self.gateway_engine, "connect"):
            self.gateway_engine.connect()

    def disconnect(self) -> None:
        """Delegate to gateway and stop the event engine."""
        if hasattr(self.gateway_engine, "disconnect"):
            self.gateway_engine.disconnect()

        self.event_engine.stop()

    # ------------------------------------------------------------------
    # Order / trading façade
    # ------------------------------------------------------------------

    def send_order(self, order_request: object) -> Optional[str]:
        """Forward an order request to the gateway; returns order_id or None."""
        if not hasattr(self.gateway_engine, "send_order"):
            return None
        return self.gateway_engine.send_order(order_request)  # type: ignore[no-any-return]

    def cancel_order(self, cancel_request: object) -> None:
        """Forward a cancel request to the gateway."""
        if hasattr(self.gateway_engine, "cancel_order"):
            self.gateway_engine.cancel_order(cancel_request)

    # ------------------------------------------------------------------
    # Event helper
    # ------------------------------------------------------------------

    def put_event(self, event_type: str, data: object | None = None) -> None:
        """Enqueue an event on the event engine."""
        self.event_engine.put(Event(event_type, data))

    # ------------------------------------------------------------------
    # Intent handling (delegates to EventEngine)
    # ------------------------------------------------------------------

    def handle_intent(self, intent_type: str, payload: object | None = None) -> object | None:
        """Delegate to the event engine's intent handler."""
        return self.event_engine.handle_intent(intent_type, payload)


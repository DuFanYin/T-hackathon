"""
Gateway engine: REST I/O for orders and market data. Fetches in on_timer() and emits EVENT_BAR;
market engine receives bars and updates symbol cache and indicators.
"""

from __future__ import annotations

from typing import Optional

from src.utilities.base_engine import BaseEngine
from src.utilities.events import EVENT_BAR
from src.utilities.object import BarData


class GatewayEngine(BaseEngine):
    """Vendor adapter: send_order/cancel_order; on_timer() fetches and puts EVENT_BAR for each trading_pairs."""

    def __init__(self, main_engine=None, engine_name: str = "Gateway", trading_pairs: Optional[list[str]] = None) -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        self.trading_pairs: list[str] = list(trading_pairs) if trading_pairs else []

    def send_order(self, order_request) -> str | None:
        """Send an order to the exchange."""
        return None

    def cancel_order(self, cancel_request) -> None:
        """Cancel an existing order."""
        pass

    def on_timer(self) -> None:
        """Called each timer tick. Override to poll REST and call put_bar(BarData(...)) when a new candle is ready."""
        pass

    def put_bar(self, bar_data: BarData) -> None:
        """Emit EVENT_BAR so the event engine routes to market engine."""
        if self.main_engine:
            self.main_engine.put_event(EVENT_BAR, bar_data)

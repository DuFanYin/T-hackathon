"""
Engine-prefixed gateway engine module.

This engine is responsible for both:
- REST-based order placement/cancellation
- REST-based market data polling (ticks) for symbols.

There is **no long-lived connection state** in this design: every
interaction with the external vendor is assumed to be a stateless
HTTP request/response.
"""

from __future__ import annotations

from typing import Dict

from src.utilities.object import SymbolData, TickData


class GatewayEngine:
    """Unified REST gateway and market data engine (skeleton)."""

    def __init__(self) -> None:
        # In-memory cache of latest symbol state keyed by symbol.
        self._symbols: Dict[str, SymbolData] = {}

    # ---------------- trading ----------------

    def send_order(self, order_request) -> str | None:
        """Send an order to the exchange."""
        return None

    def cancel_order(self, cancel_request) -> None:
        """Cancel an existing order."""
        pass

    # ---------------- market data ----------------

    def on_tick(self, event) -> None:
        """
        Handle incoming tick event and update `SymbolData` cache.

        `event.data` is expected to be a `TickData` instance.
        """
        data = event.data
        if not isinstance(data, TickData):
            return

        symbol = data.symbol
        existing = self._symbols.get(symbol)

        if existing is None:
            self._symbols[symbol] = SymbolData(
                symbol=symbol,
                last_price=data.last_price,
                bid_price=data.bid_price,
                ask_price=data.ask_price,
                ts=data.ts,
            )
        else:
            existing.last_price = data.last_price
            existing.bid_price = data.bid_price
            existing.ask_price = data.ask_price
            existing.ts = data.ts

    def get_symbol(self, symbol: str) -> SymbolData | None:
        """Return latest `SymbolData` for a symbol, if known."""
        return self._symbols.get(symbol)


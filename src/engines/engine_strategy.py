"""
Engine-prefixed strategy engine module.
"""


class StrategyEngine:
    """Coordinates trading strategies and their lifecycle (skeleton)."""

    def on_tick(self, event) -> None:
        """React to market data ticks."""
        pass

    def on_order(self, event) -> None:
        """React to order state changes."""
        pass

    def on_trade(self, event) -> None:
        """React to trade fills."""
        pass

    def on_timer(self) -> None:
        """Periodic timer callback for strategies."""
        pass


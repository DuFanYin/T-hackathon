"""
Engine-prefixed risk engine module.
"""


class RiskEngine:
    """Evaluates and enforces risk constraints (skeleton)."""

    def on_tick(self, event) -> None:
        """Review risk metrics on each tick."""
        pass

    def on_order(self, event) -> None:
        """Apply risk rules to order lifecycle changes."""
        pass

    def on_trade(self, event) -> None:
        """Update risk exposure on fills."""
        pass

    def on_timer(self) -> None:
        """Periodic risk evaluation."""
        pass


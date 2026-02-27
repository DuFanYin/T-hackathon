"""
Engine-prefixed position engine module.
"""


class PositionEngine:
    """Tracks and manages strategy positions (skeleton)."""

    def on_order(self, event) -> None:
        """Update internal state when orders change."""
        pass

    def on_trade(self, event) -> None:
        """Update internal positions when trades fill."""
        pass


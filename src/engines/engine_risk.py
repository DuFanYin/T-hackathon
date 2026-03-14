"""
Risk engine: receives order, trade, and timer events; can emit EVENT_RISK_ALERT.
"""

from src.utilities.base_engine import BaseEngine


class RiskEngine(BaseEngine):
    """Risk checks and alerts; override on_order, on_trade, on_timer to implement."""

    def __init__(self, main_engine=None, engine_name: str = "Risk") -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)

    def on_order(self, event) -> None:
        pass

    def on_trade(self, event) -> None:
        pass

    def on_timer(self) -> None:
        pass


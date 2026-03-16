"""
Strategy engine: hard-coded list of available strategies by name; registers instances, forwards events.
"""

from typing import TYPE_CHECKING, Dict, Type

from src.utilities.base_engine import BaseEngine

if TYPE_CHECKING:
    from src.strategies.template import StrategyTemplate

# Hard-coded available strategies: name -> class. Add new strategy classes here.
from src.strategies.factory import Strat1Pine, Strat2Momentum, StratTestAlt

AVAILABLE_STRATEGIES: Dict[str, Type] = {
    "Strat1Pine": Strat1Pine,
    "Strat2Momentum": Strat2Momentum,
    "StratTestAlt": StratTestAlt,
}


class StrategyEngine(BaseEngine):
    """Hard-coded AVAILABLE_STRATEGIES; add_strategy_for_pair(name, pair) looks up class and creates instance."""

    def __init__(self, main_engine=None, engine_name: str = "Strategy") -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        self._strategies: list["StrategyTemplate"] = []

    def add_strategy_for_pair(self, strategy_name: str, trading_pair: str) -> None:
        """Look up strategy class by name (from AVAILABLE_STRATEGIES), create instance for trading pair, register."""
        if not self.main_engine:
            return
        strategy_class = AVAILABLE_STRATEGIES.get(strategy_name)
        if strategy_class is None:
            raise ValueError(f"Unknown strategy name: {strategy_name}. Available: {list(AVAILABLE_STRATEGIES.keys())}")
        name = f"{strategy_name}_{trading_pair}"
        setting = {"symbol": trading_pair}
        strategy = strategy_class(self.main_engine, strategy_name=name, setting=setting)
        self.add_strategy(strategy)

    def add_strategy(self, strategy: "StrategyTemplate") -> None:
        """Register a strategy instance so it receives on_timer, on_order, on_trade."""
        self._strategies.append(strategy)

    def get_strategy(self, strategy_name: str) -> "StrategyTemplate | None":
        """Return the strategy instance with the given name, or None."""
        for s in self._strategies:
            if getattr(s, "strategy_name", None) == strategy_name:
                return s
        return None

    def init_strategy(self, strategy_name: str) -> None:
        """Call on_init() on the strategy (idempotent if already inited)."""
        s = self.get_strategy(strategy_name)
        if s is None:
            raise ValueError(f"Strategy not found: {strategy_name}")
        s.on_init()

    def start_strategy(self, strategy_name: str) -> None:
        """Start the strategy (on_start); it will receive on_timer, on_order, on_trade."""
        s = self.get_strategy(strategy_name)
        if s is None:
            raise ValueError(f"Strategy not found: {strategy_name}")
        s.on_start()

    def stop_strategy(self, strategy_name: str) -> None:
        """Stop the strategy (on_stop); it will no longer run on_timer_logic."""
        s = self.get_strategy(strategy_name)
        if s is None:
            raise ValueError(f"Strategy not found: {strategy_name}")
        s.on_stop()

    def on_order(self, event) -> None:
        for s in self._strategies:
            s.on_order(event)

    def on_timer(self) -> None:
        for s in self._strategies:
            s.on_timer()


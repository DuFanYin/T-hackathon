"""
Strategy engine: hard-coded list of available strategies by name; registers instances, forwards events.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Type

from src.utilities.base_engine import BaseEngine
from src.utilities.object import OrderData, PositionData, StrategyHolding

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine
    from src.strategies.template import StrategyTemplate

# Hard-coded available strategies: name -> class. Add new strategy classes here.
from src.strategies.factory import StrategyJH, Strat2Momentum, StratTestAlt

AVAILABLE_STRATEGIES: Dict[str, Type] = {
    "strategy_JH": StrategyJH,
    "Strat2Momentum": Strat2Momentum,
    "StratTestAlt": StratTestAlt,
}


def _round_digits(value: float, digits: int) -> float:
    if digits < 0:
        return value
    factor = 10.0**digits
    return round(value * factor) / factor


class StrategyEngine(BaseEngine):
    """Hard-coded AVAILABLE_STRATEGIES; constructs and runs strategy instances."""

    def __init__(self, main_engine: "MainEngine | None" = None, engine_name: str = "Strategy") -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        self._strategies: list["StrategyTemplate"] = []
        # Per-strategy holdings updated from order status events (moved from PositionEngine).
        self._holdings: dict[str, StrategyHolding] = {}
        self._order_last_filled: dict[str, float] = {}  # order_id -> last filled qty applied

    def _ensure_symbol_active(self, symbol: str) -> None:
        me = self.main_engine
        if me is None:
            return
        sym = str(symbol).strip().upper()
        if not sym:
            return
        if sym not in me.active_pairs:
            me.active_pairs.append(sym)
        if sym not in me.gateway_engine.trading_pairs:
            me.gateway_engine.trading_pairs.append(sym)
        me.market_engine.set_symbols([sym])

    def add_strategy_by_name(self, strategy_name: str) -> "StrategyTemplate":
        """Create one strategy instance (no external symbol input)."""
        if not self.main_engine:
            raise ValueError("main_engine is required")
        strategy_class = AVAILABLE_STRATEGIES.get(strategy_name)
        if strategy_class is None:
            raise ValueError(f"Unknown strategy name: {strategy_name}. Available: {list(AVAILABLE_STRATEGIES.keys())}")
        strategy = strategy_class(self.main_engine, strategy_name=strategy_name, setting={})
        self._strategies.append(strategy)
        for sym in strategy.iter_symbols():
            self._ensure_symbol_active(sym)
        return strategy

    def get_strategy(self, strategy_name: str) -> "StrategyTemplate | None":
        """Return the strategy instance with the given name, or None."""
        for s in self._strategies:
            if getattr(s, "strategy_name", None) == strategy_name:
                return s
        return None

    def start_strategy(self, strategy_name: str) -> None:
        """Start the strategy (auto-inits internally)."""
        s = self.get_strategy(strategy_name)
        if s is None:
            raise ValueError(f"Strategy not found: {strategy_name}")
        s.on_init()
        s.on_start()

    def stop_strategy(self, strategy_name: str) -> None:
        """
        Stop the strategy (on_stop); it will no longer run on_timer_logic.

        Strategy must be FLAT before stop (no open positions).
        """
        s = self.get_strategy(strategy_name)
        if s is None:
            raise ValueError(f"Strategy not found: {strategy_name}")
        holding = self.get_holding(strategy_name)
        for pos in getattr(holding, "positions", {}).values():
            qty = float(getattr(pos, "quantity", 0.0) or 0.0)
            if qty != 0.0:
                raise ValueError(f"Strategy has open positions; close positions before stop: {strategy_name}")
        s.on_stop()

    # ------------------------------------------------------------------
    # Holdings API (merged from PositionEngine)
    # ------------------------------------------------------------------

    def get_holding(self, strategy_name: str) -> StrategyHolding:
        if strategy_name not in self._holdings:
            self._holdings[strategy_name] = StrategyHolding()
        return self._holdings[strategy_name]

    def _apply_order_fill_to_holdings(self, data: OrderData) -> None:
        strategy_name = data.strategy_name or "default"
        order_id = str(data.order_id)
        filled_qty = float(getattr(data, "filled_quantity", 0.0) or 0.0)
        filled_avg = float(getattr(data, "filled_avg_price", 0.0) or 0.0)

        last = float(self._order_last_filled.get(order_id, 0.0))
        delta = filled_qty - last
        if delta <= 0:
            return
        self._order_last_filled[order_id] = filled_qty

        holding = self.get_holding(strategy_name)
        symbol = data.symbol
        if symbol not in holding.positions:
            holding.positions[symbol] = PositionData(symbol=symbol)
        pos = holding.positions[symbol]

        if pos.quantity < 0:
            raise ValueError(f"Position quantity must be >= 0 (no short allowed): {symbol} = {pos.quantity}")

        side = (data.side or "").upper()
        if side == "BUY":
            if filled_avg > 0:
                if pos.quantity == 0:
                    pos.avg_cost = _round_digits(filled_avg, 6)
                else:
                    pos.avg_cost = _round_digits(
                        (pos.avg_cost * pos.quantity + filled_avg * delta) / (pos.quantity + delta),
                        6,
                    )
            pos.quantity += delta
            pos.cost_value = _round_digits(pos.avg_cost * pos.quantity, 6) if pos.avg_cost else 0.0
            return

        if side == "SELL":
            if delta > pos.quantity:
                raise ValueError(f"SELL {delta} would make position negative: {symbol} quantity={pos.quantity}")
            pos.quantity -= delta
            if pos.quantity == 0:
                pos.avg_cost = 0.0
                pos.cost_value = 0.0
            else:
                pos.cost_value = _round_digits(pos.avg_cost * pos.quantity, 6)
            return

        raise ValueError(f"Unknown order side: {side}")

    def process_timer_event(self) -> None:
        """Recompute mark-to-market metrics for every strategy holding using MarketEngine prices."""
        me = self.main_engine
        if me is None or not hasattr(me, "market_engine"):
            return

        market = me.market_engine
        for holding in self._holdings.values():
            total_cost = 0.0
            current_value = 0.0
            realized_pnl = 0.0

            for symbol, pos in holding.positions.items():
                total_cost += pos.cost_value
                realized_pnl += pos.realized_pnl

                mid = pos.mid_price
                sym_data = market.get_symbol(symbol)
                if sym_data is not None:
                    mid = float(getattr(sym_data, "last_price", 0.0) or 0.0)
                    pos.mid_price = mid

                current_value += pos.quantity * mid

            holding.total_cost = _round_digits(total_cost, 2)
            holding.current_value = _round_digits(current_value, 2)
            holding.realized_pnl = _round_digits(realized_pnl, 2)
            holding.unrealized_pnl = _round_digits(holding.current_value - holding.total_cost, 2)
            holding.pnl = _round_digits(holding.unrealized_pnl + holding.realized_pnl, 2)

    def on_order(self, event) -> None:
        data = getattr(event, "data", event)
        if isinstance(data, OrderData):
            self._apply_order_fill_to_holdings(data)
        for s in self._strategies:
            s.on_order(event)

    def on_timer(self) -> None:
        for s in self._strategies:
            s.on_timer()


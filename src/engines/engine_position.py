"""
Position engine: per-strategy holdings updated by order-status events.

GatewayEngine polls `/v3/query_order` and emits `EVENT_ORDER` with `OrderData`
(including filled_quantity and filled_avg_price). PositionEngine consumes those
events and applies incremental filled deltas into per-strategy holdings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.utilities.base_engine import BaseEngine
from dataclasses import dataclass

from src.utilities.object import OrderData, PositionData, StrategyHolding

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


def _round_digits(value: float, digits: int) -> float:
    if digits < 0:
        return value
    factor = 10.0**digits
    return round(value * factor) / factor


class PositionEngine(BaseEngine):
    """
    Per-strategy holdings updated from order status events and marked to market using MarketEngine prices.

    - `on_order` applies incremental filled deltas (quantity/avg_cost/cost_value)
    - `process_timer_event` recomputes mark-to-market values (mid_price/current_value/pnl) from MarketEngine
    """

    def __init__(self, main_engine: "MainEngine | None" = None, engine_name: str = "Position") -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        self._holdings: dict[str, StrategyHolding] = {}
        self._order_last_filled: dict[str, float] = {}  # order_id -> last filled qty applied

    def get_holding(self, strategy_name: str) -> StrategyHolding:
        if strategy_name not in self._holdings:
            self._holdings[strategy_name] = StrategyHolding()
        return self._holdings[strategy_name]

    def remove_strategy_holding(self, strategy_name: str) -> None:
        self._holdings.pop(strategy_name, None)
        # Keep order tracks; strategies may still have live orders even if removed.

    def on_order(self, event) -> None:
        """Consume OrderData (with filled_quantity) and apply incremental filled deltas to holdings."""
        data = getattr(event, "data", event)
        if not isinstance(data, OrderData):
            return

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
            # Weighted avg cost using filled average price.
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

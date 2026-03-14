"""
Position engine: per-strategy positions and PnL for crypto (single-symbol, no combos).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.utilities.base_engine import BaseEngine
from src.utilities.object import (
    PositionData,
    StrategyHolding,
    TradeData,
)

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


def _round_digits(value: float, digits: int) -> float:
    if digits < 0:
        return value
    factor = 10.0**digits
    return round(value * factor) / factor


class PositionEngine(BaseEngine):
    """Per-strategy holdings: on_trade applies fills; process_timer_event() updates metrics from gateway prices."""

    def __init__(self, main_engine: "MainEngine | None" = None, engine_name: str = "Position") -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        self._strategy_holdings: dict[str, StrategyHolding] = {}
        self._trade_seen: set[str] = set()

    def on_trade(self, event) -> None:
        """Apply fill to the strategy holding; strategy from trade.strategy_name or 'default'."""
        data = getattr(event, "data", event)
        if not isinstance(data, TradeData):
            return
        trade = data
        if trade.trade_id in self._trade_seen:
            return
        self._trade_seen.add(trade.trade_id)
        strategy_name = getattr(trade, "strategy_name", None) or "default"
        self._get_or_create_holding(strategy_name)
        holding = self._strategy_holdings[strategy_name]
        self._apply_trade(holding, trade)

    def _get_or_create_holding(self, strategy_name: str) -> None:
        if strategy_name not in self._strategy_holdings:
            self._strategy_holdings[strategy_name] = StrategyHolding()

    def remove_strategy_holding(self, strategy_name: str) -> None:
        self._strategy_holdings.pop(strategy_name, None)

    def get_holding(self, strategy_name: str) -> StrategyHolding:
        self._get_or_create_holding(strategy_name)
        return self._strategy_holdings[strategy_name]

    def _apply_trade(self, holding: StrategyHolding, trade: TradeData) -> None:
        """Long-only: BUY adds, SELL reduces. Raises ValueError if trade would make quantity < 0."""
        symbol = trade.symbol
        qty = abs(float(trade.quantity))
        side = (trade.side or "").upper()
        price = float(trade.price)

        if symbol not in holding.positions:
            holding.positions[symbol] = PositionData(symbol=symbol)

        pos = holding.positions[symbol]
        if pos.quantity < 0:
            raise ValueError(f"Position quantity must be >= 0 (no short allowed): {symbol} = {pos.quantity}")

        if side == "BUY" or side == "LONG":
            if pos.quantity == 0:
                pos.avg_cost = _round_digits(price, 2)
            else:
                pos.avg_cost = _round_digits(
                    (pos.avg_cost * pos.quantity + price * qty) / (pos.quantity + qty), 2
                )
            pos.quantity += qty
            pos.cost_value = _round_digits(pos.avg_cost * pos.quantity, 2)
            return

        if side == "SELL":
            if qty > pos.quantity:
                raise ValueError(f"SELL {qty} would make position negative: {symbol} quantity={pos.quantity}")
            pnl = (price - pos.avg_cost) * qty
            pos.realized_pnl += _round_digits(pnl, 2)
            pos.quantity -= qty
            if pos.quantity == 0:
                pos.avg_cost = 0.0
                pos.cost_value = 0.0
            else:
                pos.cost_value = _round_digits(pos.avg_cost * pos.quantity, 2)
            return

        raise ValueError(f"Unknown trade side: {side}")

    def update_metrics(self, strategy_name: str) -> None:
        """Recompute holding summary from gateway mark prices."""
        if strategy_name not in self._strategy_holdings:
            return
        holding = self._strategy_holdings[strategy_name]
        total_cost = 0.0
        current_value = 0.0
        realized_pnl = 0.0

        main = self.main_engine
        for symbol, pos in holding.positions.items():
            total_cost += pos.cost_value
            realized_pnl += pos.realized_pnl
            mid = pos.mid_price
            if main and getattr(main, "market_engine", None):
                sym_data = main.market_engine.get_symbol(symbol)
                if sym_data is not None:
                    mid = getattr(sym_data, "last_price", 0.0) or 0.0
                    pos.mid_price = mid
            current_value += pos.quantity * mid

        holding.total_cost = _round_digits(total_cost, 2)
        holding.current_value = _round_digits(current_value, 2)
        holding.realized_pnl = _round_digits(realized_pnl, 2)
        holding.unrealized_pnl = _round_digits(holding.current_value - holding.total_cost, 2)
        holding.pnl = _round_digits(holding.unrealized_pnl + holding.realized_pnl, 2)

    def process_timer_event(self) -> None:
        """Update metrics for every strategy holding."""
        for name in list(self._strategy_holdings.keys()):
            self.update_metrics(name)

    def serialize_holding(self, strategy_name: str) -> str:
        """JSON-serialize strategy holding (positions + summary)."""
        if strategy_name not in self._strategy_holdings:
            return "{}"
        holding = self._strategy_holdings[strategy_name]
        out: dict = {
            "positions": {
                sym: {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_cost": p.avg_cost,
                    "cost_value": p.cost_value,
                    "realized_pnl": p.realized_pnl,
                    "mid_price": p.mid_price,
                }
                for sym, p in holding.positions.items()
            },
            "total_cost": holding.total_cost,
            "current_value": holding.current_value,
            "unrealized_pnl": holding.unrealized_pnl,
            "realized_pnl": holding.realized_pnl,
            "pnl": holding.pnl,
        }
        return json.dumps(out)

    def load_serialized_holding(self, strategy_name: str, data: str) -> None:
        """Load strategy holding from JSON string."""
        if not data.strip():
            return
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            return
        self._get_or_create_holding(strategy_name)
        holding = self._strategy_holdings[strategy_name]
        holding.positions.clear()
        for sym, p in (obj.get("positions") or {}).items():
            q = float(p.get("quantity", 0))
            if q < 0:
                raise ValueError(f"Position quantity must be >= 0 (no short allowed): {sym} = {q}")
            holding.positions[sym] = PositionData(
                symbol=p.get("symbol", sym),
                quantity=q,
                avg_cost=float(p.get("avg_cost", 0)),
                cost_value=float(p.get("cost_value", 0)),
                realized_pnl=float(p.get("realized_pnl", 0)),
                mid_price=float(p.get("mid_price", 0)),
            )
        holding.total_cost = float(obj.get("total_cost", 0))
        holding.current_value = float(obj.get("current_value", 0))
        holding.unrealized_pnl = float(obj.get("unrealized_pnl", 0))
        holding.realized_pnl = float(obj.get("realized_pnl", 0))
        holding.pnl = float(obj.get("pnl", 0))

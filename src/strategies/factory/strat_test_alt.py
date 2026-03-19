"""
BTC-only strategy with stop loss and take profit.

- Trades only BTCUSDT.
- Opens long (BUY) when flat; monitors price for stop loss / take profit.
- Stop loss: close when price falls below entry * (1 - stop_loss_pct).
- Take profit: close when price rises above entry * (1 + take_profit_pct).
- Uses MARKET orders for entry and exit.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from src.strategies.template import StrategyTemplate

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


class StratTestAlt(StrategyTemplate):
    def __init__(self, main_engine: "MainEngine", strategy_name: str, setting: dict[str, Any] | None = None) -> None:
        setting = dict(setting or {})
        setting.setdefault("symbol", "BTCUSDT")
        setting.setdefault("symbols", ["BTCUSDT"])
        setting.setdefault("timer_trigger", 30)  # check every 30 ticks (e.g. 30s if engine interval=1s)
        super().__init__(main_engine=main_engine, strategy_name=strategy_name, setting=setting)

        self.symbol: str = "BTCUSDT"
        self.quantity: float = float(setting.get("quantity", 0.001))
        self.stop_loss_pct: float = float(setting.get("stop_loss_pct", 0.01))   # 1% below entry
        self.take_profit_pct: float = float(setting.get("take_profit_pct", 0.02))  # 2% above entry
        self.cooldown_ticks: int = int(setting.get("cooldown_ticks", 60))  # wait N ticks after close before re-entry

        self._ticks_since_close: int = 0

        self._ticks_since_close = self.cooldown_ticks  # allow first entry immediately
        self.write_log(
            f"StratTestAlt symbol={self.symbol} qty={self.quantity} "
            f"SL={self.stop_loss_pct*100:.1f}% TP={self.take_profit_pct*100:.1f}% cooldown={self.cooldown_ticks}",
            level="INFO",
        )

    def on_order(self, event: Any) -> None:
        super().on_order(event)
        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos_summary = {s: p.quantity for s, p in holding.positions.items() if p.quantity != 0}
        self.write_log(f"positions={pos_summary}", level="INFO")

    def on_timer_logic(self) -> None:
        sym_data = self.get_symbol(self.symbol)
        last = getattr(sym_data, "last_price", None) if sym_data else None
        if last is None:
            return

        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(self.symbol) if holding and hasattr(holding, "positions") else None
        position_size = float(getattr(pos, "quantity", 0) or 0) if pos else 0.0
        flat = position_size <= 0.0

        if not flat:
            # In position: check stop loss and take profit
            entry = float(getattr(pos, "avg_cost", 0) or 0)
            if entry <= 0:
                entry = last  # fallback if avg_cost not yet set
            stop_price = entry * (1.0 - self.stop_loss_pct)
            target_price = entry * (1.0 + self.take_profit_pct)

            if last <= stop_price:
                self.close_position(self.symbol, position_size, 0.0, "MARKET")
                self._ticks_since_close = 0
                self.write_log(
                    f"Stop loss hit {self.symbol} last={last:.2f} <= stop={stop_price:.2f}",
                    level="WARN",
                )
                return
            if last >= target_price:
                self.close_position(self.symbol, position_size, 0.0, "MARKET")
                self._ticks_since_close = 0
                self.write_log(
                    f"Take profit hit {self.symbol} last={last:.2f} >= target={target_price:.2f}",
                    level="INFO",
                )
                return
            return

        # Flat: cooldown after close before re-entry (first entry allowed: _ticks_since_close starts high)
        if self._ticks_since_close < self.cooldown_ticks:
            self._ticks_since_close += 1
            return

        pending = self.get_pending_orders()
        # If the engine still has any pending orders for this strategy, don't spam re-entry.
        # (Some exchange responses omit symbol, so rely on "any pending" rather than symbol-keyed lookup only.)
        if any(pending.values()) or pending.get(self.symbol):
            return  # wait for pending to fill

        self.open_position(self.symbol, self.quantity, 0.0, "MARKET")
        # Prevent repeated entry attempts when holdings/account state updates lag behind order placement.
        self._ticks_since_close = 0
        self.write_log(f"Entry BUY {self.symbol} qty={self.quantity} @ market", level="INFO")

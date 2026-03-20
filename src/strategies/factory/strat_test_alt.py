"""
Simple heartbeat strategy for plumbing tests.

- Trades only BTCUSDT.
- Every minute alternates action:
  - minute N: open BUY 0.01 (if flat)
  - minute N+1: close SELL 0.01 (if position exists)
- Uses MARKET orders only.
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
        setting.setdefault("timer_trigger", 60)  # every minute if engine tick is 1s
        super().__init__(main_engine=main_engine, strategy_name=strategy_name, setting=setting)

        self.symbol: str = "BTCUSDT"
        self.quantity: float = float(setting.get("quantity", 0.01))
        self._next_action_open: bool = True
        self.write_log(
            f"StratTestAlt symbol={self.symbol} qty={self.quantity} alternating every timer minute",
            level="INFO",
        )

    def on_order(self, event: Any) -> None:
        super().on_order(event)
        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos_summary = {s: p.quantity for s, p in holding.positions.items() if p.quantity != 0}
        self.write_log(f"positions={pos_summary}", level="INFO")

    def on_timer_logic(self) -> None:
        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(self.symbol) if holding and hasattr(holding, "positions") else None
        position_size = float(getattr(pos, "quantity", 0) or 0) if pos else 0.0
        flat = position_size <= 0.0

        pending = self.get_pending_orders()
        if any(pending.values()) or pending.get(self.symbol):
            self.write_log("Skip tick due to pending orders", level="DEBUG")
            return

        if self._next_action_open:
            if flat:
                self.open_position(self.symbol, self.quantity, 0.0, "MARKET")
                self.write_log(f"OPEN BUY {self.symbol} qty={self.quantity} @ market", level="INFO")
            else:
                self.write_log("Open step skipped: already holding position", level="DEBUG")
            self._next_action_open = False
            return

        # close step
        if not flat:
            close_qty = min(self.quantity, position_size)
            self.close_position(self.symbol, close_qty, 0.0, "MARKET")
            self.write_log(f"CLOSE SELL {self.symbol} qty={close_qty} @ market", level="INFO")
        else:
            self.write_log("Close step skipped: no position", level="DEBUG")
        self._next_action_open = True

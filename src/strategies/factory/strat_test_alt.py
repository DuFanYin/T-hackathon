"""
Simple heartbeat strategy for plumbing tests.

- Trades only BTCUSDT.
- Every ~4 hours (configurable): open BUY with MARKET, wait 5s, then close with MARKET.
- Uses MARKET orders only.
"""

from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from src.strategies.template import StrategyTemplate

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine

# Defaults: full cycle spacing and gap between open and close
DEFAULT_CYCLE_INTERVAL_SEC = 4 * 3600
DEFAULT_CLOSE_DELAY_SEC = 5


class StratTestAlt(StrategyTemplate):
    def __init__(self, main_engine: "MainEngine", strategy_name: str, setting: dict[str, Any] | None = None) -> None:
        setting = dict(setting or {})
        setting.setdefault("symbol", "BTCUSDT")
        setting.setdefault("symbols", ["BTCUSDT"])
        # Need ~1s resolution so the 5s close fires on time (engine tick is typically 1s).
        setting.setdefault("timer_trigger", 1)
        super().__init__(main_engine=main_engine, strategy_name=strategy_name, setting=setting)

        self.symbol: str = "BTCUSDT"
        self.quantity: float = float(setting.get("quantity", 0.01))
        self._cycle_interval_sec: float = float(
            setting.get("cycle_interval_sec", DEFAULT_CYCLE_INTERVAL_SEC)
        )
        self._close_delay_sec: float = float(setting.get("close_delay_sec", DEFAULT_CLOSE_DELAY_SEC))
        # After a full open→close cycle completes (wall clock).
        self._last_cycle_complete_time: float = 0.0
        # When set, we are waiting until this time to issue the close.
        self._close_scheduled_at: float | None = None

        self.write_log(
            f"StratTestAlt symbol={self.symbol} qty={self.quantity} "
            f"cycle={self._cycle_interval_sec}s open→close gap={self._close_delay_sec}s",
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

        now = time.time()

        # Phase: scheduled close
        if self._close_scheduled_at is not None:
            if now < self._close_scheduled_at:
                return
            if not flat:
                close_qty = min(self.quantity, position_size)
                self.close_position(self.symbol, close_qty, 0.0, "MARKET")
                self.write_log(f"CLOSE SELL {self.symbol} qty={close_qty} @ market", level="INFO")
            else:
                self.write_log("Close step skipped: no position", level="DEBUG")
            self._close_scheduled_at = None
            self._last_cycle_complete_time = now
            return

        # Phase: idle — maybe start a new cycle
        due = self._last_cycle_complete_time == 0.0 or (
            now - self._last_cycle_complete_time >= self._cycle_interval_sec
        )
        if not due:
            return

        if not flat:
            self.write_log("Open step skipped: already holding position", level="DEBUG")
            return

        self.open_position(self.symbol, self.quantity, 0.0, "MARKET")
        self.write_log(f"OPEN BUY {self.symbol} qty={self.quantity} @ market", level="INFO")
        self._close_scheduled_at = now + self._close_delay_sec

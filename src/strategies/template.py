"""
Strategy template: lifecycle and helpers for timer-driven strategies (OTrader-style).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.utilities.events import EVENT_LOG
from src.utilities.intents import INTENT_PLACE_ORDER
from src.utilities.object import OrderRequest

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


class StrategyTemplate:
    """Base for strategies: override on_init_logic(), on_stop_logic(), on_timer_logic(); use get_symbol() for prices."""

    def __init__(
        self,
        main_engine: "MainEngine",
        strategy_name: str,
        setting: dict[str, Any] | None = None,
    ) -> None:
        if main_engine is None:
            raise ValueError("main_engine is required")
        self._main = main_engine
        self.strategy_name = strategy_name
        setting = setting or {}
        self._timer_trigger: int = int(setting.get("timer_trigger", 1))
        self._timer_cnt: int = 0
        self._inited: bool = False
        self._started: bool = False
        self._error: bool = False
        self._error_msg: str = ""
        self.write_log(f"Strategy {strategy_name} created")

    # ---------- lifecycle (framework) ----------

    def on_init(self) -> None:
        self._inited = True
        self.on_init_logic()

    def on_start(self) -> None:
        self._started = True

    def on_stop(self) -> None:
        self._started = False
        self.on_stop_logic()

    def on_timer(self) -> None:
        if not self._started or self._error:
            return
        self._timer_cnt += 1
        if self._timer_cnt >= self._timer_trigger:
            self._timer_cnt = 0
            self.on_timer_logic()

    def on_order(self, event: Any) -> None:
        data = getattr(event, "data", event)
        order_id = getattr(data, "order_id", "")
        symbol = getattr(data, "symbol", "")
        side = getattr(data, "side", "")
        qty = getattr(data, "quantity", 0)
        price = getattr(data, "price", 0.0)
        filled = getattr(data, "filled_avg_price", None) or price
        status = getattr(data, "status", "")
        self.write_log(f"Order {order_id}: {side} {qty} @ {filled} [{status}] {symbol}")

    # ---------- override these ----------

    def on_init_logic(self) -> None:
        """Override: run once after init."""
        pass

    def on_stop_logic(self) -> None:
        """Override: run once on stop."""
        pass

    def on_timer_logic(self) -> None:
        """Override: run every timer_trigger ticks; use get_symbol() for prices."""
        pass

    # ---------- helpers ----------

    def write_log(self, msg: str, level: int = 20) -> None:
        prefixed = f"[{self.strategy_name}] {msg}"
        self._main.put_event(EVENT_LOG, prefixed)

    def send_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        order_type: str = "LIMIT",
    ) -> str | None:
        req = OrderRequest(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            strategy_name=self.strategy_name,
        )
        return self._main.handle_intent(INTENT_PLACE_ORDER, req)

    def get_symbol(self, symbol: str) -> Any | None:
        if self._main.gateway_engine is None:
            return None
        return self._main.market_engine.get_symbol(symbol) if hasattr(self._main, "market_engine") else None

    def set_error(self, msg: str = "") -> None:
        self._error = True
        self._error_msg = msg
        self._started = False
        self.write_log("ERROR: " + msg)

    def clear_all_positions(self) -> None:
        """Close all positions for this strategy (long only: market sell). Raises if any quantity < 0."""
        if not hasattr(self._main, "position_engine") or self._main.position_engine is None:
            return
        holding = self._main.position_engine.get_holding(self.strategy_name)
        for symbol, pos in holding.positions.items():
            if pos.quantity == 0:
                continue
            if pos.quantity < 0:
                raise ValueError(f"Position quantity must be >= 0 (no short allowed): {symbol} = {pos.quantity}")
            price = 0.0
            sym_data = self.get_symbol(symbol)
            if sym_data is not None:
                price = getattr(sym_data, "last_price", 0.0) or 0.0
            self.send_order(symbol, "SELL", pos.quantity, price, "MARKET")
            self.write_log(f"clear_all_positions: SELL {pos.quantity} {symbol}")

    # ---------- state ----------

    @property
    def inited(self) -> bool:
        return self._inited

    @property
    def started(self) -> bool:
        return self._started

    @property
    def error(self) -> bool:
        return self._error

    @property
    def error_msg(self) -> str:
        return self._error_msg

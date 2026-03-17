"""
Test strategy: pull BTC price every 3 seconds and alternate BUY/SELL market orders.

- Runs on the framework timer (EventEngine interval is 1s).
- Every 3 seconds, logs BTCUSDT price (from MarketEngine symbol cache),
  then places a MARKET order alternating BUY/SELL.
- Repeats 3 cycles total (6 orders), then stops itself.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from src.strategies.template import StrategyTemplate

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


class StratTestAlt(StrategyTemplate):
    def __init__(self, main_engine: "MainEngine", strategy_name: str, setting: dict[str, Any] | None = None) -> None:
        setting = dict(setting or {})
        setting.setdefault("timer_trigger", 3)
        super().__init__(main_engine=main_engine, strategy_name=strategy_name, setting=setting)

        # Prefer template-parsed multi-symbol config; fall back to BTCUSDT.
        self.symbol: str = (self.symbols[0] if self.symbols else "BTCUSDT")
        self.quantity: float = float(setting.get("quantity", 0.001))

        self._order_attempts: int = 0
        self._cycle_limit: int = 3
        self._side_next: str = "BUY"

    @property
    def order_attempts(self) -> int:
        return self._order_attempts

    def on_order(self, event: Any) -> None:
        # StrategyEngine applies fills to holdings before forwarding events to strategies,
        # so by the time we get here holdings are already updated and safe to log.
        super().on_order(event)
        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos_summary = {s: p.quantity for s, p in holding.positions.items() if p.quantity != 0}
        self.write_log(f"positions={pos_summary}")

    def on_timer_logic(self) -> None:
        sym = self.get_symbol(self.symbol)
        last = getattr(sym, "last_price", None) if sym else None
        self.write_log(f"tick price {self.symbol}={last}")

        # Alternate market orders
        side = self._side_next
        self._side_next = "SELL" if side == "BUY" else "BUY"

        order_id = self.send_order(self.symbol, side, self.quantity, price=0.0, order_type="MARKET")
        self._order_attempts += 1

        # After send: check order status once; if pending, cancel; then check pending count
        try:
            if order_id:
                resp = self._main.query_order(order_id=str(order_id))
                detail = None
                if isinstance(resp, dict):
                    detail = resp.get("OrderDetail")
                    if detail is None and isinstance(resp.get("OrderMatched"), list) and resp["OrderMatched"]:
                        detail = resp["OrderMatched"][0]
                status = str((detail or {}).get("Status", "")).upper() if isinstance(detail, dict) else ""
                self.write_log(f"order status order_id={order_id} status={status}")
                if status == "PENDING":
                    self._main.cancel_order(order_id=str(order_id), symbol=self.symbol)
                    self.write_log(f"cancel sent order_id={order_id}")

        except Exception as e:
            self.write_log(f"post-order checks failed: {e}")

        # 3 cycles total => 6 orders
        if self._order_attempts >= self._cycle_limit * 2:
            self.write_log("completed 3 cycles; stopping strategy")
            self._main.stop_strategy(self.strategy_name)


"""
Strategy template: lifecycle and helpers for timer-driven strategies (OTrader-style).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.utilities.events import EVENT_LOG
from src.utilities.intents import INTENT_PLACE_ORDER
from src.utilities.interval import Interval
from src.utilities.object import LogData, OrderData, OrderRequest, SymbolData, TradingPair

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
        self.symbols: list[str] = self._parse_symbols(setting)
        self._timer_trigger: int = int(setting.get("timer_trigger", 1))
        # Each strategy uses one interval for bar data (e.g. 5m, 15m).
        self.interval: Interval = Interval.from_str(setting.get("interval"))
        self._timer_cnt: int = 0
        self._inited: bool = False
        self._started: bool = False
        self._error: bool = False
        self._error_msg: str = ""
        self.write_log(f"Strategy {strategy_name} created")

    @staticmethod
    def _parse_symbols(setting: dict[str, Any]) -> list[str]:
        """
        Parse strategy symbol universe.

        Simplified contract: strategies must provide internal MarketEngine symbols
        (e.g. `BTCUSDT`) via either `setting["symbols"]` (list) or `setting["symbol"]` (single).
        """

        def normalize_one(x: Any) -> str:
            s = str(x or "").strip().upper()
            if not s:
                return ""
            # Reject vendor formats early (e.g. BTC/USD).
            if "/" in s:
                raise ValueError(f"Unsupported symbol format {s!r}; expected internal like 'BTCUSDT'.")
            if not s.endswith("USDT"):
                raise ValueError(f"Unsupported symbol format {s!r}; expected internal like 'BTCUSDT'.")
            return s

        raw_symbols = setting.get("symbols")
        if isinstance(raw_symbols, list):
            items = [normalize_one(s) for s in raw_symbols]
            items = [x for x in items if x]
            return sorted(set(items))

        one = setting.get("symbol")
        if one is not None:
            s = normalize_one(one)
            return [s] if s else []

        return []

    def iter_symbols(self) -> list[str]:
        return list(self.symbols)

    def history_requirements(self) -> list[dict[str, object]]:
        """
        Declare the minimum historical candle data this strategy needs to initialize.

        Returned items have shape:
          - symbol: str (e.g. "BTCUSDT")
          - interval: str (Binance kline interval, e.g. "5m", "1h")
          - bars: int (minimum candles required)

        The framework may fetch/backfill these bars during init.
        Default: no requirements.
        """
        return []

    # ---------- lifecycle (framework) ----------

    def on_init(self) -> None:
        if self._inited:
            return
        self._prepare_history()
        self._inited = True
        self.on_init_logic()

    def _prepare_history(self) -> None:
        """
        Framework internal: backfill required market history before init.

        This is intentionally not exposed as a control-plane operation.
        """
        me = getattr(self._main, "market_engine", None)
        if me is None or not hasattr(me, "ensure_history"):
            self.write_log(
                f"{self.strategy_name} | HISTORY | skip: no market_engine.ensure_history",
                level="WARN",
            )
            return
        try:
            reqs = list(self.history_requirements() or [])
        except Exception as e:
            self.write_log(f"{self.strategy_name} | HISTORY | requirements failed: {e}", level="WARN")
            return
        if not reqs:
            return
        self.write_log(
            f"{self.strategy_name} | HISTORY | backfill {len(reqs)} symbol/interval requests from Binance…",
            level="INFO",
        )
        ok = 0
        for r in reqs:
            if not isinstance(r, dict):
                continue
            symbol = str(r.get("symbol", "") or "").strip().upper()
            interval = str(r.get("interval", "") or "").strip()
            bars = int(r.get("bars", 0) or 0)
            if not symbol or not interval or bars <= 0:
                continue
            try:
                n = int(me.ensure_history(symbol, interval, bars))
                if n > 0:
                    ok += 1
            except Exception:
                continue
        self.write_log(
            f"{self.strategy_name} | HISTORY | backfill done | ok={ok}/{len(reqs)} non-empty buffers",
            level="INFO",
        )

    def on_start(self) -> None:
        self._started = True
        self.on_start_logic()

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
        # Order events are broadcast to all strategies; ignore orders that don't belong to us.
        if isinstance(data, OrderData):
            order_strat = getattr(data, "strategy_name", None)
            if order_strat is not None and order_strat != self.strategy_name:
                return
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

    def on_start_logic(self) -> None:
        """Override: run when strategy starts (immediately after `_started` is set)."""
        pass

    def on_stop_logic(self) -> None:
        """Override: run once on stop."""
        pass

    def on_timer_logic(self) -> None:
        """Override: run every timer_trigger ticks; use get_symbol() for prices."""
        pass

    # ---------- helpers ----------

    def write_log(self, msg: str, level: str = "INFO") -> None:
        self._main.put_event(EVENT_LOG, LogData(msg=msg, level=level, source=self.strategy_name))

    @staticmethod
    def _coerce_nonneg_int(x: Any) -> int | None:
        if x is None or isinstance(x, bool):
            return None
        try:
            v = int(float(x))
            return v if v >= 0 else None
        except (TypeError, ValueError):
            return None

    def _prepare_order_for_exchange(
        self,
        symbol: str,
        quantity: float,
        price: float | None,
        order_type: str,
    ) -> tuple[float, float, str] | None:
        """
        Snap qty/price to exchange step sizes when we have TradingPair or SymbolData precisions.
        Returns None only if rounded quantity is non-positive.
        """
        sym = str(symbol).strip().upper()
        sd = self.get_symbol(sym)

        tp: TradingPair | None = None
        if hasattr(self._main, "get_trading_pair"):
            raw_tp = self._main.get_trading_pair(sym)
            if isinstance(raw_tp, TradingPair):
                tp = raw_tp

        amt_dec: int | None = self._coerce_nonneg_int(tp.amount_precision) if tp is not None else None
        if amt_dec is None and isinstance(sd, SymbolData):
            amt_dec = self._coerce_nonneg_int(sd.amount_precision)
        px_dec: int | None = self._coerce_nonneg_int(tp.price_precision) if tp is not None else None
        if px_dec is None and isinstance(sd, SymbolData):
            px_dec = self._coerce_nonneg_int(sd.price_precision)

        ot = str(order_type or "LIMIT").upper()
        if amt_dec is None:
            qty = float(quantity)
        else:
            qty = TradingPair.quantize_to_decimal_places(float(quantity), amt_dec)

        lim_price: float
        if ot == "MARKET":
            lim_price = 0.0
        else:
            lim_price = float(price if price is not None else 0.0)
            if lim_price > 0 and px_dec is not None:
                lim_price = TradingPair.quantize_to_decimal_places(lim_price, px_dec)

        if qty <= 0:
            return None

        return qty, lim_price, ot

    def send_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        order_type: str = "LIMIT",
    ) -> str | None:
        prepared = self._prepare_order_for_exchange(symbol, quantity, price, order_type)
        if prepared is None:
            return None
        quantity, price, order_type = prepared
        req = OrderRequest(
            symbol=str(symbol).strip().upper(),
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

    def get_pending_orders(self) -> dict[str, list[str]]:
        """
        Return engine's cached pending order ids for this strategy, grouped by symbol.
        Result: {symbol: [order_id, ...], ...}. Use instead of tracking pending orders locally.
        """
        if not hasattr(self._main, "get_pending_orders_by_symbol"):
            return {}
        return self._main.get_pending_orders_by_symbol(self.strategy_name)

    def open_position(
        self,
        symbol: str,
        quantity: float,
        price: float | None = None,
        order_type: str = "MARKET",
    ) -> str | None:
        """
        Open a long position (BUY). Prefer this over send_order for clarity.
        - order_type: MARKET (immediate) or LIMIT
        - price: required for LIMIT; for MARKET, pass 0 or None
        """
        if order_type.upper() == "LIMIT" and price is None:
            sym_data = self.get_symbol(symbol)
            price = getattr(sym_data, "last_price", 0.0) or 0.0
        return self.send_order(symbol, "BUY", quantity, price or 0.0, order_type)

    def close_position(
        self,
        symbol: str,
        quantity: float | None = None,
        price: float | None = None,
        order_type: str = "MARKET",
    ) -> str | None:
        """
        Close a long position (SELL). Prefer this over send_order for clarity.
        - quantity: if None, closes full position from strategy holdings
        - order_type: MARKET (immediate) or LIMIT
        - price: required for LIMIT; for MARKET, pass 0 or None
        """
        if quantity is None:
            if not hasattr(self._main, "strategy_engine") or self._main.strategy_engine is None:
                return None
            holding = self._main.strategy_engine.get_holding(self.strategy_name)
            pos = holding.positions.get(symbol)
            quantity = pos.quantity if pos else 0.0
        if quantity <= 0:
            return None
        if order_type.upper() == "LIMIT" and price is None:
            sym_data = self.get_symbol(symbol)
            price = getattr(sym_data, "last_price", 0.0) or 0.0
        return self.send_order(symbol, "SELL", quantity, price or 0.0, order_type)

    def set_error(self, msg: str = "") -> None:
        self._error = True
        self._error_msg = msg
        self._started = False
        self.write_log(msg, level="ERROR")

    def clear_all_positions(self) -> None:
        """Close all positions for this strategy (long only: market sell). Raises if any quantity < 0."""
        if not hasattr(self._main, "strategy_engine") or self._main.strategy_engine is None:
            return
        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        for symbol, pos in holding.positions.items():
            if pos.quantity == 0:
                continue
            if pos.quantity < 0:
                raise ValueError(f"Position quantity must be >= 0 (no short allowed): {symbol} = {pos.quantity}")
            self.close_position(symbol, pos.quantity, order_type="MARKET")
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

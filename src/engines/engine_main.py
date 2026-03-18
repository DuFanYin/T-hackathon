"""
Main engine: composition root and façade for the trading system.
"""

from __future__ import annotations

import os
import threading
from logging.handlers import RotatingFileHandler

from typing import Optional

from .engine_event import Event, EventEngine
from .engine_gateway import GatewayEngine
from .engine_market import MarketEngine
from .engine_risk import RiskEngine
from .engine_strategy import StrategyEngine
from src.control.log_store import LogStore
from src.control.order_store import OrderStore


class MainEngine:
    """Builds all engines, starts the event loop, and exposes put_event, handle_intent, send_order, cancel_order."""

    def __init__(
        self,
        event_engine: Optional[EventEngine] = None,
        env_mode: str = "mock",
    ) -> None:
        # Always rely on remote discovery for *available* trading pairs; start empty here.
        # Note: we do NOT subscribe market polling to all available pairs (too slow).
        self.trading_pairs: list[str] = []  # available pairs discovered from exchangeInfo
        self.active_pairs: list[str] = []  # pairs actively traded/polled (added when strategies are added)
        self.env_mode: str = env_mode.strip().lower() if env_mode else "mock"
        self.log_store: LogStore = LogStore()
        self.order_store: OrderStore = OrderStore()
        self._log_file_handler: RotatingFileHandler | None = None
        self._log_file_lock = threading.Lock()
        self.write_log(f"init: starting (mode={self.env_mode})", level="INFO", source="System")

        self.event_engine: EventEngine = event_engine or EventEngine(main_engine=self)
        if event_engine is not None:
            self.event_engine.set_main_engine(self)

        # Engines are constructed first; trading pairs may be overridden below
        self.market_engine = MarketEngine(main_engine=self)
        self.gateway_engine = GatewayEngine(main_engine=self, env_mode=self.env_mode)
        self.strategy_engine = StrategyEngine(main_engine=self)
        self.risk_engine = RiskEngine(main_engine=self)
        self.write_log("init: engines constructed", level="INFO", source="System")

        # One-time discovery of tradable pairs from the exchange; cache the AVAILABLE list only.
        try:
            self.write_log("init: discovering trading pairs via /v3/exchangeInfo", level="INFO", source="System")
            info = self.gateway_engine.get_exchange_info()
            pairs: list[str] = []
            if isinstance(info, dict):
                trade_pairs = info.get("TradePairs")
                if isinstance(trade_pairs, dict):
                    from .engine_gateway import GatewayEngine as _GW

                    for pair in trade_pairs.keys():
                        symbol = _GW._from_roostoo_pair(str(pair))
                        if symbol and symbol not in pairs:
                            pairs.append(symbol)
            if pairs:
                self.trading_pairs = pairs
                # Poll all pairs with one bulk /v3/ticker call per tick.
                self.gateway_engine.trading_pairs = list(pairs)
                self.market_engine.set_symbols(pairs)
                self.write_log(f"init: discovered {len(pairs)} trading pairs", level="INFO", source="System")
            else:
                self.write_log("init: no trading pairs discovered from /v3/exchangeInfo", level="WARN", source="System")
        except Exception as e:
            # Discovery failure should not stop the engine; market data will be limited.
            self.write_log(f"init: exchangeInfo discovery failed: {e}", level="ERROR", source="System")

        self.event_engine.start()
        self.write_log("init: event engine started", level="INFO", source="System")

        # Warm cached account snapshots immediately (do not wait for timer throttle).
        # This keeps `/account/*` useful right after startup.
        try:
            self.write_log("init: warming account cache (/v3/balance, /v3/pending_count)", level="INFO", source="System")
            self.gateway_engine._refresh_account_cache(force=True)
        except Exception:
            pass

    def add_strategy(self, strategy_name: str) -> None:
        """
        Add a strategy instance (no symbol input).
        """
        self.strategy_engine.add_strategy_by_name(strategy_name)

    def get_strategy(self, strategy_name: str):
        """Return the strategy instance with the given name (e.g. Strat1Pine_BTCUSDT), or None."""
        return self.strategy_engine.get_strategy(strategy_name)

    def start_strategy(self, strategy_name: str) -> None:
        """Start the strategy (independent start control)."""
        self.strategy_engine.start_strategy(strategy_name)

    def stop_strategy(self, strategy_name: str) -> None:
        """Stop the strategy (independent stop control). Strategy must be flat."""
        self.strategy_engine.stop_strategy(strategy_name)

    def delete_strategy(self, strategy_name: str) -> None:
        """
        Remove a strategy instance and its holdings.

        - Calls stop_strategy (if present)
        - Removes from StrategyEngine registry
        - Clears StrategyEngine holdings for this strategy
        """
        if self.strategy_engine.get_strategy(strategy_name) is not None:
            try:
                self.stop_strategy(strategy_name)
            except Exception:
                # Stop errors should not prevent deletion.
                pass
        self.strategy_engine.remove_strategy(strategy_name)
        self.strategy_engine.remove_strategy_holding(strategy_name)

    # ------------------------------------------------------------------
    # Gateway Public API façade (Roostoo v3)
    # ------------------------------------------------------------------

    def get_server_time(self):
        """Gateway: GET /v3/serverTime."""
        return self.gateway_engine.get_server_time()

    def get_exchange_info(self):
        """Gateway: GET /v3/exchangeInfo."""
        return self.gateway_engine.get_exchange_info()

    def get_all_trading_pairs(self) -> list[str]:
        """Return all discovered trading pairs as internal symbols (e.g. BTCUSDT)."""
        return list(self.trading_pairs)

    def get_ticker(self, symbol: str | None = None):
        """Gateway: GET /v3/ticker (optionally for one symbol)."""
        return self.gateway_engine.get_ticker(symbol)

    def get_balance(self):
        """Gateway: GET /v3/balance (SIGNED)."""
        return self.gateway_engine.get_balance()

    def pending_count(self):
        """Gateway: GET /v3/pending_count (SIGNED)."""
        return self.gateway_engine.pending_count()

    def get_pending_orders_by_symbol(self, strategy_name: str) -> dict[str, list[str]]:
        """Gateway: pending order ids grouped by symbol for a strategy."""
        return self.gateway_engine.get_pending_orders_by_symbol(strategy_name)

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        order_type: str | None = None,
    ):
        """Gateway: POST /v3/place_order (SIGNED)."""
        return self.gateway_engine.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
        )

    def cancel_order(self, order_id: str | None = None, symbol: str | None = None):
        """Gateway: POST /v3/cancel_order (SIGNED)."""
        return self.gateway_engine.cancel_order(order_id=order_id, symbol=symbol)

    def query_order(
        self,
        order_id: str | None = None,
        symbol: str | None = None,
        pending_only: bool | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ):
        """Gateway: POST /v3/query_order (SIGNED)."""
        return self.gateway_engine.query_order(
            order_id=order_id,
            symbol=symbol,
            pending_only=pending_only,
            offset=offset,
            limit=limit,
        )

    # ------------------------------------------------------------------
    # Event helper
    # ------------------------------------------------------------------

    def put_event(self, event_type: str, data: object | None = None) -> None:
        """Enqueue an event on the event engine."""
        self.event_engine.put(Event(event_type, data))

    def write_log(self, message: str, level: str = "INFO", source: str = "System") -> None:
        """Append a line to the system log stream (used by engines and control-plane UI)."""
        try:
            msg = self.log_store.append(message, level=level, source=source)

            # Persist logs on disk (rotating) under data/logs/.
            # Defaults can be overridden via env:
            # - LOG_FILE (default: data/logs/system.log)
            # - LOG_MAX_BYTES (default: 5_000_000)
            # - LOG_BACKUP_COUNT (default: 5)
            try:
                handler = self._log_file_handler
                if handler is None:
                    with self._log_file_lock:
                        handler = self._log_file_handler
                        if handler is None:
                            log_file = (os.getenv("LOG_FILE") or "data/logs/system.log").strip()
                            max_bytes = int(os.getenv("LOG_MAX_BYTES") or "5000000")
                            backup_count = int(os.getenv("LOG_BACKUP_COUNT") or "5")
                            os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
                            handler = RotatingFileHandler(
                                log_file,
                                maxBytes=max_bytes,
                                backupCount=backup_count,
                                encoding="utf-8",
                            )
                            self._log_file_handler = handler
                if handler is not None:
                    handler.stream.write(msg + "\n")
                    handler.flush()
            except Exception:
                # Never break engine due to file logging.
                pass
        except Exception:
            # Logging must never crash the engine.
            pass

    # ------------------------------------------------------------------
    # Intent handling (delegates to EventEngine)
    # ------------------------------------------------------------------

    def handle_intent(self, intent_type: str, payload: object | None = None) -> object | None:
        """Delegate to the event engine's intent handler."""
        return self.event_engine.handle_intent(intent_type, payload)


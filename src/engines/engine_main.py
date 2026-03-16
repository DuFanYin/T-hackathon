"""
Main engine: composition root and façade for the trading system.
"""

from __future__ import annotations

from typing import Optional

from .engine_event import Event, EventEngine
from .engine_gateway import GatewayEngine
from .engine_market import MarketEngine
from .engine_position import PositionEngine
from .engine_risk import RiskEngine
from .engine_strategy import StrategyEngine
from src.control.log_store import LogStore


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

        self.event_engine: EventEngine = event_engine or EventEngine(main_engine=self)
        if event_engine is not None:
            self.event_engine.set_main_engine(self)

        # Engines are constructed first; trading pairs may be overridden below
        self.market_engine = MarketEngine(main_engine=self)
        self.gateway_engine = GatewayEngine(main_engine=self, env_mode=self.env_mode)
        self.strategy_engine = StrategyEngine(main_engine=self)
        self.position_engine = PositionEngine(main_engine=self)
        self.risk_engine = RiskEngine(main_engine=self)

        # One-time discovery of tradable pairs from the exchange; cache the AVAILABLE list only.
        try:
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
            else:
                print("[MainEngine] No trading pairs discovered from /v3/exchangeInfo; system will run without market data.")
        except Exception as e:
            # Discovery failure should not stop the engine; market data will be limited.
            print(f"[MainEngine] exchangeInfo discovery failed: {e}")

        self.event_engine.start()

    def add_strategy(self, strategy_name: str, trading_pair: str) -> None:
        """Add a strategy for the trading pair. strategy_name is the class name (from AVAILABLE_STRATEGIES)."""
        self._ensure_pair_active(trading_pair)
        self.strategy_engine.add_strategy_for_pair(strategy_name, trading_pair)

    def _ensure_pair_active(self, trading_pair: str) -> None:
        """Ensure the trading pair is subscribed for market polling and cached in MarketEngine."""
        symbol = str(trading_pair).strip().upper()
        if not symbol:
            return

        if symbol not in self.active_pairs:
            self.active_pairs.append(symbol)

        if symbol not in self.gateway_engine.trading_pairs:
            self.gateway_engine.trading_pairs.append(symbol)

        # Pre-create buffers for this symbol (safe to call repeatedly).
        self.market_engine.set_symbols([symbol])

    def get_strategy(self, strategy_name: str):
        """Return the strategy instance with the given name (e.g. Strat1Pine_BTCUSDT), or None."""
        return self.strategy_engine.get_strategy(strategy_name)

    def init_strategy(self, strategy_name: str) -> None:
        """Call on_init() on the strategy."""
        self.strategy_engine.init_strategy(strategy_name)

    def start_strategy(self, strategy_name: str) -> None:
        """Start the strategy (independent start control)."""
        self.strategy_engine.start_strategy(strategy_name)

    def stop_strategy(self, strategy_name: str) -> None:
        """Stop the strategy (independent stop control)."""
        self.strategy_engine.stop_strategy(strategy_name)

    def delete_strategy(self, strategy_name: str) -> None:
        """
        Remove a strategy instance and its holdings.

        - Calls stop_strategy (if present)
        - Removes from StrategyEngine registry
        - Clears PositionEngine holdings for this strategy
        """
        if self.strategy_engine.get_strategy(strategy_name) is not None:
            try:
                self.stop_strategy(strategy_name)
            except Exception:
                # Stop errors should not prevent deletion.
                pass
        self.strategy_engine.remove_strategy(strategy_name)
        self.position_engine.remove_strategy_holding(strategy_name)

    # ------------------------------------------------------------------
    # Connectivity façade
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Delegate to gateway (if it implements connect)."""
        if hasattr(self.gateway_engine, "connect"):
            self.gateway_engine.connect()

    def disconnect(self) -> None:
        """Delegate to gateway and stop the event engine."""
        if hasattr(self.gateway_engine, "disconnect"):
            self.gateway_engine.disconnect()

        self.event_engine.stop()

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

    # ------------------------------------------------------------------
    # Intent handling (delegates to EventEngine)
    # ------------------------------------------------------------------

    def handle_intent(self, intent_type: str, payload: object | None = None) -> object | None:
        """Delegate to the event engine's intent handler."""
        return self.event_engine.handle_intent(intent_type, payload)


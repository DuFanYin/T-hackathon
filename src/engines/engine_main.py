"""
Main engine: composition root and façade for the trading system.
"""

from __future__ import annotations

import os
import threading
import time
from logging.handlers import RotatingFileHandler
from typing import Optional

from .engine_event import Event, EventEngine
from .engine_gateway import GatewayEngine
from .engine_market import MarketEngine
from .engine_risk import RiskEngine
from .engine_strategy import AVAILABLE_STRATEGIES, StrategyEngine
from src.control.log_store import LogStore
from src.control.order_store import OrderStore
from src.utilities.object import TradingPair


# ---------------------------------------------------------------------------
# Fallback precision table — used ONLY when /v3/exchangeInfo fails all retries.
#
# Values sourced from Roostoo live /v3/exchangeInfo (2026-03-20).
# Covers all 67 pairs on the exchange.
# ---------------------------------------------------------------------------
_FALLBACK_PAIR_RULES: dict[str, dict] = {
    # ── strategy_JH pairs ──
    "APTUSDT":         {"price_precision": 3, "amount_precision": 2, "mini_order": 10.0},
    "CRVUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "EIGENUSDT":       {"price_precision": 3, "amount_precision": 1, "mini_order": 10.0},
    "TAOUSDT":         {"price_precision": 1, "amount_precision": 4, "mini_order": 10.0},
    "UNIUSDT":         {"price_precision": 3, "amount_precision": 1, "mini_order": 10.0},
    "TRUMPUSDT":       {"price_precision": 2, "amount_precision": 1, "mini_order": 10.0},
    "BONKUSDT":        {"price_precision": 8, "amount_precision": 0, "mini_order": 10.0},
    "SHIBUSDT":        {"price_precision": 8, "amount_precision": 0, "mini_order": 10.0},
    # ── strategy_maliki top 20 by market cap ──
    "BTCUSDT":         {"price_precision": 0, "amount_precision": 5, "mini_order": 10.0},
    "ETHUSDT":         {"price_precision": 2, "amount_precision": 4, "mini_order": 10.0},
    "BNBUSDT":         {"price_precision": 1, "amount_precision": 3, "mini_order": 10.0},
    "SOLUSDT":         {"price_precision": 2, "amount_precision": 2, "mini_order": 10.0},
    "XRPUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "ADAUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "DOGEUSDT":        {"price_precision": 5, "amount_precision": 0, "mini_order": 10.0},
    "DOTUSDT":         {"price_precision": 3, "amount_precision": 2, "mini_order": 10.0},
    "LINKUSDT":        {"price_precision": 3, "amount_precision": 2, "mini_order": 10.0},
    "AVAXUSDT":        {"price_precision": 2, "amount_precision": 2, "mini_order": 10.0},
    "LTCUSDT":         {"price_precision": 2, "amount_precision": 3, "mini_order": 10.0},
    "TONUSDT":         {"price_precision": 3, "amount_precision": 2, "mini_order": 10.0},
    "XLMUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "HBARUSDT":        {"price_precision": 5, "amount_precision": 0, "mini_order": 10.0},
    "SUIUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "AAVEUSDT":        {"price_precision": 1, "amount_precision": 3, "mini_order": 10.0},
    "FILUSDT":         {"price_precision": 3, "amount_precision": 2, "mini_order": 10.0},
    "ICPUSDT":         {"price_precision": 2, "amount_precision": 2, "mini_order": 10.0},
    "NEARUSDT":        {"price_precision": 3, "amount_precision": 1, "mini_order": 10.0},
    "PEPEUSDT":        {"price_precision": 8, "amount_precision": 0, "mini_order": 10.0},
    # ── additional strategy_maliki coins ──
    "FETUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "SEIUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "PENDLEUSDT":      {"price_precision": 3, "amount_precision": 1, "mini_order": 10.0},
    "ENAUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "ONDOUSDT":        {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "ARBUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "WLDUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "CAKEUSDT":        {"price_precision": 3, "amount_precision": 1, "mini_order": 10.0},
    "TRXUSDT":         {"price_precision": 5, "amount_precision": 0, "mini_order": 10.0},
    "CFXUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "FLOKIUSDT":       {"price_precision": 7, "amount_precision": 0, "mini_order": 10.0},
    "WIFUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "PENGUUSDT":       {"price_precision": 5, "amount_precision": 0, "mini_order": 10.0},
    # ── remaining Roostoo pairs (from live /v3/exchangeInfo 2026-03-20) ──
    "1000CHEEMSUSDT":  {"price_precision": 6, "amount_precision": 0, "mini_order": 10.0},
    "ASTERUSDT":       {"price_precision": 3, "amount_precision": 2, "mini_order": 10.0},
    "AVNTUSDT":        {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "BIOUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "BMTUSDT":         {"price_precision": 5, "amount_precision": 1, "mini_order": 10.0},
    "EDENUSDT":        {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "FORMUSDT":        {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "HEMIUSDT":        {"price_precision": 5, "amount_precision": 1, "mini_order": 10.0},
    "LINEAUSDT":       {"price_precision": 5, "amount_precision": 0, "mini_order": 10.0},
    "LISTAUSDT":       {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "MIRAUSDT":        {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "OMNIUSDT":        {"price_precision": 2, "amount_precision": 2, "mini_order": 10.0},
    "OPENUSDT":        {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "PAXGUSDT":        {"price_precision": 2, "amount_precision": 4, "mini_order": 10.0},
    "PLUMEUSDT":       {"price_precision": 5, "amount_precision": 0, "mini_order": 10.0},
    "POLUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "PUMPUSDT":        {"price_precision": 6, "amount_precision": 0, "mini_order": 10.0},
    "SOMIUSDT":        {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "STOUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "SUSDT":           {"price_precision": 5, "amount_precision": 1, "mini_order": 10.0},
    "TUTUSDT":         {"price_precision": 5, "amount_precision": 0, "mini_order": 10.0},
    "VIRTUALUSDT":     {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "WLFIUSDT":        {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "XPLUSDT":         {"price_precision": 4, "amount_precision": 1, "mini_order": 10.0},
    "ZECUSDT":         {"price_precision": 2, "amount_precision": 3, "mini_order": 10.0},
    "ZENUSDT":         {"price_precision": 3, "amount_precision": 2, "mini_order": 10.0},
}


class MainEngine:
    """Builds all engines, starts the event loop, and exposes put_event, handle_intent, send_order, cancel_order."""

    def __init__(
        self,
        event_engine: Optional[EventEngine] = None,
        env_mode: str = "mock",
    ) -> None:
        # Always rely on remote discovery for *available* trading pairs; start empty here.
        # Note: we do NOT subscribe market polling to all available pairs (too slow).
        self.trading_pairs: list[str] = []  # internal symbols (same order as discovery)
        self.trading_pairs_by_symbol: dict[str, TradingPair] = {}  # cached exchangeInfo rules per symbol
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

        # One-time discovery with retries + fallback.
        self._exchange_info_ok: bool = self._discover_trading_pairs()

        # Create instances for all known strategies on system init.
        # Place this AFTER market symbol buffers are seeded so strategies that derive symbol lists
        # from MarketEngine cache don't start with an empty symbol universe.
        for strat_name in sorted(list(AVAILABLE_STRATEGIES.keys())):
            try:
                self.add_strategy(strat_name)
            except Exception as e:
                self.write_log(f"init: failed to create strategy {strat_name}: {e}", level="ERROR", source="System")

        self.event_engine.start()
        self.write_log("init: event engine started", level="INFO", source="System")

        # Warm cached account snapshots immediately (do not wait for timer throttle).
        # This keeps `/account/*` useful right after startup.
        try:
            self.write_log("init: warming account cache (/v3/balance, query_order pending)", level="INFO", source="System")
            self.gateway_engine._refresh_account_cache(force=True)
        except Exception:
            pass

    def add_strategy(self, strategy_name: str) -> None:
        """
        Add a strategy instance (no symbol input).
        """
        self.strategy_engine.add_strategy_by_name(strategy_name)

    def get_strategy(self, strategy_name: str):
        """Return the strategy instance with the given name, or None."""
        return self.strategy_engine.get_strategy(strategy_name)

    def start_strategy(self, strategy_name: str) -> None:
        """Start the strategy (independent start control).

        Refuses to start if /v3/exchangeInfo failed AND no fallback precision
        data is available — orders would be sent unrounded, causing step-size
        rejections and potential ghost positions.
        """
        if not self._exchange_info_ok and not self.trading_pairs_by_symbol:
            raise RuntimeError(
                f"Cannot start {strategy_name}: /v3/exchangeInfo failed after retries "
                "and no fallback precision data is loaded. Orders would be sent with "
                "unrounded quantities, causing step-size rejections."
            )
        if not self._exchange_info_ok:
            self.write_log(
                f"WARNING: starting {strategy_name} with FALLBACK precision data — "
                "/v3/exchangeInfo discovery failed. Pairs not in the fallback table "
                "will have unrounded orders.",
                level="WARN",
                source="System",
            )
        self.strategy_engine.start_strategy(strategy_name)

    def stop_strategy(self, strategy_name: str) -> None:
        """Stop the strategy (independent stop control). Strategy must be flat."""
        self.strategy_engine.stop_strategy(strategy_name)

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

    def get_trading_pair(self, symbol: str) -> TradingPair | None:
        """Cached exchangeInfo row for an internal symbol, if discovered at startup."""
        sym = str(symbol or "").strip().upper()
        return self.trading_pairs_by_symbol.get(sym) if sym else None

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
    # Exchange info discovery (retries + fallback)
    # ------------------------------------------------------------------

    def _discover_trading_pairs(self, max_retries: int = 3, retry_delay: float = 5.0) -> bool:
        """Discover trading pairs from /v3/exchangeInfo with retries.

        Returns True if live discovery succeeded on any attempt.
        On total failure, applies fallback precision table and returns False.
        """
        for attempt in range(1, max_retries + 1):
            self.write_log(
                f"init: /v3/exchangeInfo attempt {attempt}/{max_retries}",
                level="INFO", source="System",
            )
            try:
                info = self.gateway_engine.get_exchange_info()
                pairs = self._parse_exchange_info(info)
                if pairs:
                    self.trading_pairs = pairs
                    self.gateway_engine.trading_pairs = list(pairs)
                    self.gateway_engine.trading_pairs_by_symbol = self.trading_pairs_by_symbol
                    self.market_engine.set_symbols(pairs)
                    self.write_log(
                        f"init: discovered {len(pairs)} trading pairs",
                        level="INFO", source="System",
                    )
                    return True
                self.write_log(
                    f"init: /v3/exchangeInfo attempt {attempt} returned no TradePairs",
                    level="WARN", source="System",
                )
            except Exception as e:
                self.write_log(
                    f"init: /v3/exchangeInfo attempt {attempt} failed: {e}",
                    level="ERROR", source="System",
                )

            if attempt < max_retries:
                self.write_log(
                    f"init: retrying /v3/exchangeInfo in {retry_delay}s...",
                    level="INFO", source="System",
                )
                time.sleep(retry_delay)

        # All retries exhausted — apply fallback
        self.write_log(
            f"CRITICAL: /v3/exchangeInfo failed after {max_retries} retries. "
            "Applying fallback precision table for known pairs. "
            "Orders for unlisted pairs will be UNROUNDED and likely rejected.",
            level="ERROR", source="System",
        )
        self._apply_fallback_precisions()
        return False

    # Pairs whose precision we validate at startup — mismatch here means
    # every order for that pair would be rejected.
    _CRITICAL_PAIR_PRECISIONS: dict[str, tuple[int, int]] = {
        # symbol: (expected_price_precision, expected_amount_precision)
        "TAOUSDT":  (1, 4),
        "FETUSDT":  (4, 1),
        "BONKUSDT": (8, 0),
        "SHIBUSDT": (8, 0),
        "APTUSDT":  (3, 2),
    }

    def _parse_exchange_info(self, info: object) -> list[str]:
        """Parse /v3/exchangeInfo response into trading_pairs_by_symbol. Returns symbol list."""
        if not isinstance(info, dict):
            return []
        trade_pairs = info.get("TradePairs")
        if not isinstance(trade_pairs, dict):
            return []

        from .engine_gateway import GatewayEngine as _GW

        pairs: list[str] = []
        for pair_key, spec in trade_pairs.items():
            symbol = _GW._from_roostoo_pair(str(pair_key))
            if not symbol or symbol in pairs:
                continue
            self.trading_pairs_by_symbol[symbol] = TradingPair.from_exchange_entry(
                str(pair_key), spec, symbol=symbol,
            )
            pairs.append(symbol)

        # Log precision for every discovered pair and validate critical ones.
        self._log_and_validate_precisions()
        return pairs

    def _log_and_validate_precisions(self) -> None:
        """Log precisions for discovered pairs; warn if critical pairs differ from expected."""
        for symbol in sorted(self.trading_pairs_by_symbol):
            tp = self.trading_pairs_by_symbol[symbol]
            self.write_log(
                f"exchangeInfo: {tp.pair} → price_prec={tp.price_precision} "
                f"amount_prec={tp.amount_precision} mini_order={tp.mini_order}",
                level="DEBUG", source="System",
            )

        for symbol, (exp_px, exp_amt) in self._CRITICAL_PAIR_PRECISIONS.items():
            tp = self.trading_pairs_by_symbol.get(symbol)
            if tp is None:
                self.write_log(
                    f"WARN: critical pair {symbol} NOT found in exchangeInfo",
                    level="WARN", source="System",
                )
                continue
            mismatches = []
            if tp.price_precision != exp_px:
                mismatches.append(
                    f"price_precision: expected={exp_px} got={tp.price_precision}"
                )
            if tp.amount_precision != exp_amt:
                mismatches.append(
                    f"amount_precision: expected={exp_amt} got={tp.amount_precision}"
                )
            if mismatches:
                self.write_log(
                    f"WARN: {symbol} precision mismatch: {', '.join(mismatches)} — "
                    "update _CRITICAL_PAIR_PRECISIONS or _FALLBACK_PAIR_RULES",
                    level="WARN", source="System",
                )
            else:
                self.write_log(
                    f"OK: {symbol} precision verified px={exp_px} amt={exp_amt}",
                    level="INFO", source="System",
                )

    def _apply_fallback_precisions(self) -> None:
        """Load hardcoded step sizes for known pairs (does not overwrite live data)."""
        added = 0
        for symbol, rules in _FALLBACK_PAIR_RULES.items():
            if symbol in self.trading_pairs_by_symbol:
                continue  # live data takes priority
            base = symbol.replace("USDT", "")
            self.trading_pairs_by_symbol[symbol] = TradingPair(
                pair=f"{base}/USD",
                symbol=symbol,
                coin=base,
                unit="USD",
                can_trade=True,
                price_precision=int(rules["price_precision"]),
                amount_precision=int(rules["amount_precision"]),
                mini_order=float(rules["mini_order"]),
            )
            added += 1

        if added:
            all_symbols = list(self.trading_pairs_by_symbol.keys())
            self.trading_pairs = all_symbols
            self.gateway_engine.trading_pairs = list(all_symbols)
            self.gateway_engine.trading_pairs_by_symbol = self.trading_pairs_by_symbol
            self.market_engine.set_symbols(all_symbols)
            self.write_log(
                f"init: loaded {added} fallback pair precisions "
                f"(total {len(self.trading_pairs_by_symbol)} pairs)",
                level="WARN", source="System",
            )

    # ------------------------------------------------------------------
    # Intent handling (delegates to EventEngine)
    # ------------------------------------------------------------------

    def handle_intent(self, intent_type: str, payload: object | None = None) -> object | None:
        """Delegate to the event engine's intent handler."""
        return self.event_engine.handle_intent(intent_type, payload)


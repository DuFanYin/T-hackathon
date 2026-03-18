"""
Strat2: Multi-Asset Momentum Rotation (v2)

Plugs into the team's event-driven framework via StrategyTemplate.
Signal source: MarketEngine (bars from GatewayEngine Binance 5m injection).
Execution: via framework's send_order() -> GatewayEngine -> Roostoo API.

Production parameters (from backtest validation):
  lookback=96 (8h), top_n=2, rebalance_every=48 (4h), trailing_stop=3%,
  min_hold=24 (2h), regime_ma=288 (24h BTC MA)

Capital allocation: 85% of portfolio ($850k of $1M).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.strategies.template import StrategyTemplate

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine

log = logging.getLogger("strat2")

# Coins to track — base symbols (MarketEngine uses BTCUSDT, ETHUSDT, etc.)
TRACKED_COINS = [
    # Large cap
    "BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "DOT", "LINK",
    "AVAX", "LTC", "TON", "XLM", "HBAR", "SUI",
    # Mid cap
    "UNI", "AAVE", "FIL", "ICP", "NEAR", "APT", "FET", "SEI", "TAO",
    "PENDLE", "ENA", "ONDO", "ARB", "CRV", "WLD", "EIGEN", "CAKE", "TRX", "CFX",
    # Meme
    "PEPE", "SHIB", "BONK", "FLOKI", "WIF", "TRUMP", "PENGU",
]


class Strat2Momentum(StrategyTemplate):
    """
    Multi-asset momentum rotation with BTC regime filter.

    Every `rebalance_every` timer ticks:
      1. Check regime: is BTC above its 24h moving average? If not, close all and go cash.
      2. Rank all assets by 8-hour momentum (% return over last 96 5m-candles).
      3. Hold the top 2 movers. Exit anything not in top 2 (if min hold met).
      4. Trail every position with a 3% trailing stop (after 2h min hold).
    """

    def __init__(
        self,
        main_engine: "MainEngine",
        strategy_name: str = "Strat2Momentum",
        setting: dict[str, Any] | None = None,
    ) -> None:
        s = dict(setting or {})
        s.setdefault("timer_trigger", 1)  # Run every tick; rebalance_every uses internal counting
        s.setdefault("interval", "5m")  # This strategy uses 5m bars
        super().__init__(main_engine, strategy_name, s)

        # Strategy-owned symbol universe (no UI input needed).
        self.symbols = [f"{c}USDT" for c in TRACKED_COINS]

        # ── Order symbol format ──
        # GatewayEngine expects internal symbols like BTCUSDT so it can convert to Roostoo pairs BTC/USD.
        # Keep configurable, but default to gateway-compatible format.
        self.order_symbol_format: str = str(s.get("order_symbol_format", "gateway")).lower()
        # Supported:
        # - "gateway": BTCUSDT (preferred)
        # - "slash": BTC/USD (passed through by gateway)

        # ── Strategy parameters (validated by backtest) ──
        self.lookback_candles: int = int(s.get("lookback_candles", 96))
        self.top_n: int = int(s.get("top_n", 2))
        self.rebalance_every: int = int(s.get("rebalance_every", 48))
        self.trailing_stop_pct: float = float(s.get("trailing_stop_pct", 3.0))
        self.min_hold_candles: int = int(s.get("min_hold_candles", 24))
        self.regime_ma_candles: int = int(s.get("regime_ma_candles", 288))
        self.min_momentum_pct: float = float(s.get("min_momentum_pct", 0.5))
        self.capital_allocation: float = float(s.get("capital_allocation", 850_000))
        self.max_single_alloc_pct: float = float(s.get("max_single_alloc_pct", 50.0))

        # ── Internal state ──
        self._tick_count: int = 0
        self._positions: dict[str, dict] = {}
        # {coin: {"qty", "entry_price", "peak_price", "entry_tick", "roostoo_pair"}}

    def _format_pair(self, coin: str) -> str:
        """Format Roostoo pair for logging (e.g. 'BTC/USD')."""
        return f"{coin}/USD"

    def _format_order_symbol(self, coin: str) -> str:
        """Format symbol for GatewayEngine.place_order()."""
        if self.order_symbol_format == "slash":
            return self._format_pair(coin)
        # gateway-compatible internal symbol (so GatewayEngine converts USDT -> USD pair)
        return f"{coin}USDT"

    def _log_reconciliation(self) -> None:
        """Log Strat2 internal positions vs engine holdings and gateway pending orders."""
        strat_pos = {self._format_order_symbol(c): p["qty"] for c, p in self._positions.items()}
        eng_pos = {}
        if hasattr(self._main, "strategy_engine") and self._main.strategy_engine:
            holding = self._main.strategy_engine.get_holding(self.strategy_name)
            eng_pos = {s: p.quantity for s, p in holding.positions.items() if p.quantity != 0}
        pending = self.get_pending_orders()  # engine cached pending by symbol
        diff = set(strat_pos.keys()) ^ set(eng_pos.keys())
        if diff:
            self.write_log(
                f"RECONCILE: Strat2={list(strat_pos)} | Engine={list(eng_pos)} | pending={list(pending)} | "
                f"mismatch={list(diff)} — check fill/order status",
                level="WARN",
            )
        elif strat_pos or pending:
            self.write_log(f"RECONCILE: OK | Strat2={strat_pos} Engine={eng_pos} pending={pending}", level="DEBUG")

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    def on_init_logic(self) -> None:
        self.write_log(
            f"Strat2Momentum init: lookback={self.lookback_candles} "
            f"top_n={self.top_n} rebal={self.rebalance_every} "
            f"trail={self.trailing_stop_pct}% min_hold={self.min_hold_candles} "
            f"regime_ma={self.regime_ma_candles} alloc=${self.capital_allocation:,.0f} "
            f"order_symbol={self.order_symbol_format}",
            level="INFO",
        )

    def history_requirements(self) -> list[dict[str, object]]:
        # Backfill enough candles so init/start don't wait for slow warmup.
        ival = self.interval.binance
        reqs: list[dict[str, object]] = []
        # Regime filter uses BTC MA (default 288 == 24h on 5m candles).
        reqs.append({"symbol": "BTCUSDT", "interval": ival, "bars": int(self.regime_ma_candles)})
        # Momentum calculations need lookback window for each tracked coin.
        lookback = int(self.lookback_candles)
        for c in TRACKED_COINS:
            reqs.append({"symbol": f"{c}USDT", "interval": ival, "bars": lookback})
        return reqs

    def on_stop_logic(self) -> None:
        self.write_log("Strat2Momentum stopping — closing all positions", level="INFO")
        self._close_all_positions("strategy_stop")

    # ──────────────────────────────────────────
    # Main timer logic (called every tick)
    # ──────────────────────────────────────────

    def on_timer_logic(self) -> None:
        self._tick_count += 1

        if not self._has_enough_data():
            if self._tick_count % 10 == 0:
                btc_bars = 0
                me = getattr(self._main, "market_engine", None)
                if me:
                    btc_bars = me.get_bar_count("BTCUSDT", self.interval.binance)
                self.write_log(
                    f"Warming up... {btc_bars} BTC bars (need {self.regime_ma_candles})",
                    level="DEBUG",
                )
            return

        current_prices = self._get_current_prices()
        if not current_prices:
            return

        self._check_trailing_stops(current_prices)

        if self._tick_count % self.rebalance_every == 0:
            self._rebalance(current_prices)
            self._log_reconciliation()

    def _has_enough_data(self) -> bool:
        """Check if MarketEngine has enough BTC bars for regime filter."""
        me = getattr(self._main, "market_engine", None)
        if not me:
            return False
        return me.get_bar_count("BTCUSDT", self.interval.binance) >= self.regime_ma_candles

    def _get_current_prices(self) -> dict[str, float]:
        """Get latest close price for each coin from MarketEngine."""
        prices: dict[str, float] = {}
        me = getattr(self._main, "market_engine", None)
        if not me:
            return prices
        for coin in TRACKED_COINS:
            symbol = f"{coin}USDT"
            sd = me.get_symbol(symbol)
            if sd and getattr(sd, "last_price", 0.0) > 0:
                prices[coin] = float(sd.last_price)
        return prices

    # ──────────────────────────────────────────
    # Regime filter
    # ──────────────────────────────────────────

    def _is_regime_bullish(self) -> bool:
        """True if BTC is above its N-period moving average (from MarketEngine bars)."""
        me = getattr(self._main, "market_engine", None)
        if not me:
            return False
        bars = me.get_last_bars("BTCUSDT", self.regime_ma_candles, self.interval.binance)
        if len(bars) < self.regime_ma_candles:
            return False
        btc_price = bars[-1].close
        btc_ma = sum(b.close for b in bars[-self.regime_ma_candles:]) / self.regime_ma_candles
        return btc_price > btc_ma

    # ──────────────────────────────────────────
    # Momentum ranking
    # ──────────────────────────────────────────

    def _get_momentum_rankings(self) -> list[dict]:
        """
        Rank all coins by momentum (% return over lookback period).
        Returns sorted list of dicts: [{coin, momentum_pct, price}, ...]
        """
        me = getattr(self._main, "market_engine", None)
        if not me:
            return []
        rankings: list[dict] = []
        for coin in TRACKED_COINS:
            symbol = f"{coin}USDT"
            bars = me.get_last_bars(symbol, self.lookback_candles, self.interval.binance)
            if len(bars) < self.lookback_candles:
                continue
            past = bars[0].close
            current = bars[-1].close
            if past <= 0 or current <= 0:
                continue
            momentum_pct = (current - past) / past * 100
            if momentum_pct < self.min_momentum_pct:
                continue
            rankings.append({
                "coin": coin,
                "momentum_pct": momentum_pct,
                "price": current,
                "roostoo_pair": self._format_pair(coin),
                "roostoo_symbol": self._format_order_symbol(coin),
            })
        rankings.sort(key=lambda x: x["momentum_pct"], reverse=True)
        return rankings

    # ──────────────────────────────────────────
    # Trailing stops
    # ──────────────────────────────────────────

    def _check_trailing_stops(self, current_prices: dict) -> None:
        """Check and execute trailing stops (respecting min hold)."""
        to_close = []

        for coin, pos in self._positions.items():
            price = current_prices.get(coin)
            if not price:
                continue

            # Update peak
            if price > pos["peak_price"]:
                pos["peak_price"] = price

            # Respect minimum hold period
            ticks_held = self._tick_count - pos["entry_tick"]
            if ticks_held < self.min_hold_candles:
                continue

            # Check trailing stop
            dd = (pos["peak_price"] - price) / pos["peak_price"] * 100
            if dd >= self.trailing_stop_pct:
                self.write_log(
                    f"TRAILING STOP {coin}: peak={pos['peak_price']:.4f} "
                    f"now={price:.4f} dd={dd:.1f}%",
                    level="WARN",
                )
                to_close.append(coin)

        for coin in to_close:
            self._close_position(coin, "trailing_stop")

    # ──────────────────────────────────────────
    # Rebalance
    # ──────────────────────────────────────────

    def _rebalance(self, current_prices: dict) -> None:
        """Core rebalance logic: regime check → rank → rotate."""
        regime = self._is_regime_bullish()

        # If bearish regime, close positions that have met min hold
        if not regime:
            n = len(self._positions)
            self.write_log(f"REGIME: Bearish (BTC below MA) — exiting {n} position(s)", level="WARN")
            for coin in list(self._positions.keys()):
                ticks_held = self._tick_count - self._positions[coin]["entry_tick"]
                if ticks_held >= self.min_hold_candles:
                    self._close_position(coin, "regime_bearish")
            return

        # Bullish regime — rank and rotate
        rankings = self._get_momentum_rankings()

        if rankings:
            self.write_log(
                f"REBALANCE: regime=BULL | top movers: "
                + ", ".join(f"{r['coin']}({r['momentum_pct']:+.1f}%)" for r in rankings[:5]),
                level="INFO",
            )
        else:
            self.write_log("REBALANCE: No assets meet momentum threshold", level="WARN")
            return

        target_coins = [r["coin"] for r in rankings[:self.top_n]]

        # Exit positions not in target (if min hold met)
        for coin in list(self._positions.keys()):
            if coin not in target_coins:
                ticks_held = self._tick_count - self._positions[coin]["entry_tick"]
                if ticks_held >= self.min_hold_candles:
                    self.write_log(f"ROTATION EXIT: {coin} no longer in top {self.top_n}", level="INFO")
                    self._close_position(coin, "rotation")

        # Enter new targets
        for rank_info in rankings[:self.top_n]:
            coin = rank_info["coin"]
            if coin in self._positions:
                continue  # already holding

            slots_open = self.top_n - len(self._positions)
            if slots_open <= 0:
                break

            self._open_position(
                coin=coin,
                pair=rank_info["roostoo_pair"],
                price=rank_info["price"],
                momentum=rank_info["momentum_pct"],
                slots_open=slots_open,
            )

    # ──────────────────────────────────────────
    # Order execution
    # ──────────────────────────────────────────

    def _open_position(self, coin: str, pair: str, price: float,
                       momentum: float, slots_open: int) -> None:
        """Buy via framework's send_order."""
        # Size: equal allocation across available slots
        max_per = self.capital_allocation * (self.max_single_alloc_pct / 100)
        alloc = min(self.capital_allocation / self.top_n, max_per)

        qty = alloc / price
        # Round to reasonable precision
        qty = round(qty, 5)

        if qty <= 0 or alloc < 10:
            self.write_log(
                f"BUY {coin} skipped: qty={qty:.5f} alloc=${alloc:,.0f} (min $10)",
                level="WARN",
            )
            return

        # Use LIMIT order for lower commission
        # Set limit slightly above current price to ensure fill
        limit_price = round(price * 1.001, 8)

        self.write_log(
            f"BUY {coin}: qty={qty:.5f} limit={limit_price:.4f} "
            f"alloc=${alloc:,.0f} momentum={momentum:+.2f}%",
            level="INFO",
        )

        roostoo_symbol = self._format_order_symbol(coin)
        order_id = self.send_order(
            symbol=roostoo_symbol,
            side="BUY",
            quantity=qty,
            price=limit_price,
            order_type="LIMIT",
        )

        # Track position internally
        self._positions[coin] = {
            "qty": qty,
            "entry_price": price,
            "peak_price": price,
            "entry_tick": self._tick_count,
            "roostoo_pair": pair,
            "roostoo_symbol": roostoo_symbol,
            "order_id": order_id,
        }

    def _close_position(self, coin: str, reason: str) -> None:
        """Sell via framework's send_order."""
        pos = self._positions.get(coin)
        if not pos:
            return

        current_price = 0.0
        me = getattr(self._main, "market_engine", None)
        if me:
            sd = me.get_symbol(f"{coin}USDT")
            if sd and getattr(sd, "last_price", 0.0) > 0:
                current_price = float(sd.last_price)

        self.write_log(
            f"SELL {coin}: qty={pos['qty']:.5f} reason={reason} "
            f"entry={pos['entry_price']:.4f} now={current_price:.4f}",
            level="INFO",
        )

        self.send_order(
            symbol=pos["roostoo_symbol"],
            side="SELL",
            quantity=pos["qty"],
            price=current_price,
            order_type="MARKET",
        )

        del self._positions[coin]

    def _close_all_positions(self, reason: str) -> None:
        """Close all positions."""
        for coin in list(self._positions.keys()):
            self._close_position(coin, reason)

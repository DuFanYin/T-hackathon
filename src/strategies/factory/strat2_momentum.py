"""
Strat2: Multi-Asset Momentum Rotation (v2)

Plugs into the team's event-driven framework via StrategyTemplate.
Signal source: Binance public API (5m candles for momentum ranking).
Execution: via framework's send_order() -> GatewayEngine -> Roostoo API.

Production parameters (from backtest validation):
  lookback=96 (8h), top_n=2, rebalance_every=48 (4h), trailing_stop=3%,
  min_hold=24 (2h), regime_ma=288 (24h BTC MA)

Capital allocation: 85% of portfolio ($850k of $1M).
"""

from __future__ import annotations

import time
import logging
from typing import TYPE_CHECKING, Any
from collections import deque

import requests

from src.strategies.template import StrategyTemplate

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine

log = logging.getLogger("strat2")

# Binance public API (no key needed)
BINANCE_URL = "https://api.binance.com"

# Coins to track — maps Roostoo symbol to Binance symbol
# Only includes coins available on BOTH Roostoo and Binance
TRACKED_COINS = {
    # Large cap
    "BTC": "BTCUSDT", "ETH": "ETHUSDT", "BNB": "BNBUSDT",
    "SOL": "SOLUSDT", "XRP": "XRPUSDT", "ADA": "ADAUSDT",
    "DOGE": "DOGEUSDT", "DOT": "DOTUSDT", "LINK": "LINKUSDT",
    "AVAX": "AVAXUSDT", "LTC": "LTCUSDT", "TON": "TONUSDT",
    "XLM": "XLMUSDT", "HBAR": "HBARUSDT", "SUI": "SUIUSDT",
    # Mid cap
    "UNI": "UNIUSDT", "AAVE": "AAVEUSDT", "FIL": "FILUSDT",
    "ICP": "ICPUSDT", "NEAR": "NEARUSDT", "APT": "APTUSDT",
    "FET": "FETUSDT", "SEI": "SEIUSDT", "TAO": "TAOUSDT",
    "PENDLE": "PENDLEUSDT", "ENA": "ENAUSDT", "ONDO": "ONDOUSDT",
    "ARB": "ARBUSDT", "CRV": "CRVUSDT", "WLD": "WLDUSDT",
    "EIGEN": "EIGENUSDT", "CAKE": "CAKEUSDT", "TRX": "TRXUSDT",
    "CFX": "CFXUSDT",
    # Meme
    "PEPE": "PEPEUSDT", "SHIB": "SHIBUSDT", "BONK": "BONKUSDT",
    "FLOKI": "FLOKIUSDT", "WIF": "WIFUSDT", "TRUMP": "TRUMPUSDT",
    "PENGU": "PENGUUSDT",
}


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
        super().__init__(main_engine, strategy_name, s)

        # ── Symbol format (configurable for gateway compatibility) ──
        # Default "USD" produces pair "BTC/USD", order symbol "BTCUSD"
        self.quote_asset: str = str(s.get("quote_asset", "USD")).upper()
        self.order_symbol_format: str = str(s.get("order_symbol_format", "compact")).lower()
        # "compact" = "BTCUSD", "slash" = "BTC/USD"

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

        # Price history buffers for each coin (stores close prices)
        self._price_buffers: dict[str, deque] = {
            coin: deque(maxlen=max(self.lookback_candles, self.regime_ma_candles) + 50)
            for coin in TRACKED_COINS
        }

        # BTC close prices for regime filter
        self._btc_closes: deque = deque(
            maxlen=self.regime_ma_candles + 50
        )

        self._last_fetch_time: float = 0
        self._initialized_data: bool = False

    def _format_pair(self, coin: str) -> str:
        """Format trading pair (e.g. 'BTC/USD'). Configurable via quote_asset."""
        return f"{coin}/{self.quote_asset}"

    def _format_order_symbol(self, coin: str) -> str:
        """Format symbol for order API. 'compact'=BTCUSD, 'slash'=BTC/USD."""
        if self.order_symbol_format == "slash":
            return self._format_pair(coin)
        return f"{coin}{self.quote_asset}"

    def _log_reconciliation(self) -> None:
        """Log Strat2 internal positions vs PositionEngine for reconciliation (self-contained)."""
        strat_pos = {self._format_order_symbol(c): p["qty"] for c, p in self._positions.items()}
        eng_pos = {}
        if hasattr(self._main, "position_engine") and self._main.position_engine:
            holding = self._main.position_engine.get_holding(self.strategy_name)
            eng_pos = {s: p.quantity for s, p in holding.positions.items() if p.quantity != 0}
        diff = set(strat_pos.keys()) ^ set(eng_pos.keys())
        if diff:
            self.write_log(
                f"RECONCILE: Strat2={list(strat_pos)} | PositionEngine={list(eng_pos)} | "
                f"mismatch={list(diff)} — check fill/order status"
            )
        elif strat_pos:
            self.write_log(f"RECONCILE: OK | Strat2={strat_pos} PositionEngine={eng_pos}")

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    def on_init_logic(self) -> None:
        self.write_log(
            f"Strat2Momentum init: lookback={self.lookback_candles} "
            f"top_n={self.top_n} rebal={self.rebalance_every} "
            f"trail={self.trailing_stop_pct}% min_hold={self.min_hold_candles} "
            f"regime_ma={self.regime_ma_candles} alloc=${self.capital_allocation:,.0f} "
            f"symbol_format={self.quote_asset} order_symbol={self.order_symbol_format}"
        )

    def on_stop_logic(self) -> None:
        self.write_log("Strat2Momentum stopping — closing all positions")
        self._close_all_positions("strategy_stop")

    # ──────────────────────────────────────────
    # Main timer logic (called every tick)
    # ──────────────────────────────────────────

    def on_timer_logic(self) -> None:
        self._tick_count += 1

        # Fetch latest prices from Binance (throttled to avoid rate limits)
        self._fetch_prices()

        if not self._has_enough_data():
            if self._tick_count % 10 == 0:
                self.write_log(f"Warming up... {len(self._btc_closes)} BTC candles "
                              f"(need {self.regime_ma_candles})")
            return

        # Get current prices
        current_prices = self._get_current_prices()
        if not current_prices:
            return

        # ── Always check trailing stops ──
        self._check_trailing_stops(current_prices)

        # ── Rebalance on schedule ──
        if self._tick_count % self.rebalance_every == 0:
            self._rebalance(current_prices)
            self._log_reconciliation()

    # ──────────────────────────────────────────
    # Binance data fetching
    # ──────────────────────────────────────────

    def _fetch_prices(self) -> None:
        """Fetch latest 5m close from Binance for all tracked coins."""
        now = time.time()
        # Throttle: fetch at most every 30 seconds
        if now - self._last_fetch_time < 30:
            return
        self._last_fetch_time = now

        for coin, binance_sym in TRACKED_COINS.items():
            try:
                # If we haven't initialized, fetch full history
                if not self._initialized_data:
                    limit = max(self.lookback_candles, self.regime_ma_candles) + 10
                else:
                    limit = 2  # just latest candle

                url = f"{BINANCE_URL}/api/v3/klines"
                r = requests.get(url, params={
                    "symbol": binance_sym, "interval": "5m", "limit": limit
                }, timeout=5)

                if r.status_code != 200:
                    continue

                klines = r.json()
                for k in klines:
                    close = float(k[4])
                    self._price_buffers[coin].append(close)

                    if coin == "BTC":
                        self._btc_closes.append(close)

                time.sleep(0.05)  # rate limit courtesy

            except Exception as e:
                log.debug(f"Fetch {coin} failed: {e}")

        if not self._initialized_data and self._has_enough_data():
            self._initialized_data = True
            self.write_log(f"Data initialized: {len(self._btc_closes)} BTC candles loaded")

    def _has_enough_data(self) -> bool:
        """Check if we have enough history for all calculations."""
        return len(self._btc_closes) >= self.regime_ma_candles

    def _get_current_prices(self) -> dict[str, float]:
        """Get latest close price for each coin."""
        prices = {}
        for coin in TRACKED_COINS:
            buf = self._price_buffers[coin]
            if buf:
                prices[coin] = buf[-1]
        return prices

    # ──────────────────────────────────────────
    # Regime filter
    # ──────────────────────────────────────────

    def _is_regime_bullish(self) -> bool:
        """True if BTC is above its N-period moving average."""
        if len(self._btc_closes) < self.regime_ma_candles:
            return False

        btc_price = self._btc_closes[-1]
        btc_ma = sum(list(self._btc_closes)[-self.regime_ma_candles:]) / self.regime_ma_candles
        return btc_price > btc_ma

    # ──────────────────────────────────────────
    # Momentum ranking
    # ──────────────────────────────────────────

    def _get_momentum_rankings(self) -> list[dict]:
        """
        Rank all coins by momentum (% return over lookback period).
        Returns sorted list of dicts: [{coin, momentum_pct, price}, ...]
        """
        rankings = []
        for coin in TRACKED_COINS:
            buf = self._price_buffers[coin]
            if len(buf) < self.lookback_candles:
                continue

            current = buf[-1]
            past = buf[-self.lookback_candles]

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
                    f"now={price:.4f} dd={dd:.1f}%"
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
            self.write_log("REGIME: Bearish (BTC below MA) — exiting positions")
            for coin in list(self._positions.keys()):
                ticks_held = self._tick_count - self._positions[coin]["entry_tick"]
                if ticks_held >= self.min_hold_candles:
                    self._close_position(coin, "regime_bearish")
            return

        # Bullish regime — rank and rotate
        rankings = self._get_momentum_rankings()

        if rankings:
            top_coins = [r["coin"] for r in rankings[:min(5, len(rankings))]]
            self.write_log(
                f"REBALANCE: regime=BULL | top movers: "
                + ", ".join(f"{r['coin']}({r['momentum_pct']:+.1f}%)" for r in rankings[:5])
            )
        else:
            self.write_log("REBALANCE: No assets meet momentum threshold")
            return

        target_coins = [r["coin"] for r in rankings[:self.top_n]]

        # Exit positions not in target (if min hold met)
        for coin in list(self._positions.keys()):
            if coin not in target_coins:
                ticks_held = self._tick_count - self._positions[coin]["entry_tick"]
                if ticks_held >= self.min_hold_candles:
                    self.write_log(f"ROTATION EXIT: {coin} no longer in top {self.top_n}")
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
            return

        # Use LIMIT order for lower commission
        # Set limit slightly above current price to ensure fill
        limit_price = round(price * 1.001, 8)

        self.write_log(
            f"BUY {coin}: qty={qty:.5f} limit={limit_price:.4f} "
            f"alloc=${alloc:,.0f} momentum={momentum:+.2f}%"
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
        buf = self._price_buffers.get(coin)
        if buf:
            current_price = buf[-1]

        self.write_log(
            f"SELL {coin}: qty={pos['qty']:.5f} reason={reason} "
            f"entry={pos['entry_price']:.4f} now={current_price:.4f}"
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

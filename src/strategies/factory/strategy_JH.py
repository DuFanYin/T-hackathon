"""
strategy_JH: Multi-Asset Momentum Rotation (JH tuning)

Tuned parameters per request:
- Lookback: 4h → 48h (on 5m bars: 576 candles)
- Top N: 3 → 1
- Rebalance: every 4h → every 24h (on timer ticks: 288)
- Trailing stop: 3% → 8%
- Minimum hold: none → 24h (288)
- Minimum momentum: 0.5% → 3.0% (stay in cash if nothing qualifies)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.strategies.template import StrategyTemplate

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine

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


class StrategyJH(StrategyTemplate):
    """
    Multi-asset momentum rotation.

    Every `rebalance_every` timer ticks:
      1) Rank assets by lookback momentum (% return).
      2) Hold the top N assets (default 1) that exceed min momentum threshold.
      3) If nothing qualifies, rotate to cash (respecting minimum hold).
      4) Trailing-stop each position after min-hold has elapsed.
    """

    def __init__(
        self,
        main_engine: "MainEngine",
        strategy_name: str = "strategy_JH",
        setting: dict[str, Any] | None = None,
    ) -> None:
        s = dict(setting or {})
        s.setdefault("timer_trigger", 1)  # Run every tick; rebalance_every uses internal counting
        s.setdefault("interval", "5m")
        super().__init__(main_engine, strategy_name, s)

        # Strategy-owned symbol universe (no UI input needed).
        self.symbols = [f"{c}USDT" for c in TRACKED_COINS]

        # ── Order symbol format ──
        # Keep compatible with GatewayEngine conversion (preferred is "gateway": BTCUSDT).
        self.order_symbol_format: str = str(s.get("order_symbol_format", "gateway")).lower()

        # ── Parameters ──
        # 48h lookback on 5m bars = 48*60/5 = 576 candles.
        self.lookback_candles: int = int(s.get("lookback_candles", 576))
        self.top_n: int = int(s.get("top_n", 1))
        # 24h rebalance on tick cadence (1 tick per 5m timer) = 24*60/5 = 288 ticks.
        self.rebalance_every: int = int(s.get("rebalance_every", 288))
        self.trailing_stop_pct: float = float(s.get("trailing_stop_pct", 8.0))
        # 24h min-hold on 5m ticks = 288 ticks.
        self.min_hold_candles: int = int(s.get("min_hold_candles", 288))
        self.min_momentum_pct: float = float(s.get("min_momentum_pct", 3.0))

        # Capital allocation knobs (kept compatible with existing framework defaults)
        self.capital_allocation: float = float(s.get("capital_allocation", 850_000))
        self.max_single_alloc_pct: float = float(s.get("max_single_alloc_pct", 100.0))

        # ── Internal state ──
        self._tick_count: int = 0
        self._positions: dict[str, dict[str, Any]] = {}
        # {coin: {"qty", "entry_price", "peak_price", "entry_tick", "order_symbol", "order_id"}}

    def _format_pair(self, coin: str) -> str:
        """Format Roostoo pair for logging (e.g. 'BTC/USD')."""
        return f"{coin}/USD"

    def _format_order_symbol(self, coin: str) -> str:
        """Format symbol for GatewayEngine.place_order()."""
        if self.order_symbol_format == "slash":
            return self._format_pair(coin)
        return f"{coin}USDT"

    def _log_reconciliation(self) -> None:
        """Log internal positions vs engine holdings and gateway pending orders."""
        strat_pos = {self._format_order_symbol(c): float(p["qty"]) for c, p in self._positions.items()}
        eng_pos: dict[str, float] = {}
        if hasattr(self._main, "strategy_engine") and self._main.strategy_engine:
            holding = self._main.strategy_engine.get_holding(self.strategy_name)
            eng_pos = {s: float(p.quantity) for s, p in holding.positions.items() if float(p.quantity or 0) != 0}
        pending = self.get_pending_orders()
        diff = set(strat_pos.keys()) ^ set(eng_pos.keys())
        if diff:
            self.write_log(
                f"RECONCILE: JH={list(strat_pos)} | Engine={list(eng_pos)} | pending={list(pending)} | mismatch={list(diff)}",
                level="WARN",
            )
        elif strat_pos or pending:
            self.write_log(f"RECONCILE: OK | JH={strat_pos} Engine={eng_pos} pending={pending}", level="DEBUG")

    def on_init_logic(self) -> None:
        self.write_log(
            f"strategy_JH init: lookback={self.lookback_candles} top_n={self.top_n} "
            f"rebalance_every={self.rebalance_every} trail={self.trailing_stop_pct}% "
            f"min_hold={self.min_hold_candles} min_mom={self.min_momentum_pct}% "
            f"alloc=${self.capital_allocation:,.0f} order_symbol={self.order_symbol_format}",
            level="INFO",
        )

    def history_requirements(self) -> list[dict[str, object]]:
        ival = self.interval.binance
        reqs: list[dict[str, object]] = []
        lookback = int(self.lookback_candles)
        for c in TRACKED_COINS:
            reqs.append({"symbol": f"{c}USDT", "interval": ival, "bars": lookback})
        return reqs

    def on_stop_logic(self) -> None:
        self.write_log("strategy_JH stopping — closing all positions", level="INFO")
        self._close_all_positions("strategy_stop")

    def on_timer_logic(self) -> None:
        self._tick_count += 1

        if not self._has_enough_data():
            if self._tick_count % 10 == 0:
                me = getattr(self._main, "market_engine", None)
                any_bars = 0
                if me:
                    any_bars = me.get_bar_count("BTCUSDT", self.interval.binance)
                self.write_log(
                    f"Warming up... {any_bars} bars available (need {self.lookback_candles})",
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
        me = getattr(self._main, "market_engine", None)
        if not me:
            return False
        # Use BTCUSDT as a proxy that the engine is warmed up, but also require
        # per-asset lookback in ranking function (it skips assets lacking bars).
        return me.get_bar_count("BTCUSDT", self.interval.binance) >= self.lookback_candles

    def _get_current_prices(self) -> dict[str, float]:
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

    def _get_momentum_rankings(self) -> list[dict[str, Any]]:
        me = getattr(self._main, "market_engine", None)
        if not me:
            return []
        rankings: list[dict[str, Any]] = []
        for coin in TRACKED_COINS:
            symbol = f"{coin}USDT"
            bars = me.get_last_bars(symbol, self.lookback_candles, self.interval.binance)
            if len(bars) < self.lookback_candles:
                continue
            past = float(bars[0].close)
            current = float(bars[-1].close)
            if past <= 0 or current <= 0:
                continue
            momentum_pct = (current - past) / past * 100.0
            if momentum_pct < self.min_momentum_pct:
                continue
            rankings.append({"coin": coin, "momentum_pct": momentum_pct, "price": current})
        rankings.sort(key=lambda x: x["momentum_pct"], reverse=True)
        return rankings

    def _check_trailing_stops(self, current_prices: dict[str, float]) -> None:
        to_close: list[str] = []
        for coin, pos in self._positions.items():
            price = current_prices.get(coin)
            if not price:
                continue

            if price > float(pos["peak_price"]):
                pos["peak_price"] = price

            ticks_held = self._tick_count - int(pos["entry_tick"])
            if ticks_held < self.min_hold_candles:
                continue

            peak = float(pos["peak_price"])
            dd = (peak - price) / peak * 100.0 if peak > 0 else 0.0
            if dd >= self.trailing_stop_pct:
                self.write_log(
                    f"TRAILING STOP {coin}: peak={peak:.6f} now={price:.6f} dd={dd:.2f}%",
                    level="WARN",
                )
                to_close.append(coin)

        for coin in to_close:
            self._close_position(coin, "trailing_stop")

    def _rebalance(self, current_prices: dict[str, float]) -> None:
        rankings = self._get_momentum_rankings()

        if not rankings:
            self.write_log(
                f"REBALANCE: No assets meet min momentum {self.min_momentum_pct:.2f}% — staying in cash",
                level="WARN",
            )
            # Rotate to cash if possible (respect min hold)
            for coin in list(self._positions.keys()):
                ticks_held = self._tick_count - int(self._positions[coin]["entry_tick"])
                if ticks_held >= self.min_hold_candles:
                    self._close_position(coin, "no_qualifiers")
            return

        self.write_log(
            "REBALANCE: top movers: " + ", ".join(f"{r['coin']}({r['momentum_pct']:+.2f}%)" for r in rankings[:5]),
            level="INFO",
        )

        target_coins = [r["coin"] for r in rankings[: self.top_n]]

        for coin in list(self._positions.keys()):
            if coin not in target_coins:
                ticks_held = self._tick_count - int(self._positions[coin]["entry_tick"])
                if ticks_held >= self.min_hold_candles:
                    self.write_log(f"ROTATION EXIT: {coin} no longer in top {self.top_n}", level="INFO")
                    self._close_position(coin, "rotation")

        for rank_info in rankings[: self.top_n]:
            coin = str(rank_info["coin"])
            if coin in self._positions:
                continue
            slots_open = self.top_n - len(self._positions)
            if slots_open <= 0:
                break
            self._open_position(
                coin=coin,
                price=float(rank_info["price"]),
                momentum=float(rank_info["momentum_pct"]),
                slots_open=slots_open,
            )

    def _open_position(self, coin: str, price: float, momentum: float, slots_open: int) -> None:
        max_per = self.capital_allocation * (self.max_single_alloc_pct / 100.0)
        alloc = min(self.capital_allocation / max(self.top_n, 1), max_per)

        qty = alloc / price if price > 0 else 0.0
        qty = round(qty, 5)
        if qty <= 0 or alloc < 10:
            self.write_log(
                f"BUY {coin} skipped: qty={qty:.5f} alloc=${alloc:,.0f} (min $10)",
                level="WARN",
            )
            return

        # LIMIT slightly above current price to improve fills
        limit_price = round(price * 1.001, 8)
        order_symbol = self._format_order_symbol(coin)

        self.write_log(
            f"BUY {coin}: qty={qty:.5f} limit={limit_price:.6f} alloc=${alloc:,.0f} momentum={momentum:+.2f}%",
            level="INFO",
        )

        order_id = self.open_position(
            symbol=order_symbol,
            quantity=qty,
            price=limit_price,
            order_type="LIMIT",
        )

        self._positions[coin] = {
            "qty": qty,
            "entry_price": price,
            "peak_price": price,
            "entry_tick": self._tick_count,
            "order_symbol": order_symbol,
            "order_id": order_id,
        }

    def _close_position(self, coin: str, reason: str) -> None:
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
            f"SELL {coin}: qty={float(pos['qty']):.5f} reason={reason} "
            f"entry={float(pos['entry_price']):.6f} now={current_price:.6f}",
            level="INFO",
        )

        self.close_position(
            symbol=str(pos["order_symbol"]),
            quantity=float(pos["qty"]),
            order_type="MARKET",
        )

        del self._positions[coin]

    def _close_all_positions(self, reason: str) -> None:
        for coin in list(self._positions.keys()):
            self._close_position(coin, reason)

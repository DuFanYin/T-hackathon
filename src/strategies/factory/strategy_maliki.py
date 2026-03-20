"""
strategy_maliki: Multi-Asset Momentum Rotation (v2) — tuned (48h / top1 / daily rebalance)

Plugs into the team's event-driven framework via StrategyTemplate.
Signal source: MarketEngine (bars from GatewayEngine Binance 5m injection).
Execution: via framework's send_order() -> GatewayEngine -> Roostoo API.

Tuned parameters (per request):
  lookback=576 (48h on 5m bars), top_n=1, rebalance_every=288 (24h),
  trailing_stop=8%, min_hold=288 (24h), min_momentum=3.0%

Default sizing fallback: capital_allocation=$20k when cached USD balance is unavailable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.strategies.template import StrategyTemplate

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine

log = logging.getLogger("strategy_maliki")

# Assets to track in MarketEngine symbol format (internal symbols like BTCUSDT).
#
# Using internal symbols makes this strategy compatible with the system's
# MarketEngine/Gateway symbol conventions without extra conversions.
TRACKED_COINS = [
    # Large cap
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT",
    "AVAXUSDT", "LTCUSDT", "TONUSDT", "XLMUSDT", "HBARUSDT", "SUIUSDT",
    # Mid cap
    "UNIUSDT", "AAVEUSDT", "FILUSDT", "ICPUSDT", "NEARUSDT", "APTUSDT", "FETUSDT", "SEIUSDT", "TAOUSDT",
    "PENDLEUSDT", "ENAUSDT", "ONDOUSDT", "ARBUSDT", "CRVUSDT", "WLDUSDT", "EIGENUSDT", "CAKEUSDT", "TRXUSDT", "CFXUSDT",
    # Meme
    "PEPEUSDT", "SHIBUSDT", "BONKUSDT", "FLOKIUSDT", "WIFUSDT", "TRUMPUSDT", "PENGUUSDT",
]


class StrategyMaliki(StrategyTemplate):
    """
    Multi-asset momentum rotation with BTC regime filter.

    Every `rebalance_every` strategy timer steps (each step = timer_trigger EventEngine ticks, default 300 ≈ 5m at 1s/tick):
      1. Check regime: is BTC above its 48h moving average? If not, close all and go cash.
      2. Rank all assets by 48h momentum (% return over last 576 5m-candles).
      3. Hold the top 1 mover. Exit if a different coin takes #1 (if min hold met).
      4. Trail every position with an 8% trailing stop (after 24h min hold).
    """

    def __init__(
        self,
        main_engine: "MainEngine",
        strategy_name: str = "strategy_maliki",
        setting: dict[str, Any] | None = None,
    ) -> None:
        s = dict(setting or {})
        # Align strategy steps with 5m bar cadence: EventEngine default interval=1s → 300 ticks ≈ 5 minutes.
        s.setdefault("timer_trigger", 300)
        s.setdefault("interval", "5m")  # This strategy uses 5m bars
        super().__init__(main_engine, strategy_name, s)

        # Strategy-owned symbol universe (internal MarketEngine symbols, e.g. BTCUSDT).
        self.symbols = list(TRACKED_COINS)

        # ── Strategy parameters ──
        # 48h lookback on 5m bars = 48*60/5 = 576 candles.
        self.lookback_candles: int = int(s.get("lookback_candles", 576))
        # Concentrate into top-1.
        self.top_n: int = int(s.get("top_n", 1))
        # 24h between rebalances: 288 strategy steps × 5m/step (with timer_trigger=300 @ 1s EventEngine).
        self.rebalance_every: int = int(s.get("rebalance_every", 288))
        # Wider trail to reduce churn.
        self.trailing_stop_pct: float = float(s.get("trailing_stop_pct", 8.0))
        # Minimum hold 24h in strategy steps (288 × 5m with default timer_trigger).
        self.min_hold_candles: int = int(s.get("min_hold_candles", 288))
        # BTC regime MA: 48h on 5m bars = 576.
        self.regime_ma_candles: int = int(s.get("regime_ma_candles", 576))
        # Require strong trend; if none qualify, stay in cash.
        self.min_momentum_pct: float = float(s.get("min_momentum_pct", 3.0))
        # Liquidity filter: approximate 24h notional (sum(volume*close) over last 288 bars).
        self.min_notional_24h: float = float(s.get("min_notional_24h", 1_000_000))
        self.capital_allocation: float = float(s.get("capital_allocation", 20_000))
        # top_n=1 by default; allow full allocation.
        self.max_single_alloc_pct: float = float(s.get("max_single_alloc_pct", 100.0))

        # ── Internal state ──
        self._tick_count: int = 0
        # Internal risk metadata only (NOT holdings source-of-truth).
        self._risk_state: dict[str, dict[str, float | int]] = {}
        # {coin: {"peak_price": float, "entry_tick": int, "entry_price": float}}

        n_track = len(self.symbols)
        self.write_log(
            f"[strategy_maliki] CONSTRUCT | tracked_symbols={n_track} interval={self.interval.binance} "
            f"timer_trigger={self._timer_trigger} lookback={self.lookback_candles} top_n={self.top_n} "
            f"rebalance_every={self.rebalance_every} trail={self.trailing_stop_pct}% "
            f"min_hold={self.min_hold_candles} regime_ma={self.regime_ma_candles} "
            f"min_momentum={self.min_momentum_pct}% min_notional_24h=${self.min_notional_24h:,.0f} "
            f"alloc=${self.capital_allocation:,.0f} max_single%={self.max_single_alloc_pct}",
            level="INFO",
        )

    def _format_pair(self, coin: str) -> str:
        """Format Roostoo pair for logging (e.g. 'BTC/USD')."""
        return f"{coin}/USD"

    @staticmethod
    def _symbol_to_coin(symbol: str) -> str:
        """
        Convert a symbol key coming from StrategyEngine holdings/pending orders into a coin base name.

        - Internal symbol style: "BTCUSDT" -> "BTC"
        """
        s = str(symbol or "").strip().upper()
        if not s:
            return s
        if s.endswith("USDT"):
            return s[:-4]
        return s

    def _engine_positions(self) -> dict[str, float]:
        se = getattr(self._main, "strategy_engine", None)
        if not se:
            return {}
        holding = se.get_holding(self.strategy_name)
        out: dict[str, float] = {}
        for sym, pos in getattr(holding, "positions", {}).items():
            qty = float(getattr(pos, "quantity", 0.0) or 0.0)
            if qty > 0:
                out[self._symbol_to_coin(sym)] = qty
        return out

    def _log_reconciliation(self) -> None:
        """Log internal risk-state symbols vs engine-held symbols and pending orders."""
        risk_syms = sorted(self._risk_state.keys())
        eng_syms = sorted(self._engine_positions().keys())
        pending = self.get_pending_orders()  # engine cached pending by symbol
        diff = set(risk_syms) ^ set(eng_syms)
        if diff:
            self.write_log(
                f"RECONCILE: risk={risk_syms} | engine={eng_syms} | pending={list(pending)} | "
                f"mismatch={list(diff)} — check fill/order status",
                level="WARN",
            )
        elif eng_syms or pending:
            self.write_log(f"RECONCILE: OK | risk={risk_syms} engine={eng_syms} pending={pending}", level="DEBUG")

    # ──────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────

    def on_init_logic(self) -> None:
        reqs = self.history_requirements()
        ival = self.interval.binance
        me = getattr(self._main, "market_engine", None)
        btc_n = me.get_bar_count("BTCUSDT", ival) if me else 0
        sample_momo = 0
        if me and self.symbols:
            sample_momo = me.get_bar_count(self.symbols[0], ival)
        self.write_log(
            f"[strategy_maliki] INIT | history_requests={len(reqs)} | "
            f"BTCUSDT bars={btc_n} (regime needs {self.regime_ma_candles}) | "
            f"sample {self.symbols[0] if self.symbols else '?'} bars={sample_momo} (momentum needs {self.lookback_candles}) | "
            f"top_n={self.top_n} rebal_every={self.rebalance_every} ticks",
            level="INFO",
        )

    def history_requirements(self) -> list[dict[str, object]]:
        # Backfill enough candles so init/start don't wait for slow warmup.
        ival = self.interval.binance
        reqs: list[dict[str, object]] = []
        # Regime filter uses BTC MA.
        reqs.append({"symbol": "BTCUSDT", "interval": ival, "bars": int(self.regime_ma_candles)})
        # Momentum calculations need lookback window for each tracked coin.
        lookback = int(self.lookback_candles)
        for c in TRACKED_COINS:
            # TRACKED_COINS already uses internal MarketEngine symbols like BTCUSDT.
            reqs.append({"symbol": c, "interval": ival, "bars": lookback})
        return reqs

    def on_start_logic(self) -> None:
        self.write_log(
            f"[strategy_maliki] START | timer every {self._timer_trigger} tick(s) "
            f"→ rebalance check each {self.rebalance_every} strategy steps | "
            f"interval={self.interval.binance} universe={len(self.symbols)} symbols",
            level="INFO",
        )

    def on_stop_logic(self) -> None:
        self.write_log("[strategy_maliki] STOP | closing all positions", level="INFO")
        self.clear_all_positions()

    # ──────────────────────────────────────────
    # Main timer logic (each call ≈ every 5m with default timer_trigger=300 and EventEngine interval=1s)
    # ──────────────────────────────────────────

    def on_timer_logic(self) -> None:
        self._tick_count += 1
        me = getattr(self._main, "market_engine", None)
        btc_bars = me.get_bar_count("BTCUSDT", self.interval.binance) if me else 0
        warmup_ok = self._has_enough_data()
        rebal_this = self._tick_count % self.rebalance_every == 0
        self.write_log(
            f"[strategy_maliki] TIMER | tick={self._tick_count} | btc_bars={btc_bars}/"
            f"{self.regime_ma_candles} warmup_ok={warmup_ok} | rebalance_this_step={rebal_this} "
            f"(every {self.rebalance_every} ticks)",
            level="INFO",
        )

        if not warmup_ok:
            if self._tick_count % 10 == 0:
                self.write_log(
                    f"[strategy_maliki] Warming up... {btc_bars} BTC bars (need {self.regime_ma_candles})",
                    level="DEBUG",
                )
            return

        current_prices = self._get_current_prices()
        if not current_prices:
            self.write_log("[strategy_maliki] TIMER | skip: no current_prices from MarketEngine", level="WARN")
            return

        self.write_log(
            f"[strategy_maliki] prices | n={len(current_prices)} held={list(self._engine_positions().keys())}",
            level="INFO",
        )

        self._check_trailing_stops(current_prices)

        if rebal_this:
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
        for asset_symbol in TRACKED_COINS:
            coin = self._symbol_to_coin(asset_symbol)
            sd = me.get_symbol(asset_symbol)
            if sd and getattr(sd, "last_price", 0.0) > 0:
                prices[coin] = float(sd.last_price)
        return prices

    # ──────────────────────────────────────────
    # Regime filter
    # ──────────────────────────────────────────

    def _regime_snapshot(self) -> tuple[bool, float, float] | None:
        """
        (bullish, btc_last, btc_ma) or None if insufficient bars / no market.
        bullish ⇔ btc_last > btc_ma.
        """
        me = getattr(self._main, "market_engine", None)
        if not me:
            return None
        bars = me.get_last_bars("BTCUSDT", self.regime_ma_candles, self.interval.binance)
        if len(bars) < self.regime_ma_candles:
            return None
        btc_price = float(bars[-1].close)
        btc_ma = sum(float(b.close) for b in bars[-self.regime_ma_candles :]) / self.regime_ma_candles
        return (btc_price > btc_ma, btc_price, btc_ma)

    def _is_regime_bullish(self) -> bool:
        """True if BTC is above its N-period moving average (from MarketEngine bars)."""
        snap = self._regime_snapshot()
        return bool(snap and snap[0])

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
        vol_window = 288  # 24h on 5m bars
        for asset_symbol in TRACKED_COINS:
            coin = self._symbol_to_coin(asset_symbol)
            bars = me.get_last_bars(asset_symbol, self.lookback_candles, self.interval.binance)
            if len(bars) < self.lookback_candles:
                continue
            notional_24h = me.get_notional_sum(asset_symbol, vol_window, self.interval.binance)
            if notional_24h < self.min_notional_24h:
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
                # System internal symbol (e.g. BTCUSDT) for GatewayEngine.
                "roostoo_symbol": f"{coin}USDT",
                "notional_24h": notional_24h,
            })
        rankings.sort(key=lambda x: x["momentum_pct"], reverse=True)
        return rankings

    # ──────────────────────────────────────────
    # Trailing stops
    # ──────────────────────────────────────────

    def _check_trailing_stops(self, current_prices: dict) -> None:
        """Check and execute trailing stops (respecting min hold)."""
        to_close = []

        held = self._engine_positions()
        for coin, qty in held.items():
            price = current_prices.get(coin)
            if not price:
                self.write_log(
                    f"[strategy_maliki] TRAIL | {coin} | skip: no price in current_prices qty_held={qty}",
                    level="INFO",
                )
                continue
            st = self._risk_state.setdefault(
                coin,
                {"peak_price": price, "entry_tick": self._tick_count, "entry_price": price},
            )

            # Update peak
            if price > float(st["peak_price"]):
                st["peak_price"] = price

            # Respect minimum hold period
            ticks_held = self._tick_count - int(st["entry_tick"])
            peak = float(st["peak_price"])
            dd = (peak - price) / peak * 100 if peak > 0 else 0.0
            self.write_log(
                f"[strategy_maliki] TRAIL | {coin} | price={price:.6f} peak={peak:.6f} "
                f"dd={dd:.2f}% (th={self.trailing_stop_pct}%) ticks_held={ticks_held}/"
                f"{self.min_hold_candles} qty={qty}",
                level="INFO",
            )
            if ticks_held < self.min_hold_candles:
                continue

            # Check trailing stop
            if dd >= self.trailing_stop_pct:
                self.write_log(
                    f"[strategy_maliki] TRAIL | {coin} | TRIGGER peak={peak:.4f} now={price:.4f} dd={dd:.1f}%",
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
        snap = self._regime_snapshot()
        regime = bool(snap and snap[0])
        held = self._engine_positions()
        if snap:
            bull, btc_p, btc_ma = snap
            self.write_log(
                f"[strategy_maliki] REBALANCE | regime={'BULL' if bull else 'BEAR'} | "
                f"BTC_last={btc_p:.4f} MA({self.regime_ma_candles})={btc_ma:.4f} "
                f"spread={btc_p - btc_ma:+.4f} (bull needs last>MA) | held={list(held.keys())}",
                level="INFO",
            )
        else:
            self.write_log(
                "[strategy_maliki] REBALANCE | regime=UNKNOWN (insufficient BTC bars for MA)",
                level="WARN",
            )

        # If bearish regime, close positions that have met min hold
        if not regime:
            n = len(held)
            self.write_log(
                f"[strategy_maliki] REBALANCE | BEAR path — close if min_hold met | n_held={n}",
                level="WARN",
            )
            for coin in list(held.keys()):
                st = self._risk_state.get(coin)
                ticks_held = self._tick_count - int(st["entry_tick"]) if st else self.min_hold_candles
                self.write_log(
                    f"[strategy_maliki] REBALANCE | BEAR | {coin} ticks_held={ticks_held} "
                    f"need>={self.min_hold_candles} → "
                    f"{'CLOSE regime_bearish' if ticks_held >= self.min_hold_candles else 'keep'}",
                    level="INFO",
                )
                if ticks_held >= self.min_hold_candles:
                    self._close_position(coin, "regime_bearish")
            return

        # Bullish regime — rank and rotate
        rankings = self._get_momentum_rankings()
        self.write_log(
            f"[strategy_maliki] REBALANCE | BULL | rankings_count={len(rankings)} "
            f"min_mom={self.min_momentum_pct}% min_notional_24h={self.min_notional_24h}",
            level="INFO",
        )

        if rankings:
            self.write_log(
                f"[strategy_maliki] REBALANCE | top movers: "
                + ", ".join(
                    f"{r['coin']}({r['momentum_pct']:+.1f}% n24h={r.get('notional_24h', 0):.0f})"
                    for r in rankings[:8]
                ),
                level="INFO",
            )
        else:
            self.write_log(
                f"[strategy_maliki] REBALANCE | no candidates (momentum/notional/lookback) "
                f"min_momentum={self.min_momentum_pct:.2f}% — cash mode",
                level="WARN",
            )
            # If nothing qualifies, rotate to cash (respect min hold).
            for coin in list(held.keys()):
                st = self._risk_state.get(coin)
                ticks_held = self._tick_count - int(st["entry_tick"]) if st else self.min_hold_candles
                if ticks_held >= self.min_hold_candles:
                    self._close_position(coin, "no_qualifiers")
            return

        target_coins = [r["coin"] for r in rankings[:self.top_n]]
        self.write_log(
            f"[strategy_maliki] REBALANCE | target_coins(top_{self.top_n})={target_coins}",
            level="INFO",
        )

        # Exit positions not in target (if min hold met)
        for coin in list(held.keys()):
            if coin not in target_coins:
                st = self._risk_state.get(coin)
                ticks_held = self._tick_count - int(st["entry_tick"]) if st else self.min_hold_candles
                self.write_log(
                    f"[strategy_maliki] REBALANCE | rotation check | {coin} not in {target_coins} "
                    f"ticks_held={ticks_held}",
                    level="INFO",
                )
                if ticks_held >= self.min_hold_candles:
                    self.write_log(
                        f"[strategy_maliki] ROTATION EXIT | {coin} dropped from top {self.top_n}",
                        level="INFO",
                    )
                    self._close_position(coin, "rotation")

        # Enter new targets
        pending_by_symbol = self.get_pending_orders()
        for rank_info in rankings[:self.top_n]:
            coin = rank_info["coin"]
            sym = f"{coin}USDT"
            if coin in held or pending_by_symbol.get(sym):
                self.write_log(
                    f"[strategy_maliki] ENTRY skip | {coin} already_held={coin in held} "
                    f"pending_on_{sym}={bool(pending_by_symbol.get(sym))}",
                    level="INFO",
                )
                continue  # already holding

            slots_open = self.top_n - len(held)
            if slots_open <= 0:
                self.write_log(
                    f"[strategy_maliki] ENTRY skip | slots_open={slots_open} held={list(held.keys())}",
                    level="INFO",
                )
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
        # Size: prefer cached USD balance (no exchange call), fallback to configured capital_allocation.
        usd_balance = 0.0
        gw = getattr(self._main, "gateway_engine", None)
        if gw and hasattr(gw, "get_balance"):
            bal = gw.get_balance() or {}
            wallet = bal.get("Wallet") if isinstance(bal, dict) else None
            if isinstance(wallet, dict):
                usd = wallet.get("USD")
                if isinstance(usd, dict):
                    usd_balance = float((usd.get("Free") or 0.0)) + float((usd.get("Lock") or 0.0))

        portfolio_value = usd_balance if usd_balance > 0 else float(self.capital_allocation)
        max_per = portfolio_value * (self.max_single_alloc_pct / 100)
        alloc = min(portfolio_value / max(self.top_n, 1), max_per)

        qty = alloc / price
        # Rounding is handled centrally by the gateway safety net
        # (engine_gateway.place_order rounds to TradingPair.amount_precision).

        self.write_log(
            f"[strategy_maliki] ENTRY sizing | {coin} | usd_wallet={usd_balance:.2f} "
            f"fallback_capital={self.capital_allocation} → portfolio_value={portfolio_value:.2f} "
            f"max_single%={self.max_single_alloc_pct} alloc=${alloc:,.2f} price={price:.6f} qty={qty:.8f}",
            level="INFO",
        )

        if qty <= 0 or alloc < 10:
            self.write_log(
                f"[strategy_maliki] BUY {coin} skipped: qty={qty:.8f} alloc=${alloc:,.0f} (min $10)",
                level="WARN",
            )
            return

        # Use LIMIT order for lower commission
        # Set limit slightly above current price to ensure fill.
        # Gateway rounds to TradingPair.price_precision before sending.
        limit_price = price * 1.001

        self.write_log(
            f"[strategy_maliki] BUY {coin} | qty={qty:.5f} limit={limit_price:.6f} ref={price:.6f} "
            f"momentum={momentum:+.2f}%",
            level="INFO",
        )

        # System internal symbol format: e.g. BTCUSDT.
        roostoo_symbol = f"{coin}USDT"
        order_id = self.open_position(
            symbol=roostoo_symbol,
            quantity=qty,
            price=limit_price,
            order_type="LIMIT",
        )

        if order_id:
            # Start risk metadata at submit time; holdings still come from engine fill events.
            self._risk_state.setdefault(
                coin,
                {"peak_price": price, "entry_tick": self._tick_count, "entry_price": price},
            )

    def _close_position(self, coin: str, reason: str) -> None:
        """Sell via framework's send_order."""
        held = self._engine_positions()
        qty = float(held.get(coin, 0.0) or 0.0)
        if qty <= 0:
            return

        current_price = 0.0
        me = getattr(self._main, "market_engine", None)
        if me:
            sd = me.get_symbol(f"{coin}USDT")
            if sd and getattr(sd, "last_price", 0.0) > 0:
                current_price = float(sd.last_price)

        st = self._risk_state.get(coin, {})
        entry_price = float(st.get("entry_price", 0.0) or 0.0)
        self.write_log(
            f"SELL {coin}: qty={qty:.5f} reason={reason} "
            f"entry={entry_price:.4f} now={current_price:.4f}",
            level="INFO",
        )

        self.close_position(
            symbol=f"{coin}USDT",
            quantity=qty,
            order_type="MARKET",
        )
        self._risk_state.pop(coin, None)

    def _close_all_positions(self, reason: str) -> None:
        """Close all positions."""
        for coin in list(self._engine_positions().keys()):
            self._close_position(coin, reason)

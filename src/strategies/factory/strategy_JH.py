"""
strategy_JH.

Note: This file defines the strategy class `StrategyJH` whose default `strategy_name`
matches the filename (`strategy_JH`), so it can be registered/started by name consistently.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.strategies.template import StrategyTemplate
from src.utilities.intents import INTENT_CANCEL_ORDER
from src.utilities.object import CancelOrderRequest

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


def _round_digits(value: float, digits: int) -> float:
    if digits < 0:
        return value
    factor = 10.0**digits
    return round(value * factor) / factor


def _state_default() -> dict[str, Any]:
    return {
        "sup_price": None,
        "hit_count": 0,
        "hit1_low": None,
        "limit_bar_idx": 0,  # bar index when limit order was placed (for timeout)
        "active_stop": None,
        "active_target": None,
    }


class StrategyJH(StrategyTemplate):
    """
    Port of pine/strategy.pine: support bounce H1/H2, strict bearish, R:R exit.
    Monitors all trading pairs by default. Bars and indicators from market_engine.
    """

    def __init__(
        self,
        main_engine: "MainEngine",
        strategy_name: str = "strategy_JH",
        setting: dict[str, Any] | None = None,
    ) -> None:
        s = dict(setting or {})
        # Solely rely on market engine cached symbols (no resolution from config or main_engine)
        market = getattr(main_engine, "market_engine", None) if main_engine else None
        symbols = market.get_cached_symbols() if market and hasattr(market, "get_cached_symbols") else []
        s["symbols"] = symbols
        super().__init__(main_engine, strategy_name, s)
        if not self.symbols:
            self.write_log(
                "Symbol selection: no cached symbols in market engine",
                level="ERROR",
            )

        self.pivot_len = int(s.get("pivot_len", 3))
        self.rr = float(s.get("rr", 2.0))
        self.use_limit = bool(s.get("use_limit", True))
        self.fill_bars = int(s.get("fill_bars", 2))
        self.atr_len = int(s.get("atr_len", 14))
        self.mintick = float(s.get("mintick", 0.01))
        self.quantity = float(s.get("quantity", 1.0))

        # Per-symbol state
        self._state: dict[str, dict[str, Any]] = {}

    def _get_state(self, symbol: str) -> dict[str, Any]:
        if symbol not in self._state:
            self._state[symbol] = _state_default()
        return self._state[symbol]

    def on_init_logic(self) -> None:
        self.write_log(
            f"strategy_JH symbols={len(self.symbols)} pivot_len={self.pivot_len} rr={self.rr} use_limit={self.use_limit}",
            level="INFO",
        )

    def on_timer_logic(self) -> None:
        market = getattr(self._main, "market_engine", None)
        if not market:
            self.write_log("strategy_JH no market_engine", level="WARN")
            return

        ival = getattr(self.interval, "binance", "5m") if hasattr(self, "interval") else "5m"

        for symbol in self.symbols:
            self._tick_symbol(market, symbol, ival)

    def _tick_symbol(self, market: Any, symbol: str, interval: str) -> None:
        last_bars = market.get_last_bars(symbol, 4, interval)
        if len(last_bars) < 4:
            bar_count = market.get_bar_count(symbol, interval)
            if bar_count > 0 and bar_count % 100 == 1:
                self.write_log(f"strategy_JH {symbol} waiting for bars: have {len(last_bars)}/4", level="DEBUG")
            return

        st = self._get_state(symbol)
        pending_map = self.get_pending_orders()
        pending_ids = pending_map.get(symbol, [])

        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(symbol)
        position_size = pos.quantity if pos else 0.0
        flat = position_size == 0.0

        if not flat and st["active_stop"] is not None and st["active_target"] is not None:
            sym_data = self.get_symbol(symbol)
            last = getattr(sym_data, "last_price", None) if sym_data else None
            if last is not None:
                if last <= st["active_stop"]:
                    self.send_order(symbol, "SELL", abs(position_size), last, "MARKET")
                    self.write_log(f"strategy_JH {symbol} exit stop hit {last} <= {st['active_stop']}", level="WARN")
                    st["active_stop"] = None
                    st["active_target"] = None
                elif last >= st["active_target"]:
                    self.send_order(symbol, "SELL", abs(position_size), last, "MARKET")
                    self.write_log(f"strategy_JH {symbol} exit target hit {last} >= {st['active_target']}", level="INFO")
                    st["active_stop"] = None
                    st["active_target"] = None

        bar_count = market.get_bar_count(symbol, interval)
        if self.use_limit and flat and pending_ids and bar_count - st["limit_bar_idx"] >= self.fill_bars + 1:
            oid = pending_ids[0]
            self._main.handle_intent(INTENT_CANCEL_ORDER, CancelOrderRequest(order_id=oid, symbol=symbol))
            self.write_log(f"strategy_JH {symbol} limit timeout, cancel {oid}", level="WARN")

        last_bar = last_bars[-1]
        prev_bar = last_bars[-2]
        o = last_bar.open
        h = last_bar.high
        l = last_bar.low
        c = last_bar.close
        prev_open = prev_bar.open
        rng = h - l
        close_top_third = rng > 0 and c >= (l + rng * (2.0 / 3.0))
        close_above_support = st["sup_price"] is not None and c > st["sup_price"]
        close_not_above_prev_open = c <= prev_open
        entry_price = (h + l) / 2.0
        stop_price = l - self.mintick
        risk = entry_price - stop_price
        atr = market.get_atr(symbol, self.atr_len, interval)
        risk_too_big = atr > 0 and risk >= atr

        pl = market.get_pivot_low(symbol, self.pivot_len, self.pivot_len, interval)
        if pl is not None:
            st["sup_price"] = pl
            st["hit_count"] = 0
            st["hit1_low"] = None
            self.write_log(f"strategy_JH {symbol} pivot low={pl:.2f} support updated", level="DEBUG")

        hit_support = st["sup_price"] is not None and l <= st["sup_price"]
        if hit_support:
            st["hit_count"] += 1
            if st["hit_count"] == 1:
                st["hit1_low"] = l

        ok_bear = market.prev3_bearish_strict(symbol, interval)
        ok_t3 = close_top_third
        ok_cs = close_above_support
        ok_po = close_not_above_prev_open
        ok_atr = not risk_too_big
        higher_low_fail = st["hit_count"] == 2 and st["hit1_low"] is not None and l > st["hit1_low"]

        signal = False
        if st["hit_count"] == 1 and ok_bear and ok_t3 and ok_cs and ok_po and ok_atr:
            signal = True
        elif st["hit_count"] == 2 and not signal and ok_bear and ok_t3 and ok_cs and ok_po and ok_atr and not higher_low_fail:
            signal = True
        elif st["hit_count"] == 2 and not signal:
            self.write_log(f"strategy_JH {symbol} H2 higher-low fail, reset support", level="DEBUG")
            st["sup_price"] = None
            st["hit_count"] = 0
            st["hit1_low"] = None

        if signal and flat:
            target_price = _round_digits(entry_price + self.rr * risk, 2)
            if pending_ids:
                for oid in pending_ids:
                    self._main.handle_intent(INTENT_CANCEL_ORDER, CancelOrderRequest(order_id=oid, symbol=symbol))
            if self.use_limit:
                self.send_order(symbol, "BUY", self.quantity, entry_price, "LIMIT")
                st["limit_bar_idx"] = bar_count
                self.write_log(f"strategy_JH {symbol} limit BUY @ {entry_price:.2f} qty={self.quantity}", level="INFO")
            else:
                self.send_order(symbol, "BUY", self.quantity, entry_price, "MARKET")
                self.write_log(f"strategy_JH {symbol} market BUY qty={self.quantity}", level="INFO")
            st["active_stop"] = stop_price
            st["active_target"] = target_price
            self.write_log(
                f"strategy_JH {symbol} signal entry={entry_price} stop={stop_price} target={target_price} rr={self.rr}",
                level="INFO",
            )
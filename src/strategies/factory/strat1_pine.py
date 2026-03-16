"""
Python implementation of pine/strategy.pine (Strat1: support bounce, H1/H2, strict bearish + R:R).
Indicator calculations (bars, ATR, pivot low, prev3 bearish) live in MarketEngine; strategy uses
get_last_bars(), get_atr(), get_pivot_low(), prev3_bearish_strict() and keeps only signal/order state.
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


class Strat1Pine(StrategyTemplate):
    """
    Port of pine/strategy.pine: support bounce H1/H2, strict bearish, R:R exit.
    Bars and indicators from market_engine (add_bar called by gateway/data feed). Strategy keeps
    support state, hit count, limit timeout, and stop/target.
    """

    def __init__(
        self,
        main_engine: "MainEngine",
        strategy_name: str = "Strat1Pine",
        setting: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(main_engine, strategy_name, setting or {})
        s = setting or {}
        self.symbol = str(s.get("symbol", "BTCUSDT"))
        self.pivot_len = int(s.get("pivot_len", 3))
        self.rr = float(s.get("rr", 2.0))
        self.use_limit = bool(s.get("use_limit", True))
        self.fill_bars = int(s.get("fill_bars", 2))
        self.atr_len = int(s.get("atr_len", 14))
        self.mintick = float(s.get("mintick", 0.01))
        self.quantity = float(s.get("quantity", 1.0))

        self._sup_price: float | None = None
        self._hit_count: int = 0
        self._hit1_low: float | None = None
        self._limit_pending: bool = False
        self._limit_bar_idx: int = 0
        self._pending_order_id: str | None = None
        self._active_stop: float | None = None
        self._active_target: float | None = None

    def on_init_logic(self) -> None:
        self.write_log(f"Strat1Pine symbol={self.symbol} pivot_len={self.pivot_len} rr={self.rr} use_limit={self.use_limit}")

    def on_timer_logic(self) -> None:
        market = getattr(self._main, "market_engine", None)
        if not market:
            return
        last_bars = market.get_last_bars(self.symbol, 4)
        if len(last_bars) < 4:
            return

        holding = self._main.position_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(self.symbol)
        position_size = pos.quantity if pos else 0.0
        flat = position_size == 0.0

        if not flat:
            self._limit_pending = False
            self._pending_order_id = None

        if not flat and self._active_stop is not None and self._active_target is not None:
            sym = self.get_symbol(self.symbol)
            last = getattr(sym, "last_price", None) if sym else None
            if last is not None:
                if last <= self._active_stop:
                    self.send_order(self.symbol, "SELL", abs(position_size), last, "MARKET")
                    self.write_log(f"Strat1 exit stop hit {last} <= {self._active_stop}")
                    self._active_stop = None
                    self._active_target = None
                elif last >= self._active_target:
                    self.send_order(self.symbol, "SELL", abs(position_size), last, "MARKET")
                    self.write_log(f"Strat1 exit target hit {last} >= {self._active_target}")
                    self._active_stop = None
                    self._active_target = None

        bar_count = market.get_bar_count(self.symbol)
        if self.use_limit and self._limit_pending and flat and self._pending_order_id is not None:
            if bar_count - self._limit_bar_idx >= self.fill_bars + 1:
                self._main.handle_intent(INTENT_CANCEL_ORDER, CancelOrderRequest(order_id=self._pending_order_id, symbol=self.symbol))
                self.write_log(f"Strat1 limit timeout, cancel {self._pending_order_id}")
                self._limit_pending = False
                self._pending_order_id = None

        last_bar = last_bars[-1]
        prev_bar = last_bars[-2]
        o = last_bar.open
        h = last_bar.high
        l = last_bar.low
        c = last_bar.close
        prev_open = prev_bar.open
        rng = h - l
        close_top_third = rng > 0 and c >= (l + rng * (2.0 / 3.0))
        close_above_support = self._sup_price is not None and c > self._sup_price
        close_not_above_prev_open = c <= prev_open
        entry_price = (h + l) / 2.0
        stop_price = l - self.mintick
        risk = entry_price - stop_price
        atr = market.get_atr(self.symbol, self.atr_len)
        risk_too_big = atr > 0 and risk >= atr

        pl = market.get_pivot_low(self.symbol, self.pivot_len, self.pivot_len)
        if pl is not None:
            self._sup_price = pl
            self._hit_count = 0
            self._hit1_low = None

        hit_support = self._sup_price is not None and l <= self._sup_price
        if hit_support:
            self._hit_count += 1
            if self._hit_count == 1:
                self._hit1_low = l

        ok_bear = market.prev3_bearish_strict(self.symbol)
        ok_t3 = close_top_third
        ok_cs = close_above_support
        ok_po = close_not_above_prev_open
        ok_atr = not risk_too_big
        higher_low_fail = self._hit_count == 2 and self._hit1_low is not None and l > self._hit1_low

        signal = False
        if self._hit_count == 1 and ok_bear and ok_t3 and ok_cs and ok_po and ok_atr:
            signal = True
        elif self._hit_count == 2 and not signal and ok_bear and ok_t3 and ok_cs and ok_po and ok_atr and not higher_low_fail:
            signal = True
        elif self._hit_count == 2 and not signal:
            self._sup_price = None
            self._hit_count = 0
            self._hit1_low = None

        if signal and flat:
            target_price = _round_digits(entry_price + self.rr * risk, 2)
            if self._limit_pending and self._pending_order_id:
                self._main.handle_intent(INTENT_CANCEL_ORDER, CancelOrderRequest(order_id=self._pending_order_id, symbol=self.symbol))
                self._limit_pending = False
                self._pending_order_id = None
            if self.use_limit:
                self._pending_order_id = self.send_order(self.symbol, "BUY", self.quantity, entry_price, "LIMIT")
                self._limit_pending = True
                self._limit_bar_idx = bar_count
            else:
                self.send_order(self.symbol, "BUY", self.quantity, entry_price, "MARKET")
            self._active_stop = stop_price
            self._active_target = target_price
            self.write_log(f"Strat1 signal entry={entry_price} stop={stop_price} target={target_price} rr={self.rr}")

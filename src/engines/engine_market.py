"""
Market engine: tracks OHLC bars and symbol state; computes indicators (ATR, pivot low, etc.).
Receives EVENT_BAR; strategies read get_symbol(), get_atr(), get_pivot_low(), etc.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, TYPE_CHECKING
import time

import requests

from src.utilities.base_engine import BaseEngine
from src.utilities.interval import Interval
from src.utilities.object import BarData, SymbolData

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


BINANCE_URL = "https://api.binance.com"


class MarketEngine(BaseEngine):
    """Symbol cache from bars; bar buffers and indicator calculations (ATR, pivot low, prev3 bearish) per symbol."""

    def __init__(
        self,
        main_engine: "MainEngine | None" = None,
        engine_name: str = "Market",
    ) -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        # Default bar buffer size; may be increased per symbol by ensure_history().
        self._max_bars_per_symbol = 512
        self._symbols: Dict[str, SymbolData] = {}
        self._bars: Dict[str, deque[BarData]] = {}
        self._bar_count: Dict[str, int] = {}
        # Throttle map for Binance klines per interval string (e.g. "5m")
        self._last_binance_fetch: Dict[str, float] = {}

    # ---------- lifecycle ----------

    def on_timer(self) -> None:
        """
        Timer hook: refresh market data from Binance for all subscribed intervals.

        - Determines which intervals are needed (from active strategies).
        - Uses main_engine.active_pairs (preferred) as the symbol universe.
        """
        me = self.main_engine
        if me is None:
            return

        symbols: List[str] = getattr(me, "active_pairs", None) or getattr(me, "trading_pairs", []) or []
        if not symbols:
            return

        intervals: set[Interval] = set()
        if hasattr(me, "strategy_engine") and me.strategy_engine is not None:
            for s in getattr(me.strategy_engine, "_strategies", []):
                ival = getattr(s, "interval", None)
                if isinstance(ival, Interval):
                    intervals.add(ival)
        if not intervals:
            intervals = {Interval.M5}

        for interval in intervals:
            self.update_from_binance(symbols, interval)

    @staticmethod
    def _bar_key(symbol: str, interval: str) -> str:
        """Composite key for per-interval bar storage."""
        return f"{symbol}_{interval}"

    def on_bar(self, event) -> None:
        """Update bar buffer and SymbolData from EVENT_BAR payload (BarData)."""
        data = getattr(event, "data", event)
        if not isinstance(data, BarData):
            return
        self.add_bar(data)
        existing = self._symbols.get(data.symbol)
        if existing is None:
            self._symbols[data.symbol] = SymbolData(
                symbol=data.symbol,
                last_price=data.close,
                ts=data.ts,
            )
        else:
            existing.last_price = data.close
            existing.ts = data.ts

    def get_symbol(self, symbol: str) -> SymbolData | None:
        """Return cached SymbolData for the symbol (last_price from latest bar close)."""
        return self._symbols.get(symbol)

    def get_cached_symbols(self) -> List[str]:
        """Return sorted list of symbols the market engine has bar/symbol data for."""
        seen: set[str] = set()
        for key in self._bars:
            parts = key.rsplit("_", 1)
            if len(parts) == 2:
                seen.add(parts[0])
        return sorted(seen)

    def update_symbol_from_ticker(
        self,
        symbol: str,
        *,
        last_price: float | None = None,
        bid_price: float | None = None,
        ask_price: float | None = None,
        volume_24h: float | None = None,
        notional_24h: float | None = None,
        change_24h: float | None = None,
    ) -> None:
        """
        Update SymbolData snapshot directly from vendor ticker data.

        This complements bar updates: bars feed indicators; ticker feeds richer snapshot fields.
        """
        if not symbol:
            return
        existing = self._symbols.get(symbol)
        if existing is None:
            existing = SymbolData(symbol=symbol)
            self._symbols[symbol] = existing
        if last_price is not None:
            existing.last_price = float(last_price)
        if bid_price is not None:
            existing.bid_price = float(bid_price)
        if ask_price is not None:
            existing.ask_price = float(ask_price)
        if volume_24h is not None:
            existing.volume_24h = float(volume_24h)
        if notional_24h is not None:
            existing.notional_24h = float(notional_24h)
        if change_24h is not None:
            existing.change_24h = float(change_24h)

    def set_symbols(self, symbols: List[str]) -> None:
        """
        Hint the market engine which symbols will be traded.

        This pre-creates bar buffers and counters for the given symbols, but does not
        clear existing data. Bars are still accepted lazily for any symbol.
        """
        for symbol in symbols:
            key = self._bar_key(symbol, "5m")
            if key not in self._bars:
                self._bars[key] = deque(maxlen=self._max_bars_per_symbol)
            if key not in self._bar_count:
                self._bar_count[key] = 0

    # ---------- bars and indicators ----------

    def add_bar(self, bar: BarData) -> None:
        """Append one bar for the symbol+interval (e.g. from EVENT_BAR)."""
        interval = bar.interval or "5m"
        key = self._bar_key(bar.symbol, interval)
        if key not in self._bars:
            self._bars[key] = deque(maxlen=self._max_bars_per_symbol)
            self._bar_count[key] = 0
        self._bars[key].append(bar)
        self._bar_count[key] += 1

    def get_bar_count(self, symbol: str, interval: str = "5m") -> int:
        """Total bars pushed for this symbol+interval."""
        return self._bar_count.get(self._bar_key(symbol, interval), 0)

    def get_last_bars(
        self, symbol: str, n: int, interval: str = "5m"
    ) -> List[BarData]:
        """Last n bars, oldest first; e.g. [-1] is latest. Returns [] if not enough bars."""
        key = self._bar_key(symbol, interval)
        bars = self._bars.get(key)
        if not bars or len(bars) < n:
            return []
        return list(bars)[-n:]

    def get_notional_sum(self, symbol: str, n: int, interval: str = "5m") -> float:
        """
        Sum of notional traded over the last n bars.

        Binance klines in this codebase only store base `volume`, not quote-volume.
        We approximate notional as sum(volume * close).
        """
        key = self._bar_key(symbol, interval)
        bars = self._bars.get(key)
        if not bars or len(bars) < n:
            return 0.0
        out = 0.0
        for b in list(bars)[-n:]:
            v = float(getattr(b, "volume", 0.0) or 0.0)
            c = float(getattr(b, "close", 0.0) or 0.0)
            if v > 0 and c > 0:
                out += v * c
        return out

    # ---------- historical backfill ----------

    def ensure_history(self, symbol: str, interval: str, bars: int) -> int:
        """
        Ensure we have at least `bars` candles buffered for symbol+interval by backfilling from Binance.

        Returns the resulting buffered bar count (len of deque).
        """
        sym = str(symbol or "").strip().upper()
        ival = str(interval or "").strip()
        need = int(bars or 0)
        if not sym or not ival or need <= 0:
            return 0

        key = self._bar_key(sym, ival)
        existing = self._bars.get(key)
        have = len(existing) if existing is not None else 0
        if have >= need:
            return have

        maxlen = max(self._max_bars_per_symbol, need, have)
        klines = self._fetch_binance_klines(sym, ival, limit=need)
        if not klines:
            return have

        out: list[BarData] = []
        for k in klines:
            if not isinstance(k, list) or len(k) < 6:
                continue
            try:
                open_ = float(k[1])
                high = float(k[2])
                low = float(k[3])
                close = float(k[4])
                volume = float(k[5])
            except Exception:
                continue
            if close <= 0:
                continue
            out.append(
                BarData(
                    symbol=sym,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    ts=None,
                    interval=ival,
                )
            )

        if not out:
            return have

        # Replace the deque with a larger buffer so strategies can compute long MAs, etc.
        self._bars[key] = deque(out, maxlen=maxlen)
        self._bar_count[key] = max(int(self._bar_count.get(key, 0) or 0), len(out))

        # Keep SymbolData last_price coherent with latest bar close.
        try:
            last_close = float(out[-1].close)
            if last_close > 0:
                self.update_symbol_from_ticker(sym, last_price=last_close)
        except Exception:
            pass

        return len(self._bars[key])

    @staticmethod
    def _fetch_binance_klines(symbol: str, interval: str, *, limit: int) -> list:
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": max(1, min(int(limit), 1000)),
        }
        try:
            resp = requests.get(f"{BINANCE_URL}/api/v3/klines", params=params, timeout=8.0)
            if resp.status_code != 200:
                return []
            body = resp.json()
            return body if isinstance(body, list) else []
        except Exception:
            return []

    def get_atr(self, symbol: str, atr_len: int = 14, interval: str = "5m") -> float:
        """ATR for the symbol (requires at least atr_len+1 bars)."""
        bars = self._bars.get(self._bar_key(symbol, interval))
        if not bars or len(bars) < atr_len + 1:
            return 0.0
        tr_sum = 0.0
        for i in range(atr_len):
            prev_b = bars[-(2 + i)]
            curr_b = bars[-(1 + i)]
            tr = max(
                curr_b.high - curr_b.low,
                abs(curr_b.high - prev_b.close),
                abs(curr_b.low - prev_b.close),
            )
            tr_sum += tr
        return tr_sum / atr_len if atr_len > 0 else 0.0

    def get_pivot_low(
        self, symbol: str, pivot_len: int, center_offset: int, interval: str = "5m"
    ) -> float | None:
        """Pivot low at bar center_offset bars back (center_offset = pivot_len for confirmed pivot). Returns None if invalid."""
        bars = self._bars.get(self._bar_key(symbol, interval))
        n = pivot_len
        if not bars or len(bars) < 2 * n + 1 or center_offset < n or center_offset >= len(bars) - n:
            return None
        low_mid = bars[-(center_offset + 1)].low
        for j in range(1, n + 1):
            l_left = bars[-(center_offset + 1 + j)].low
            l_right = bars[-(center_offset + 1 - j)].low
            if l_left <= low_mid or l_right <= low_mid:
                return None
        return low_mid

    def prev3_bearish_strict(self, symbol: str, interval: str = "5m") -> bool:
        """True if last 4 bars exist and bars at indices 1,2,3 (1=most recent past) satisfy strict bearish rules."""
        bars_list = self.get_last_bars(symbol, 4, interval)
        if len(bars_list) < 4:
            return False
        b1, b2, b3 = bars_list[-2], bars_list[-3], bars_list[-4]
        if not (b1.close < b1.open and b2.close < b2.open and b3.close < b3.open):
            return False
        if not (b1.close <= (b1.high + b1.low) / 2.0 and b2.close <= (b2.high + b2.low) / 2.0 and b3.close <= (b3.high + b3.low) / 2.0):
            return False
        if not (b2.close < b3.low and b2.high <= b3.high):
            return False
        if not (b1.close < b2.low and b1.high <= b2.high):
            return False
        return True

    # ---------- external market data (Binance) ----------

    def update_from_binance(
        self,
        symbols: List[str],
        interval: Interval,
        *,
        limit: int = 2,
        throttle_sec: float = 30.0,
    ) -> None:
        """
        Fetch latest klines from Binance for given symbols and interval, update bars and symbol snapshots.

        - symbols: internal symbols like "BTCUSDT"
        - interval: Interval enum (maps to Binance klines interval string via .binance)
        """
        if not symbols:
            return

        ival_str = interval.binance
        now = time.time()
        last = self._last_binance_fetch.get(ival_str, 0.0)
        if now - last < throttle_sec:
            return
        self._last_binance_fetch[ival_str] = now

        for symbol in symbols:
            params = {
                "symbol": symbol,
                "interval": ival_str,
                "limit": limit,
            }
            try:
                klines = self._fetch_binance_klines(symbol, ival_str, limit=limit)
                if not klines:
                    continue
                k = klines[-1]
                try:
                    open_ = float(k[1])
                    high = float(k[2])
                    low = float(k[3])
                    close = float(k[4])
                    volume = float(k[5])
                except Exception:
                    continue

                if close <= 0:
                    continue

                bar = BarData(
                    symbol=symbol,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    ts=None,
                    interval=ival_str,
                )
                # Reuse on_bar so SymbolData & buffers stay consistent.
                self.on_bar(bar)
            except Exception:
                continue

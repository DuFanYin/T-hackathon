"""
Market engine: tracks OHLC bars and symbol state; computes indicators (ATR, pivot low, etc.).
Receives EVENT_BAR; strategies read get_symbol(), get_atr(), get_pivot_low(), etc.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, TYPE_CHECKING

from src.utilities.base_engine import BaseEngine
from src.utilities.object import BarData, SymbolData

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


class MarketEngine(BaseEngine):
    """Symbol cache from bars; bar buffers and indicator calculations (ATR, pivot low, prev3 bearish) per symbol."""

    def __init__(
        self,
        main_engine: "MainEngine | None" = None,
        engine_name: str = "Market",
        trading_pairs: Optional[List[str]] = None,
    ) -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        self._max_bars_per_symbol = 64
        self._symbols: Dict[str, SymbolData] = {}
        self._bars: Dict[str, deque[BarData]] = {}
        self._bar_count: Dict[str, int] = {}
        for symbol in trading_pairs or []:
            self._bars[symbol] = deque(maxlen=self._max_bars_per_symbol)
            self._bar_count[symbol] = 0

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

    # ---------- bars and indicators ----------

    def add_bar(self, bar: BarData) -> None:
        """Append one bar for the symbol (e.g. from EVENT_BAR)."""
        symbol = bar.symbol
        if symbol not in self._bars:
            self._bars[symbol] = deque(maxlen=self._max_bars_per_symbol)
            self._bar_count[symbol] = 0
        self._bars[symbol].append(bar)
        self._bar_count[symbol] += 1

    def get_bar_count(self, symbol: str) -> int:
        """Total bars pushed for this symbol (for limit timeout etc.)."""
        return self._bar_count.get(symbol, 0)

    def get_last_bars(self, symbol: str, n: int) -> List[BarData]:
        """Last n bars, oldest first; e.g. [-1] is latest. Returns [] if not enough bars."""
        bars = self._bars.get(symbol)
        if not bars or len(bars) < n:
            return []
        return list(bars)[-n:]

    def get_atr(self, symbol: str, atr_len: int = 14) -> float:
        """ATR for the symbol (requires at least atr_len+1 bars)."""
        bars = self._bars.get(symbol)
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

    def get_pivot_low(self, symbol: str, pivot_len: int, center_offset: int) -> float | None:
        """Pivot low at bar center_offset bars back (center_offset = pivot_len for confirmed pivot). Returns None if invalid."""
        bars = self._bars.get(symbol)
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

    @staticmethod
    def _b_close_lower_half(o: float, h: float, l: float, c: float) -> bool:
        return c <= (h + l) / 2.0

    @staticmethod
    def _b_bear(o: float, c: float) -> bool:
        return c < o

    def prev3_bearish_strict(self, symbol: str) -> bool:
        """True if last 4 bars exist and bars at indices 1,2,3 (1=most recent past) satisfy strict bearish rules."""
        bars_list = self.get_last_bars(symbol, 4)
        if len(bars_list) < 4:
            return False
        b1, b2, b3 = bars_list[-2], bars_list[-3], bars_list[-4]
        if not (self._b_bear(b1.open, b1.close) and self._b_bear(b2.open, b2.close) and self._b_bear(b3.open, b3.close)):
            return False
        if not (
            self._b_close_lower_half(b1.open, b1.high, b1.low, b1.close)
            and self._b_close_lower_half(b2.open, b2.high, b2.low, b2.close)
            and self._b_close_lower_half(b3.open, b3.high, b3.low, b3.close)
        ):
            return False
        if not (b2.close < b3.low and b2.high <= b3.high):
            return False
        if not (b1.close < b2.low and b1.high <= b2.high):
            return False
        return True

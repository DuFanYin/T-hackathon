"""
Interval enum for bar/candle timeframes.

Each strategy uses one interval. Maps to Binance /api/v3/klines interval strings.
"""

from __future__ import annotations

from enum import Enum


class Interval(str, Enum):
    """Candle interval. Use .binance for Binance API string."""

    M1 = "1m"
    M3 = "3m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    H6 = "6h"
    H8 = "8h"
    H12 = "12h"
    D1 = "1d"
    D3 = "3d"
    W1 = "1w"
    MN1 = "1M"

    @property
    def binance(self) -> str:
        """Binance /api/v3/klines interval string."""
        return self.value

    @classmethod
    def from_str(cls, s: str | None) -> "Interval":
        """Parse string to Interval. Default M5 if invalid or None."""
        if not s:
            return cls.M5
        v = str(s).strip().lower()
        for i in cls:
            if i.value == v:
                return i
        return cls.M5

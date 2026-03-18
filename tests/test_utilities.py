"""
Tests for utilities: Interval, object types.
"""

import pytest
from datetime import datetime

from src.utilities.interval import Interval
from src.utilities.object import (
    BarData,
    OrderData,
    OrderRequest,
    PositionData,
    StrategyHolding,
    SymbolData,
)


class TestInterval:
    """Tests for Interval enum."""

    def test_from_str_valid(self):
        assert Interval.from_str("5m") == Interval.M5
        assert Interval.from_str("1h") == Interval.H1
        assert Interval.from_str("1d") == Interval.D1

    def test_from_str_none_defaults_m5(self):
        assert Interval.from_str(None) == Interval.M5

    def test_from_str_invalid_defaults_m5(self):
        assert Interval.from_str("invalid") == Interval.M5
        assert Interval.from_str("") == Interval.M5

    def test_binance_property(self):
        assert Interval.M5.binance == "5m"
        assert Interval.H1.binance == "1h"


class TestBarData:
    """Tests for BarData."""

    def test_creation(self):
        bar = BarData("BTCUSDT", 100.0, 105.0, 99.0, 102.0)
        assert bar.symbol == "BTCUSDT"
        assert bar.open == 100.0
        assert bar.high == 105.0
        assert bar.low == 99.0
        assert bar.close == 102.0

    def test_with_optional_fields(self):
        ts = datetime.now()
        bar = BarData("BTCUSDT", 100, 105, 99, 102, volume=1000.0, ts=ts, interval="5m")
        assert bar.volume == 1000.0
        assert bar.ts == ts
        assert bar.interval == "5m"


class TestOrderData:
    """Tests for OrderData."""

    def test_creation(self):
        od = OrderData(
            order_id="123",
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            price=50000.0,
            status="FILLED",
        )
        assert od.order_id == "123"
        assert od.symbol == "BTCUSDT"
        assert od.side == "BUY"
        assert od.quantity == 0.01
        assert od.price == 50000.0
        assert od.status == "FILLED"
        assert od.filled_quantity == 0.0


class TestOrderRequest:
    """Tests for OrderRequest."""

    def test_creation(self):
        req = OrderRequest(
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.01,
            price=50000.0,
            order_type="LIMIT",
            strategy_name="StratTestAlt",
        )
        assert req.symbol == "BTCUSDT"
        assert req.side == "BUY"
        assert req.quantity == 0.01
        assert req.price == 50000.0
        assert req.order_type == "LIMIT"
        assert req.strategy_name == "StratTestAlt"


class TestPositionData:
    """Tests for PositionData."""

    def test_creation(self):
        pos = PositionData(symbol="BTCUSDT", quantity=0.01, avg_cost=50000.0)
        assert pos.symbol == "BTCUSDT"
        assert pos.quantity == 0.01
        assert pos.avg_cost == 50000.0

    def test_current_value(self):
        pos = PositionData(symbol="BTCUSDT", quantity=0.01, mid_price=51000.0)
        assert pos.current_value() == 510.0


class TestStrategyHolding:
    """Tests for StrategyHolding."""

    def test_empty_holding(self):
        h = StrategyHolding()
        assert h.positions == {}
        assert h.total_cost == 0.0
        assert h.current_value == 0.0

    def test_holding_with_positions(self):
        h = StrategyHolding()
        h.positions["BTCUSDT"] = PositionData(symbol="BTCUSDT", quantity=0.01, avg_cost=50000.0)
        assert "BTCUSDT" in h.positions
        assert h.positions["BTCUSDT"].quantity == 0.01


class TestSymbolData:
    """Tests for SymbolData."""

    def test_creation(self):
        sd = SymbolData(symbol="BTCUSDT", last_price=50000.0)
        assert sd.symbol == "BTCUSDT"
        assert sd.last_price == 50000.0

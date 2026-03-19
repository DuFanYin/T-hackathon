"""
Tests for StrategyEngine.
"""

import pytest

from src.engines.engine_strategy import AVAILABLE_STRATEGIES, StrategyEngine
from src.utilities.object import PositionData, StrategyHolding


class TestStrategyEngine:
    """Tests for StrategyEngine."""

    @pytest.fixture
    def main_engine_mock(self):
        """MainEngine mock with required attributes for StrategyEngine."""
        from unittest.mock import MagicMock

        main = MagicMock()
        main.active_pairs = []
        main.trading_pairs = []
        main.gateway_engine = MagicMock()
        main.gateway_engine.trading_pairs = []
        main.market_engine = MagicMock()
        return main

    def test_add_strategy_requires_main_engine(self):
        engine = StrategyEngine(main_engine=None)
        with pytest.raises(ValueError, match="main_engine is required"):
            engine.add_strategy_by_name("StratTestAlt")

    def test_add_strategy_unknown_name_raises(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        with pytest.raises(ValueError, match="Unknown strategy name"):
            engine.add_strategy_by_name("UnknownStrategy")

    def test_add_strategy_by_name_returns_instance(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        strat = engine.add_strategy_by_name("StratTestAlt")
        assert strat is not None
        assert strat.strategy_name == "StratTestAlt"
        assert engine.get_strategy("StratTestAlt") is strat

    def test_add_strategy_strategy_jh(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        strat = engine.add_strategy_by_name("strategy_JH")
        assert strat.strategy_name == "strategy_JH"
        assert "BTCUSDT" in strat.symbols

    def test_add_strategy_strat2_momentum(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        strat = engine.add_strategy_by_name("Strat2Momentum")
        assert strat.strategy_name == "Strat2Momentum"
        assert "BTCUSDT" in strat.symbols

    def test_get_strategy_none_for_missing(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        assert engine.get_strategy("StratTestAlt") is None

    def test_get_holding_returns_strategy_holding(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        holding = engine.get_holding("StratTestAlt")
        assert isinstance(holding, StrategyHolding)
        assert engine.get_holding("StratTestAlt") is holding

    def test_stop_strategy_raises_when_has_positions(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        engine.add_strategy_by_name("StratTestAlt")
        holding = engine.get_holding("StratTestAlt")
        holding.positions["BTCUSDT"] = PositionData(symbol="BTCUSDT", quantity=0.001)
        with pytest.raises(ValueError, match="open positions"):
            engine.stop_strategy("StratTestAlt")

    def test_stop_strategy_succeeds_when_flat(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        engine.add_strategy_by_name("StratTestAlt")
        engine.start_strategy("StratTestAlt")
        engine.stop_strategy("StratTestAlt")

    def test_remove_strategy(self, main_engine_mock):
        engine = StrategyEngine(main_engine=main_engine_mock)
        engine.add_strategy_by_name("StratTestAlt")
        assert engine.get_strategy("StratTestAlt") is not None
        engine.remove_strategy("StratTestAlt")
        assert engine.get_strategy("StratTestAlt") is None


class TestAvailableStrategies:
    """Tests for AVAILABLE_STRATEGIES registry."""

    def test_contains_expected_strategies(self):
        assert "strategy_JH" in AVAILABLE_STRATEGIES
        assert "Strat2Momentum" in AVAILABLE_STRATEGIES
        assert "StratTestAlt" in AVAILABLE_STRATEGIES

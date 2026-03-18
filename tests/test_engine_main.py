"""
Tests for MainEngine.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.engines.engine_main import MainEngine


def _mock_exchange_info():
    return {
        "TradePairs": {
            "BTC_USDT": {},
            "ETH_USDT": {},
        },
    }


class TestMainEngine:
    """Tests for MainEngine."""

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_add_strategy_get_strategy(self, mock_refresh, mock_info):
        main = MainEngine(env_mode="mock")
        main.add_strategy("StratTestAlt")
        strat = main.get_strategy("StratTestAlt")
        assert strat is not None
        assert strat.strategy_name == "StratTestAlt"

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_get_strategy_returns_none_for_missing(self, mock_refresh, mock_info):
        main = MainEngine(env_mode="mock")
        assert main.get_strategy("StratTestAlt") is None

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_start_stop_strategy(self, mock_refresh, mock_info):
        main = MainEngine(env_mode="mock")
        main.add_strategy("StratTestAlt")
        main.start_strategy("StratTestAlt")
        main.stop_strategy("StratTestAlt")

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_delete_strategy(self, mock_refresh, mock_info):
        main = MainEngine(env_mode="mock")
        main.add_strategy("StratTestAlt")
        main.delete_strategy("StratTestAlt")
        assert main.get_strategy("StratTestAlt") is None

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_add_all_strategies(self, mock_refresh, mock_info):
        main = MainEngine(env_mode="mock")
        main.add_strategy("Strat1Pine")
        main.add_strategy("Strat2Momentum")
        main.add_strategy("StratTestAlt")
        assert main.get_strategy("Strat1Pine") is not None
        assert main.get_strategy("Strat2Momentum") is not None
        assert main.get_strategy("StratTestAlt") is not None

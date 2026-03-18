"""
Tests for EngineManager.
"""

import pytest
from unittest.mock import patch, MagicMock

from src.control.engine_manager import EngineManager


def _mock_exchange_info():
    """Minimal exchangeInfo response to avoid network."""
    return {
        "TradePairs": {
            "BTC_USDT": {},
            "ETH_USDT": {},
        },
    }


class TestEngineManager:
    """Tests for EngineManager."""

    @pytest.fixture
    def manager(self):
        return EngineManager()

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_start_stop_cycle(self, mock_refresh, mock_info, manager):
        status = manager.start("mock")
        assert status.running is True
        assert status.mode == "mock"

        status = manager.stop()
        assert status.running is False
        assert status.mode is None

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_start_idempotent(self, mock_refresh, mock_info, manager):
        manager.start("mock")
        status = manager.start("mock")
        assert status.running is True

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_require_raises_when_not_running(self, mock_refresh, mock_info, manager):
        with pytest.raises(RuntimeError, match="not running"):
            manager.require()

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", return_value=_mock_exchange_info())
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_get_returns_none_when_stopped(self, mock_refresh, mock_info, manager):
        assert manager.get() is None

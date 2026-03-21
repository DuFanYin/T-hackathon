"""
Pytest fixtures for T-hackathon tests.
"""

import pytest


@pytest.fixture
def mock_main_engine():
    """Minimal MainEngine-like object for unit tests (no network)."""
    from unittest.mock import MagicMock

    main = MagicMock()
    main.active_pairs = []
    main.trading_pairs = []
    main.market_engine = MagicMock()
    main.gateway_engine = MagicMock()
    main.strategy_engine = MagicMock()
    return main

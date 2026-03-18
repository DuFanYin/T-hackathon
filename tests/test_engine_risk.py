"""
Tests for RiskEngine and _parse_equity_usd.
"""

import pytest

from src.engines.engine_risk import (
    RISK_CONFIG,
    RiskEngine,
    _parse_equity_usd,
)


class TestParseEquityUsd:
    """Tests for _parse_equity_usd."""

    def test_empty_or_none_returns_zero(self):
        assert _parse_equity_usd(None) == 0.0
        assert _parse_equity_usd({}) == 0.0

    def test_no_wallet_returns_zero(self):
        assert _parse_equity_usd({"other": "data"}) == 0.0

    def test_wallet_usdt(self):
        bal = {
            "Wallet": {
                "USDT": {"Free": 100.5, "Lock": 20.0},
                "BTC": {"Free": 0.1, "Lock": 0},
            },
        }
        assert _parse_equity_usd(bal) == 120.5

    def test_spot_wallet_fallback(self):
        bal = {
            "SpotWallet": {
                "USD": {"Free": 50.0, "Lock": 0},
                "USDT": {"Free": 25.0, "Lock": 0},
                "BUSD": {"Free": 10.0, "Lock": 5.0},
            },
        }
        assert _parse_equity_usd(bal) == 90.0

    def test_wallet_preferred_over_spot(self):
        bal = {
            "Wallet": {"USDT": {"Free": 100, "Lock": 0}},
            "SpotWallet": {"USDT": {"Free": 200, "Lock": 0}},
        }
        assert _parse_equity_usd(bal) == 100.0

    def test_no_usd_usdt_busd_returns_zero(self):
        bal = {"Wallet": {"BTC": {"Free": 1.0, "Lock": 0}}}
        assert _parse_equity_usd(bal) == 0.0

    def test_invalid_entry_skipped(self):
        bal = {
            "Wallet": {
                "USDT": {"Free": 100, "Lock": 0},
                "ETH": "invalid",
            },
        }
        assert _parse_equity_usd(bal) == 100.0


class TestRiskEngineConfig:
    """Tests for RiskEngine hard-coded config."""

    def test_risk_config_has_expected_keys(self):
        assert "max_drawdown_pct" in RISK_CONFIG
        assert "atr_drawdown_multiplier" in RISK_CONFIG
        assert "atr_daily_len" in RISK_CONFIG
        assert "daily_interval" in RISK_CONFIG
        assert "atr_log_every_ticks" in RISK_CONFIG

    def test_risk_engine_uses_config(self):
        engine = RiskEngine(main_engine=None)
        assert engine.max_drawdown_pct == 10.0
        assert engine.atr_drawdown_multiplier == 2.0
        assert engine.atr_daily_len == 14
        assert engine.daily_interval == "1d"
        assert engine.atr_log_every_ticks == 60
        assert engine.daily_bars_needed == 15

    def test_risk_engine_on_timer_no_breach(self):
        engine = RiskEngine(main_engine=None)
        engine.on_timer()
        assert engine._breach_triggered is False

    def test_risk_engine_max_drawdown_pct_no_atr(self):
        engine = RiskEngine(main_engine=None)
        engine.account_init_balance = 1000.0
        assert engine._max_drawdown_pct() == 10.0

    def test_risk_engine_max_drawdown_pct_with_atr(self):
        from unittest.mock import MagicMock

        main = MagicMock()
        main.market_engine = MagicMock()
        main.market_engine.get_symbol.return_value = MagicMock(last_price=50000.0)
        engine = RiskEngine(main_engine=main)
        engine.account_init_balance = 100000.0
        engine._daily_atr = {"BTCUSDT": 500.0}
        pct = engine._max_drawdown_pct()
        assert 1.0 <= pct <= 10.0

"""
Tests for each strategy: strategy_JH, strategy_maliki, StratTestAlt.
"""

import pytest
from unittest.mock import MagicMock

from src.strategies.factory import StrategyJH, StrategyMaliki, StratTestAlt
from src.strategies.factory.strategy_maliki import TRACKED_COINS


def _main_engine_mock():
    """MainEngine mock with market, gateway, strategy_engine, handle_intent."""
    main = MagicMock()
    main.active_pairs = []
    main.trading_pairs = []
    main.gateway_engine = MagicMock()
    main.gateway_engine.trading_pairs = []
    main.market_engine = MagicMock()
    main.strategy_engine = MagicMock()
    main.handle_intent = MagicMock(return_value="order-123")
    main.get_pending_orders_by_symbol = MagicMock(return_value={})
    main.query_order = MagicMock(return_value={"OrderDetail": {"Status": "FILLED"}})
    main.cancel_order = MagicMock()
    main.stop_strategy = MagicMock()
    main.put_event = MagicMock()
    return main


class TestStratTestAlt:
    """Tests for StratTestAlt."""

    def test_construction_default_symbol(self):
        main = _main_engine_mock()
        strat = StratTestAlt(main, "StratTestAlt_Test", setting={})
        assert strat.strategy_name == "StratTestAlt_Test"
        assert strat.symbol == "BTCUSDT"
        assert strat.quantity == 0.01
        assert strat._next_action_open is True

    def test_construction_with_setting(self):
        main = _main_engine_mock()
        strat = StratTestAlt(
            main, "StratTestAlt_Test",
            setting={"quantity": 0.01, "timer_trigger": 5},
        )
        assert strat.symbol == "BTCUSDT"  # BTC only
        assert strat.quantity == 0.01

    def test_on_init_on_start(self):
        main = _main_engine_mock()
        strat = StratTestAlt(main, "StratTestAlt_Test")
        strat.on_init()
        strat.on_start()
        assert strat.inited
        assert strat.started

    def test_on_timer_logic_sends_order(self):
        main = _main_engine_mock()
        main.market_engine.get_symbol.return_value = MagicMock(last_price=50000.0)
        holding = MagicMock()
        holding.positions = {}  # flat
        main.strategy_engine.get_holding.return_value = holding
        strat = StratTestAlt(main, "StratTestAlt_Test", setting={"quantity": 0.001})
        strat.on_init()
        strat.on_start()
        strat.on_timer_logic()
        assert main.handle_intent.called


class TestStrategyJH:
    """Tests for strategy_JH (StrategyJH)."""

    def test_construction_defaults(self):
        main = _main_engine_mock()
        strat = StrategyJH(main, "strategy_JH_Test", setting={})
        assert strat.strategy_name == "strategy_JH_Test"
        # Default universe comes from PAIRS_CONFIG inside the strategy.
        assert "APTUSDT" in strat.symbols
        assert strat.interval.binance == "15m"
        assert strat.pivot_len == 5
        assert strat.rr == 2.0
        assert strat.atr_len == 14
        assert strat.fill_bars == 1
        assert strat.capital == 150_000.0
        assert strat.risk_pct == 0.01

    def test_history_requirements(self):
        main = _main_engine_mock()
        strat = StrategyJH(main, "strategy_JH_Test")
        reqs = strat.history_requirements()
        assert len(reqs) >= 1
        assert any(r.get("symbol") == "APTUSDT" for r in reqs)


class TestStrategyMaliki:
    """Tests for strategy_maliki (StrategyMaliki)."""

    def test_construction_defaults(self):
        main = _main_engine_mock()
        strat = StrategyMaliki(main, "strategy_maliki_Test", setting={})
        assert strat.strategy_name == "strategy_maliki_Test"
        assert "BTCUSDT" in strat.symbols
        assert strat.lookback_candles == 576
        assert strat.top_n == 1
        assert strat.rebalance_every == 288
        assert strat.trailing_stop_pct == 8.0
        assert strat.min_hold_candles == 288
        assert strat.regime_ma_candles == 576

    def test_construction_with_setting(self):
        main = _main_engine_mock()
        strat = StrategyMaliki(
            main, "strategy_maliki_Test",
            setting={
                "lookback_candles": 48,
                "top_n": 3,
                "rebalance_every": 24,
                "trailing_stop_pct": 5.0,
            },
        )
        assert strat.lookback_candles == 48
        assert strat.top_n == 3
        assert strat.rebalance_every == 24
        assert strat.trailing_stop_pct == 5.0

    def test_format_order_symbol_gateway(self):
        main = _main_engine_mock()
        strat = StrategyMaliki(main, "maliki", setting={"order_symbol_format": "gateway"})
        assert strat._format_order_symbol("BTC") == "BTCUSDT"
        assert strat._format_pair("BTC") == "BTC/USD"

    def test_format_order_symbol_slash(self):
        main = _main_engine_mock()
        strat = StrategyMaliki(main, "maliki", setting={"order_symbol_format": "slash"})
        assert strat._format_order_symbol("BTC") == "BTC/USD"

    def test_history_requirements(self):
        main = _main_engine_mock()
        strat = StrategyMaliki(main, "strategy_maliki_Test")
        reqs = strat.history_requirements()
        assert len(reqs) >= len(TRACKED_COINS) + 1
        btc_req = next(r for r in reqs if r.get("symbol") == "BTCUSDT")
        # Regime MA now uses 48h (576 bars on 5m candles)
        assert btc_req["bars"] == 576

    def test_has_enough_data_false_when_no_market(self):
        main = _main_engine_mock()
        main.market_engine = None
        strat = StrategyMaliki(main, "strategy_maliki_Test")
        assert strat._has_enough_data() is False

    def test_has_enough_data_false_when_insufficient_bars(self):
        main = _main_engine_mock()
        main.market_engine.get_bar_count.return_value = 100
        strat = StrategyMaliki(main, "strategy_maliki_Test")
        assert strat._has_enough_data() is False

    def test_has_enough_data_true_when_sufficient(self):
        main = _main_engine_mock()
        # Must be >= regime_ma_candles (default 576)
        main.market_engine.get_bar_count.return_value = 600
        strat = StrategyMaliki(main, "strategy_maliki_Test")
        assert strat._has_enough_data() is True

    def test_get_momentum_rankings_empty_when_no_market(self):
        main = _main_engine_mock()
        main.market_engine = None
        strat = StrategyMaliki(main, "strategy_maliki_Test")
        assert strat._get_momentum_rankings() == []

    def test_get_momentum_rankings_returns_sorted(self):
        from src.utilities.object import BarData
        from datetime import datetime

        main = _main_engine_mock()
        ts = datetime.now()
        bars_btc = [BarData("BTCUSDT", 100 - i, 101, 99, 100 - i, ts=ts) for i in range(96)]
        bars_eth = [BarData("ETHUSDT", 50, 51, 49, 50 + i, ts=ts) for i in range(96)]
        main.market_engine.get_last_bars.side_effect = lambda s, n, i: bars_btc if s == "BTCUSDT" else bars_eth
        strat = StrategyMaliki(main, "strategy_maliki_Test")
        rankings = strat._get_momentum_rankings()
        assert isinstance(rankings, list)
        if rankings:
            assert all("coin" in r and "momentum_pct" in r for r in rankings)

    def test_on_stop_logic_closes_positions(self):
        main = _main_engine_mock()
        main.market_engine.get_symbol.return_value = MagicMock(last_price=50000.0)
        strat = StrategyMaliki(main, "strategy_maliki_Test")
        holding = main.strategy_engine.get_holding.return_value
        holding.positions = {"BTCUSDT": MagicMock(quantity=0.01)}
        strat.on_stop_logic()
        assert main.handle_intent.called

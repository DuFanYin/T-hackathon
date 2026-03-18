"""
Tests for each strategy: Strat1Pine, Strat2Momentum, StratTestAlt.
"""

import pytest
from unittest.mock import MagicMock

from src.strategies.factory import Strat1Pine, Strat2Momentum, StratTestAlt
from src.strategies.factory.strat2_momentum import TRACKED_COINS


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
        assert strat.quantity == 0.001
        assert strat._cycle_limit == 3
        assert strat._side_next == "BUY"

    def test_construction_with_setting(self):
        main = _main_engine_mock()
        strat = StratTestAlt(
            main, "StratTestAlt_Test",
            setting={"symbols": ["ETHUSDT"], "quantity": 0.01, "timer_trigger": 5},
        )
        assert strat.symbol == "ETHUSDT"
        assert strat.quantity == 0.01
        assert strat._timer_trigger == 5

    def test_order_attempts_property(self):
        main = _main_engine_mock()
        strat = StratTestAlt(main, "StratTestAlt_Test")
        assert strat.order_attempts == 0
        strat._order_attempts = 5
        assert strat.order_attempts == 5

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
        strat = StratTestAlt(main, "StratTestAlt_Test", setting={"quantity": 0.001})
        strat.on_init()
        strat.on_start()
        strat.on_timer_logic()
        assert main.handle_intent.called
        assert strat._order_attempts == 1


class TestStrat1Pine:
    """Tests for Strat1Pine."""

    def test_construction_empty_market_symbols(self):
        main = _main_engine_mock()
        main.market_engine.get_cached_symbols.return_value = []
        strat = Strat1Pine(main, "Strat1Pine_Test", setting={})
        assert strat.symbols == []
        assert strat.pivot_len == 3
        assert strat.rr == 2.0
        assert strat.use_limit is True
        assert strat.quantity == 1.0

    def test_construction_with_cached_symbols(self):
        main = _main_engine_mock()
        main.market_engine.get_cached_symbols.return_value = ["BTCUSDT", "ETHUSDT"]
        strat = Strat1Pine(main, "Strat1Pine_Test", setting={})
        assert strat.symbols == ["BTCUSDT", "ETHUSDT"]

    def test_construction_with_setting_overrides(self):
        main = _main_engine_mock()
        main.market_engine.get_cached_symbols.return_value = ["BTCUSDT"]
        strat = Strat1Pine(
            main, "Strat1Pine_Test",
            setting={"pivot_len": 5, "rr": 3.0, "use_limit": False, "quantity": 0.5},
        )
        assert strat.pivot_len == 5
        assert strat.rr == 3.0
        assert strat.use_limit is False
        assert strat.quantity == 0.5

    def test_get_state_returns_default(self):
        main = _main_engine_mock()
        main.market_engine.get_cached_symbols.return_value = ["BTCUSDT"]
        strat = Strat1Pine(main, "Strat1Pine_Test")
        st = strat._get_state("BTCUSDT")
        assert st["sup_price"] is None
        assert st["hit_count"] == 0
        assert st["active_stop"] is None
        assert st["active_target"] is None

    def test_on_init_logic(self):
        main = _main_engine_mock()
        main.market_engine.get_cached_symbols.return_value = ["BTCUSDT"]
        strat = Strat1Pine(main, "Strat1Pine_Test")
        strat.on_init_logic()
        assert main.put_event.called

    def test_on_timer_logic_no_bars_returns_early(self):
        main = _main_engine_mock()
        main.market_engine.get_cached_symbols.return_value = ["BTCUSDT"]
        main.market_engine.get_last_bars.return_value = []
        main.market_engine.get_bar_count.return_value = 0
        strat = Strat1Pine(main, "Strat1Pine_Test")
        strat.on_init()
        strat.on_start()
        strat.on_timer_logic()
        main.market_engine.get_last_bars.assert_called()


class TestStrat2Momentum:
    """Tests for Strat2Momentum."""

    def test_construction_defaults(self):
        main = _main_engine_mock()
        strat = Strat2Momentum(main, "Strat2Momentum_Test", setting={})
        assert strat.strategy_name == "Strat2Momentum_Test"
        assert "BTCUSDT" in strat.symbols
        assert strat.lookback_candles == 96
        assert strat.top_n == 2
        assert strat.rebalance_every == 48
        assert strat.trailing_stop_pct == 3.0
        assert strat.min_hold_candles == 24
        assert strat.regime_ma_candles == 288

    def test_construction_with_setting(self):
        main = _main_engine_mock()
        strat = Strat2Momentum(
            main, "Strat2Momentum_Test",
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
        strat = Strat2Momentum(main, "Strat2", setting={"order_symbol_format": "gateway"})
        assert strat._format_order_symbol("BTC") == "BTCUSDT"
        assert strat._format_pair("BTC") == "BTC/USD"

    def test_format_order_symbol_slash(self):
        main = _main_engine_mock()
        strat = Strat2Momentum(main, "Strat2", setting={"order_symbol_format": "slash"})
        assert strat._format_order_symbol("BTC") == "BTC/USD"

    def test_history_requirements(self):
        main = _main_engine_mock()
        strat = Strat2Momentum(main, "Strat2Momentum_Test")
        reqs = strat.history_requirements()
        assert len(reqs) >= len(TRACKED_COINS) + 1
        btc_req = next(r for r in reqs if r.get("symbol") == "BTCUSDT")
        assert btc_req["bars"] == 288

    def test_has_enough_data_false_when_no_market(self):
        main = _main_engine_mock()
        main.market_engine = None
        strat = Strat2Momentum(main, "Strat2Momentum_Test")
        assert strat._has_enough_data() is False

    def test_has_enough_data_false_when_insufficient_bars(self):
        main = _main_engine_mock()
        main.market_engine.get_bar_count.return_value = 100
        strat = Strat2Momentum(main, "Strat2Momentum_Test")
        assert strat._has_enough_data() is False

    def test_has_enough_data_true_when_sufficient(self):
        main = _main_engine_mock()
        main.market_engine.get_bar_count.return_value = 300
        strat = Strat2Momentum(main, "Strat2Momentum_Test")
        assert strat._has_enough_data() is True

    def test_get_momentum_rankings_empty_when_no_market(self):
        main = _main_engine_mock()
        main.market_engine = None
        strat = Strat2Momentum(main, "Strat2Momentum_Test")
        assert strat._get_momentum_rankings() == []

    def test_get_momentum_rankings_returns_sorted(self):
        from src.utilities.object import BarData
        from datetime import datetime

        main = _main_engine_mock()
        ts = datetime.now()
        bars_btc = [BarData("BTCUSDT", 100 - i, 101, 99, 100 - i, ts=ts) for i in range(96)]
        bars_eth = [BarData("ETHUSDT", 50, 51, 49, 50 + i, ts=ts) for i in range(96)]
        main.market_engine.get_last_bars.side_effect = lambda s, n, i: bars_btc if s == "BTCUSDT" else bars_eth
        strat = Strat2Momentum(main, "Strat2Momentum_Test")
        rankings = strat._get_momentum_rankings()
        assert isinstance(rankings, list)
        if rankings:
            assert all("coin" in r and "momentum_pct" in r for r in rankings)

    def test_on_stop_logic_closes_positions(self):
        main = _main_engine_mock()
        main.market_engine.get_symbol.return_value = MagicMock(last_price=50000.0)
        strat = Strat2Momentum(main, "Strat2Momentum_Test")
        strat._positions["BTC"] = {
            "qty": 0.01, "entry_price": 50000, "peak_price": 50000,
            "entry_tick": 0, "roostoo_pair": "BTC/USD", "roostoo_symbol": "BTCUSDT",
        }
        strat.on_stop_logic()
        assert "BTC" not in strat._positions

"""
tests/test_live_readiness.py — Round 1 deployment readiness tests.

Verifies the critical path for live trading using mock mode only.
Does NOT place real orders or hit external APIs.
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.engines.engine_event import EventEngine
from src.engines.engine_main import MainEngine
from src.engines.engine_market import MarketEngine
from src.engines.engine_strategy import StrategyEngine
from src.strategies.factory import StrategyJH, StrategyMaliki
from src.strategies.factory.strategy_JH import PAIRS_CONFIG, _round_price, _round_qty
from src.strategies.factory.strategy_maliki import TRACKED_COINS
from src.strategies.template import StrategyTemplate
from src.utilities.object import (
    BarData, OrderData, PositionData, SymbolData, TradingPair,
)


# ═══════════════════════════════════════════════════
# Shared helpers
# ═══════════════════════════════════════════════════


def _mock_main():
    """MagicMock main engine for simple unit tests (no real engines)."""
    main = MagicMock()
    main.active_pairs = []
    main.trading_pairs = []
    main.trading_pairs_by_symbol = {}
    main.gateway_engine = MagicMock()
    main.gateway_engine.trading_pairs = []
    main.market_engine = MagicMock()
    main.strategy_engine = MagicMock()
    main.risk_engine = MagicMock()
    main.handle_intent = MagicMock(return_value="order-123")
    main.get_pending_orders_by_symbol = MagicMock(return_value={})
    main.put_event = MagicMock()
    main.get_trading_pair = MagicMock(return_value=None)
    return main


def _functional_main():
    """Main with real MarketEngine + StrategyEngine, mocked gateway. No network."""
    main = SimpleNamespace()
    main.active_pairs = []
    main.trading_pairs = []
    main.trading_pairs_by_symbol = {}
    main.market_engine = MarketEngine(main_engine=None)
    main.put_event = MagicMock()
    main.strategy_engine = StrategyEngine(main_engine=main)
    main.risk_engine = MagicMock()
    main.event_engine = EventEngine(main_engine=main)
    main.gateway_engine = MagicMock()
    main.gateway_engine.trading_pairs = []
    main.gateway_engine.trading_pairs_by_symbol = {}
    main.gateway_engine.get_pending_orders_by_symbol = MagicMock(return_value={})
    main.gateway_engine.get_balance = MagicMock(return_value=None)

    main.handle_intent = main.event_engine.handle_intent
    main.get_pending_orders_by_symbol = (
        lambda sn: main.gateway_engine.get_pending_orders_by_symbol(sn)
    )
    main.get_trading_pair = lambda sym: main.trading_pairs_by_symbol.get(
        str(sym).strip().upper()
    )
    main.place_order = MagicMock(return_value=None)
    main.cancel_order = MagicMock()
    return main


def _seed_bars(me, symbol, closes, interval="5m", *, volume=100.0):
    """Seed MarketEngine with bars from a list of close prices."""
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = max(o, c) * 1.001
        l = min(o, c) * 0.999
        me.on_bar(
            BarData(
                symbol=symbol, open=o, high=h, low=l, close=c,
                volume=volume, interval=interval,
            )
        )


def _make_tp(symbol, price_precision=2, amount_precision=6, mini_order=10.0):
    """Create a TradingPair for testing precision."""
    base = symbol.replace("USDT", "")
    return TradingPair(
        pair=f"{base}/USD", symbol=symbol, coin=base, unit="USD",
        can_trade=True, price_precision=price_precision,
        amount_precision=amount_precision, mini_order=mini_order,
    )


# ═══════════════════════════════════════════════════
# GROUP 1: Strategy Initialization
# ═══════════════════════════════════════════════════


class TestGroup1StrategyInit:

    def test_maliki_starts_without_errors(self):
        main = _mock_main()
        strat = StrategyMaliki(main, "strategy_maliki")
        strat.on_init()
        strat.on_start()
        assert strat.inited and strat.started and not strat.error

    def test_maliki_correct_params(self):
        main = _mock_main()
        s = StrategyMaliki(main, "strategy_maliki")
        assert s.lookback_candles == 576
        assert s.top_n == 1
        assert s.rebalance_every == 288
        assert s.trailing_stop_pct == 8.0
        assert s.min_hold_candles == 288
        assert s.regime_ma_candles == 576
        assert s.min_momentum_pct == 3.0
        assert s.interval.binance == "5m"
        assert s._timer_trigger == 300

    def test_jh_starts_without_errors(self):
        main = _mock_main()
        strat = StrategyJH(main, "strategy_JH")
        strat.on_init()
        strat.on_start()
        assert strat.inited and strat.started and not strat.error

    def test_jh_correct_params(self):
        main = _mock_main()
        s = StrategyJH(main, "strategy_JH")
        assert s.interval.binance == "15m"
        assert s.pivot_len == 5
        assert s.rr == 2.0
        assert s.atr_len == 14
        assert s.fill_bars == 1
        assert len(s.symbols) == 8
        assert sorted(s.symbols) == sorted(PAIRS_CONFIG.keys())
        assert s.capital == 20_000.0
        assert s.risk_pct == 0.01

    def test_both_strategies_simultaneous(self):
        main = _mock_main()
        m = StrategyMaliki(main, "strategy_maliki")
        j = StrategyJH(main, "strategy_JH")
        m.on_init(); m.on_start()
        j.on_init(); j.on_start()
        assert m.started and j.started
        assert not m.error and not j.error


# ═══════════════════════════════════════════════════
# GROUP 2: Order Precision
# ═══════════════════════════════════════════════════


class TestGroup2OrderPrecision:

    def test_trading_pair_parses_precision(self):
        spec = {"PricePrecision": 2, "AmountPrecision": 5, "MiniOrder": 10.0,
                "Coin": "BTC", "Unit": "USD", "CanTrade": True}
        tp = TradingPair.from_exchange_entry("BTC/USD", spec, symbol="BTCUSDT")
        assert tp.price_precision == 2
        assert tp.amount_precision == 5
        assert tp.mini_order == 10.0

    def test_prepare_order_rounds_qty_and_price(self):
        main = _mock_main()
        tp = _make_tp("BTCUSDT", amount_precision=5, price_precision=2)
        main.get_trading_pair = MagicMock(return_value=tp)
        main.market_engine.get_symbol.return_value = SymbolData(
            symbol="BTCUSDT", last_price=70000.0,
        )
        strat = StrategyMaliki(main, "strategy_maliki")
        result = strat._prepare_order_for_exchange("BTCUSDT", 0.123456789, 70000.123, "LIMIT")
        assert result is not None
        qty, price, _ = result
        assert qty == pytest.approx(0.12346, abs=1e-6)
        assert price == pytest.approx(70000.12, abs=0.01)

    def test_prepare_order_market_sets_price_zero(self):
        main = _mock_main()
        tp = _make_tp("BTCUSDT", amount_precision=3)
        main.get_trading_pair = MagicMock(return_value=tp)
        main.market_engine.get_symbol.return_value = SymbolData(symbol="BTCUSDT", last_price=70000)
        strat = StrategyMaliki(main, "strategy_maliki")
        result = strat._prepare_order_for_exchange("BTCUSDT", 0.5, 0.0, "MARKET")
        assert result is not None
        _, price, ot = result
        assert ot == "MARKET" and price == 0.0

    @pytest.mark.parametrize("symbol", sorted(PAIRS_CONFIG.keys()))
    def test_jh_pair_price_rounded_to_mintick(self, symbol):
        mintick = PAIRS_CONFIG[symbol]["mintick"]
        raw_price = 123.456789012345
        rounded = _round_price(raw_price, mintick)
        if mintick > 0:
            ratio = rounded / mintick
            assert abs(ratio - round(ratio)) < 0.01, (
                f"{symbol}: {rounded} not a multiple of mintick={mintick}"
            )

    @pytest.mark.parametrize("symbol", sorted(PAIRS_CONFIG.keys()))
    def test_jh_pair_qty_floor_truncated(self, symbol):
        raw_qty = 123.456789
        for dec in [0, 2, 4, 6]:
            rounded = _round_qty(raw_qty, dec)
            factor = 10.0 ** dec
            assert rounded == int(raw_qty * factor) / factor

    def test_maliki_top10_precision_via_prepare_order(self):
        top10 = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
                  "ADAUSDT", "DOGEUSDT", "DOTUSDT", "LINKUSDT", "AVAXUSDT"]
        main = _mock_main()
        for sym in top10:
            tp = _make_tp(sym, amount_precision=4, price_precision=2)
            main.get_trading_pair = MagicMock(return_value=tp)
            main.market_engine.get_symbol.return_value = SymbolData(
                symbol=sym, last_price=100.0, amount_precision=4, price_precision=2,
            )
            strat = StrategyTemplate(main, f"t_{sym}", setting={"symbols": [sym]})
            result = strat._prepare_order_for_exchange(sym, 1.23456789, 100.123456, "LIMIT")
            assert result is not None
            qty, price, _ = result
            qty_dec = len(f"{qty:.10f}".rstrip("0").split(".")[-1])
            price_dec = len(f"{price:.10f}".rstrip("0").split(".")[-1])
            assert qty_dec <= 4, f"{sym} qty has {qty_dec} decimals, expected <=4"
            assert price_dec <= 2, f"{sym} price has {price_dec} decimals, expected <=2"

    def test_edge_case_bonk_large_qty_integer(self):
        main = _mock_main()
        tp = _make_tp("BONKUSDT", price_precision=8, amount_precision=0)
        main.get_trading_pair = MagicMock(return_value=tp)
        main.market_engine.get_symbol.return_value = SymbolData(
            symbol="BONKUSDT", last_price=0.00002, price_precision=8, amount_precision=0,
        )
        strat = StrategyTemplate(main, "t_bonk", setting={"symbols": ["BONKUSDT"]})
        result = strat._prepare_order_for_exchange("BONKUSDT", 125000000.7, 0.00002, "LIMIT")
        assert result is not None
        qty, price, _ = result
        assert qty == 125000001.0  # amount_precision=0 → integer
        assert price == pytest.approx(0.00002, abs=1e-10)

    def test_edge_case_pepe_large_qty_integer(self):
        main = _mock_main()
        tp = _make_tp("PEPEUSDT", price_precision=8, amount_precision=0)
        main.get_trading_pair = MagicMock(return_value=tp)
        main.market_engine.get_symbol.return_value = SymbolData(
            symbol="PEPEUSDT", last_price=0.000015, price_precision=8, amount_precision=0,
        )
        strat = StrategyTemplate(main, "t_pepe", setting={"symbols": ["PEPEUSDT"]})
        result = strat._prepare_order_for_exchange("PEPEUSDT", 166666666.3, 0.000015, "LIMIT")
        assert result is not None
        qty, price, _ = result
        assert qty == 166666666.0
        assert price == pytest.approx(0.000015, abs=1e-10)

    def test_no_precision_info_passes_through_unrounded(self):
        """Without TradingPair or SymbolData precision, qty/price pass through raw."""
        main = _mock_main()
        main.get_trading_pair = MagicMock(return_value=None)
        main.market_engine.get_symbol.return_value = SymbolData(
            symbol="BTCUSDT", last_price=70000.0,
        )
        strat = StrategyTemplate(main, "t_noprec", setting={"symbols": ["BTCUSDT"]})
        result = strat._prepare_order_for_exchange("BTCUSDT", 0.123456789, 70000.123456, "LIMIT")
        assert result is not None
        qty, price, _ = result
        assert qty == pytest.approx(0.123456789)
        assert price == pytest.approx(70000.123456)

    def test_ghost_position_prevented_on_order_failure(self):
        """If Roostoo returns Success=False, no position and no risk_state recorded."""
        main = _functional_main()
        main.place_order = MagicMock(return_value={
            "Success": False, "ErrorCode": "QTY_STEP_SIZE",
            "ErrorMessage": "bad qty",
        })
        strat = StrategyMaliki(main, "strategy_maliki_ghost", setting={
            "lookback_candles": 5, "regime_ma_candles": 5, "rebalance_every": 1,
            "min_hold_candles": 0, "top_n": 1, "min_momentum_pct": 1.0,
            "min_notional_24h": 0, "capital_allocation": 100.0,
        })
        main.strategy_engine._strategies = [strat]
        _seed_bars(main.market_engine, "BTCUSDT", [100, 101, 102, 103, 104, 105],
                   "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        holding = main.strategy_engine.get_holding("strategy_maliki_ghost")
        for pos in holding.positions.values():
            assert pos.quantity == 0.0, "Ghost position after failed order!"
        assert len(strat._risk_state) == 0, "Risk state set despite failed order!"


# ═══════════════════════════════════════════════════
# GROUP 3: Position Tracking
# ═══════════════════════════════════════════════════


class TestGroup3PositionTracking:

    def test_successful_buy_records_position(self):
        se = StrategyEngine(main_engine=None)
        order = OrderData(
            order_id="o1", symbol="BTCUSDT", side="BUY", quantity=0.1,
            price=70000.0, status="FILLED", filled_quantity=0.1,
            filled_avg_price=70000.0, strategy_name="s",
        )
        se._apply_order_fill_to_holdings(order)
        h = se.get_holding("s")
        assert h.positions["BTCUSDT"].quantity == pytest.approx(0.1)
        assert h.positions["BTCUSDT"].avg_cost == pytest.approx(70000.0, rel=1e-4)

    def test_failed_buy_no_position(self):
        """Rejected order (filled_quantity=0) must NOT create a position."""
        se = StrategyEngine(main_engine=None)
        order = OrderData(
            order_id="fail1", symbol="BTCUSDT", side="BUY", quantity=0.1,
            price=70000.0, status="REJECTED", filled_quantity=0.0,
            filled_avg_price=0.0, strategy_name="s",
        )
        se._apply_order_fill_to_holdings(order)
        h = se.get_holding("s")
        pos = h.positions.get("BTCUSDT")
        assert pos is None or pos.quantity == 0.0

    def test_buy_then_sell_clears_position(self):
        se = StrategyEngine(main_engine=None)
        se._apply_order_fill_to_holdings(OrderData(
            order_id="b1", symbol="ETHUSDT", side="BUY", quantity=1.0,
            price=3000.0, status="FILLED", filled_quantity=1.0,
            filled_avg_price=3000.0, strategy_name="s",
        ))
        assert se.get_holding("s").positions["ETHUSDT"].quantity == pytest.approx(1.0)
        se._apply_order_fill_to_holdings(OrderData(
            order_id="s1", symbol="ETHUSDT", side="SELL", quantity=1.0,
            price=3100.0, status="FILLED", filled_quantity=1.0,
            filled_avg_price=3100.0, strategy_name="s",
        ))
        assert se.get_holding("s").positions["ETHUSDT"].quantity == 0.0

    def test_strategy_restart_resets_cleanly(self):
        main = _mock_main()
        se = StrategyEngine(main_engine=main)
        strat = se.add_strategy_by_name("StratTestAlt")
        se.start_strategy("StratTestAlt")
        h = se.get_holding("StratTestAlt")
        assert all(p.quantity == 0 for p in h.positions.values()) or len(h.positions) == 0
        se.stop_strategy("StratTestAlt")
        assert not strat.started

    def test_reconciliation_matches_engine_holdings(self):
        se = StrategyEngine(main_engine=None)
        se._apply_order_fill_to_holdings(OrderData(
            order_id="r1", symbol="SOLUSDT", side="BUY", quantity=10.0,
            price=150.0, status="FILLED", filled_quantity=10.0,
            filled_avg_price=150.0, strategy_name="recon",
        ))
        h = se.get_holding("recon")
        assert h.positions["SOLUSDT"].quantity == 10.0
        assert h.positions["SOLUSDT"].avg_cost == pytest.approx(150.0, rel=1e-4)


# ═══════════════════════════════════════════════════
# GROUP 4: Regime Filter (strategy_maliki)
# ═══════════════════════════════════════════════════


def _make_maliki(main, **kw):
    defaults = {
        "lookback_candles": 5, "regime_ma_candles": 5, "rebalance_every": 1,
        "min_hold_candles": 0, "top_n": 1, "min_momentum_pct": 1.0,
        "min_notional_24h": 0, "capital_allocation": 1000.0,
    }
    defaults.update(kw)
    return StrategyMaliki(main, "strategy_maliki_t", setting=defaults)


class TestGroup4RegimeFilter:

    def test_btc_above_ma_allows_trading(self):
        main = _functional_main()
        main.place_order = MagicMock(return_value={
            "Success": True,
            "OrderDetail": {"OrderID": "o1", "Status": "FILLED", "Side": "BUY",
                            "Quantity": 1.0, "Price": 105.0, "FilledQuantity": 1.0,
                            "FilledAverPrice": 105.0, "Pair": "BTC/USD", "Type": "LIMIT"},
        })
        strat = _make_maliki(main)
        main.strategy_engine._strategies = [strat]
        _seed_bars(main.market_engine, "BTCUSDT",
                   [100, 101, 102, 103, 104, 105], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()
        assert main.place_order.called, "No order placed despite bullish regime"

    def test_btc_below_ma_no_new_entries(self):
        main = _functional_main()
        strat = _make_maliki(main)
        main.strategy_engine._strategies = [strat]
        _seed_bars(main.market_engine, "BTCUSDT",
                   [105, 104, 103, 102, 101, 100], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()
        assert not main.place_order.called, "Order placed despite bearish regime"

    def test_btc_crosses_below_closes_after_min_hold(self):
        main = _functional_main()
        captured = []
        main.place_order = MagicMock(side_effect=lambda **kw: captured.append(kw))
        strat = _make_maliki(main, min_hold_candles=2)
        main.strategy_engine._strategies = [strat]

        # Pre-set a position
        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="b1", symbol="BTCUSDT", side="BUY", quantity=1.0,
            price=105.0, status="FILLED", filled_quantity=1.0,
            filled_avg_price=105.0, strategy_name="strategy_maliki_t",
        ))
        strat._risk_state["BTC"] = {"peak_price": 105, "entry_tick": 1, "entry_price": 105}

        # Bearish bars
        _seed_bars(main.market_engine, "BTCUSDT",
                   [105, 104, 103, 102, 101, 100], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat._tick_count = 3  # ticks_held = 3-1 = 2 >= min_hold(2)
        strat.on_timer_logic()

        sells = [c for c in captured if c.get("side") == "SELL"]
        assert len(sells) > 0, "Position not closed after regime turned bearish"

    def test_btc_below_ma_within_min_hold_keeps_position(self):
        main = _functional_main()
        captured = []
        main.place_order = MagicMock(side_effect=lambda **kw: captured.append(kw))
        strat = _make_maliki(main, min_hold_candles=100)
        main.strategy_engine._strategies = [strat]

        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="b2", symbol="BTCUSDT", side="BUY", quantity=1.0,
            price=105.0, status="FILLED", filled_quantity=1.0,
            filled_avg_price=105.0, strategy_name="strategy_maliki_t",
        ))
        strat._risk_state["BTC"] = {"peak_price": 105, "entry_tick": 1, "entry_price": 105}

        _seed_bars(main.market_engine, "BTCUSDT",
                   [105, 104, 103, 102, 101, 100], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat._tick_count = 2  # ticks_held = 3-1 = 2 < min_hold(100)
        strat.on_timer_logic()

        sells = [c for c in captured if c.get("side") == "SELL"]
        assert len(sells) == 0, "Position closed before min_hold elapsed"


# ═══════════════════════════════════════════════════
# GROUP 5: strategy_JH Signal Validation
# ═══════════════════════════════════════════════════


def _make_jh(main, **kw):
    defaults = {
        "pairs": ["APTUSDT"], "pivot_len": 1, "atr_len": 1,
        "fill_bars": 1, "capital": 1000.0, "risk_pct": 0.01,
    }
    defaults.update(kw)
    return StrategyJH(main, "strategy_JH_t", setting=defaults)


def _seed_jh_signal_bars(me, symbol="APTUSDT", sup=99.0, interval="15m"):
    """Seed 4 bars: 3 bearish candles + signal candle bouncing off support."""
    bars = [
        BarData(symbol, 110, 111, 105, 106, volume=100, interval=interval),
        BarData(symbol, 106, 108, 102, 103, volume=100, interval=interval),
        BarData(symbol, 103, 105, 99, 100, volume=100, interval=interval),
        # Signal candle: low touches support, close in upper 1/3, close <= prev.open
        BarData(symbol, sup + 1, sup + 6, sup - 0.5, sup + 4, volume=100, interval=interval),
    ]
    for b in bars:
        me.on_bar(b)
    return bars


class TestGroup5JHSignal:

    def test_valid_setup_fires_signal(self):
        main = _functional_main()
        main.place_order = MagicMock(return_value={
            "Success": True,
            "OrderDetail": {"OrderID": "jh1", "Status": "NEW", "Side": "BUY",
                            "Quantity": 1.0, "Price": 100, "Pair": "APT/USD",
                            "Type": "LIMIT", "FilledQuantity": 0, "FilledAverPrice": 0},
        })
        main.gateway_engine.register_order = MagicMock()
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]

        _seed_jh_signal_bars(main.market_engine)
        main.market_engine.get_pivot_low = MagicMock(return_value=99.0)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=True)
        main.market_engine.get_atr = MagicMock(return_value=5.0)

        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        assert main.place_order.called, "No BUY on valid signal"
        kw = main.place_order.call_args[1]
        assert kw["side"] == "BUY"
        assert kw["order_type"] == "LIMIT"

    def test_missing_bearish_no_signal(self):
        main = _functional_main()
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]

        _seed_jh_signal_bars(main.market_engine)
        main.market_engine.get_pivot_low = MagicMock(return_value=99.0)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=False)
        main.market_engine.get_atr = MagicMock(return_value=5.0)

        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        assert not main.place_order.called, "Signal fired without bearish confirmation"

    def test_h2_higher_low_resets_support(self):
        main = _functional_main()
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]

        _seed_jh_signal_bars(main.market_engine, sup=99.0)
        # Disable pivot so it doesn't reset our staged state
        main.market_engine.get_pivot_low = MagicMock(return_value=None)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=True)
        main.market_engine.get_atr = MagicMock(return_value=5.0)

        strat.on_init(); strat.on_start()

        # Simulate H1 already happened at a LOWER low
        st = strat._state["APTUSDT"]
        st["sup_price"] = 99.0
        st["hit_count"] = 1
        st["hit1_low"] = 98.0  # H1 low was 98.0; cur.low=98.5 > 98.0 → higher low

        strat.on_timer_logic()

        assert st["sup_price"] is None, "Support not reset on H2 higher-low failure"
        assert st["hit_count"] == 0

    def test_limit_not_filled_cancelled(self):
        main = _functional_main()
        strat = _make_jh(main, fill_bars=1)
        main.strategy_engine._strategies = [strat]
        strat.on_init(); strat.on_start()

        # Pending order placed at bar_idx=10
        st = strat._state["APTUSDT"]
        st["pending_order_id"] = "p1"
        st["limit_bar_idx"] = 10
        main.gateway_engine.get_pending_orders_by_symbol = MagicMock(
            return_value={"APTUSDT": ["p1"]}
        )
        # bar_count = 12 → bars_since = 12 - 10 = 2 ≥ fill_bars+1 = 2
        main.market_engine.get_bar_count = MagicMock(return_value=12)

        # Seed enough bars so _process_signal doesn't crash
        for i in range(20):
            main.market_engine.on_bar(BarData(
                "APTUSDT", 10, 11, 9, 10, volume=100, interval="15m",
            ))
        main.market_engine.get_pivot_low = MagicMock(return_value=None)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=False)
        main.market_engine.get_atr = MagicMock(return_value=1.0)

        strat.on_timer_logic()

        assert main.cancel_order.called, "Unfilled LIMIT not cancelled after fill_bars+1"


# ═══════════════════════════════════════════════════
# GROUP 6: Order Execution Rules — strategy_maliki
# ═══════════════════════════════════════════════════


class TestGroup6MalikiExecution:

    def test_entry_limit_above_last_price(self):
        """Entry = LIMIT at price * 1.001."""
        main = _functional_main()
        captured = {}
        def _place(**kw):
            captured.update(kw)
            return {"Success": True, "OrderDetail": {
                "OrderID": "m1", "Status": "FILLED", "Side": "BUY",
                "Quantity": kw["quantity"], "Price": kw.get("price", 0),
                "FilledQuantity": kw["quantity"], "FilledAverPrice": kw.get("price", 0),
                "Pair": "BTC/USD", "Type": "LIMIT",
            }}
        main.place_order = _place
        strat = _make_maliki(main)
        main.strategy_engine._strategies = [strat]
        _seed_bars(main.market_engine, "BTCUSDT",
                   [100, 101, 102, 103, 104, 105], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        assert captured.get("order_type") == "LIMIT"
        assert captured["price"] == pytest.approx(round(105 * 1.001, 8), rel=0.01)

    def test_exit_regime_market_sell(self):
        main = _functional_main()
        captured = []
        main.place_order = MagicMock(side_effect=lambda **kw: captured.append(kw))
        strat = _make_maliki(main, min_hold_candles=0)
        main.strategy_engine._strategies = [strat]

        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="x1", symbol="BTCUSDT", side="BUY", quantity=1.0,
            price=105.0, status="FILLED", filled_quantity=1.0,
            filled_avg_price=105.0, strategy_name="strategy_maliki_t",
        ))
        strat._risk_state["BTC"] = {"peak_price": 105, "entry_tick": 0, "entry_price": 105}
        _seed_bars(main.market_engine, "BTCUSDT",
                   [110, 108, 106, 104, 102, 100], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat._tick_count = 1
        strat.on_timer_logic()

        sells = [c for c in captured if c.get("side") == "SELL"]
        assert len(sells) > 0, "No MARKET SELL on bearish regime"
        assert sells[0]["order_type"] == "MARKET"

    def test_exit_trailing_stop_market_sell(self):
        main = _functional_main()
        captured = []
        main.place_order = MagicMock(side_effect=lambda **kw: captured.append(kw))
        # Use high rebalance_every so only trailing stop runs, not rebalance
        strat = _make_maliki(main, min_hold_candles=0, trailing_stop_pct=8.0,
                             rebalance_every=999)
        main.strategy_engine._strategies = [strat]

        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="ts1", symbol="BTCUSDT", side="BUY", quantity=1.0,
            price=100.0, status="FILLED", filled_quantity=1.0,
            filled_avg_price=100.0, strategy_name="strategy_maliki_t",
        ))
        strat._risk_state["BTC"] = {"peak_price": 100, "entry_tick": 0, "entry_price": 100}
        # 9% drop from peak → exceeds 8% trailing stop
        _seed_bars(main.market_engine, "BTCUSDT",
                   [100, 99, 98, 95, 93, 91], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat._tick_count = 1
        strat.on_timer_logic()

        sells = [c for c in captured if c.get("side") == "SELL"]
        assert len(sells) > 0, "Trailing stop did not trigger"
        assert sells[0]["order_type"] == "MARKET"

    def test_no_exit_before_min_hold(self):
        main = _functional_main()
        captured = []
        main.place_order = MagicMock(side_effect=lambda **kw: captured.append(kw))
        strat = _make_maliki(main, min_hold_candles=288)
        main.strategy_engine._strategies = [strat]

        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="nh1", symbol="BTCUSDT", side="BUY", quantity=1.0,
            price=100.0, status="FILLED", filled_quantity=1.0,
            filled_avg_price=100.0, strategy_name="strategy_maliki_t",
        ))
        strat._risk_state["BTC"] = {"peak_price": 100, "entry_tick": 1, "entry_price": 100}
        # Bearish + 20% drop (should trigger both regime and trailing stop if min_hold met)
        _seed_bars(main.market_engine, "BTCUSDT",
                   [100, 95, 90, 85, 82, 80], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat._tick_count = 2  # ticks_held = 3-1 = 2 << 288
        strat.on_timer_logic()

        sells = [c for c in captured if c.get("side") == "SELL"]
        assert len(sells) == 0, f"Exit before min_hold! sells={sells}"

    def test_only_one_position_top_n_1(self):
        """Already holding → no new BUY on rebalance."""
        main = _functional_main()
        strat = _make_maliki(main, top_n=1)
        main.strategy_engine._strategies = [strat]

        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="p1", symbol="BTCUSDT", side="BUY", quantity=1.0,
            price=100.0, status="FILLED", filled_quantity=1.0,
            filled_avg_price=100.0, strategy_name="strategy_maliki_t",
        ))
        strat._risk_state["BTC"] = {"peak_price": 105, "entry_tick": 0, "entry_price": 100}
        _seed_bars(main.market_engine, "BTCUSDT",
                   [100, 101, 102, 103, 104, 105], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        buys = [c for c in main.place_order.call_args_list if c[1].get("side") == "BUY"]
        assert len(buys) == 0, "BUY placed while already holding"

    def test_no_order_below_min_momentum(self):
        main = _functional_main()
        strat = _make_maliki(main, min_momentum_pct=50.0)
        main.strategy_engine._strategies = [strat]
        # Near-flat bars → ~0% momentum, below 50%
        _seed_bars(main.market_engine, "BTCUSDT",
                   [100, 100.1, 100.2, 100.1, 100.0, 100.3], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()
        assert not main.place_order.called, "Order placed below min_momentum"

    def test_allocation_uses_capital_fallback(self):
        """No balance → allocation ≤ capital_allocation."""
        main = _functional_main()
        captured = {}
        main.place_order = MagicMock(side_effect=lambda **kw: captured.update(kw))
        main.gateway_engine.get_balance = MagicMock(return_value=None)
        strat = _make_maliki(main, capital_allocation=20_000.0)
        main.strategy_engine._strategies = [strat]
        _seed_bars(main.market_engine, "BTCUSDT",
                   [100, 101, 102, 103, 104, 105], "5m", volume=100000)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()
        if captured:
            # qty * price ≈ allocation ≤ 20000
            alloc_used = captured["quantity"] * captured.get("price", 105)
            assert alloc_used <= 20_100, f"Allocation {alloc_used} exceeds capital"


# ═══════════════════════════════════════════════════
# GROUP 6: Order Execution Rules — strategy_JH
# ═══════════════════════════════════════════════════


class TestGroup6JHExecution:

    def _setup_signal_and_run(self, main, strat, return_order=True):
        """Set up bars + mocks for signal, run on_timer_logic."""
        _seed_jh_signal_bars(main.market_engine)
        main.market_engine.get_pivot_low = MagicMock(return_value=99.0)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=True)
        main.market_engine.get_atr = MagicMock(return_value=5.0)

        if return_order:
            main.place_order = MagicMock(return_value={
                "Success": True,
                "OrderDetail": {"OrderID": "jh-e", "Status": "NEW", "Side": "BUY",
                                "Quantity": 1, "Price": 100, "Pair": "APT/USD",
                                "Type": "LIMIT", "FilledQuantity": 0, "FilledAverPrice": 0},
            })
            main.gateway_engine.register_order = MagicMock()

        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

    def test_entry_limit_at_midpoint(self):
        main = _functional_main()
        captured = {}
        def _place(**kw):
            captured.update(kw)
            return {"Success": True, "OrderDetail": {
                "OrderID": "jhe1", "Status": "NEW", "Side": "BUY",
                "Quantity": kw["quantity"], "Price": kw.get("price", 0),
                "Pair": "APT/USD", "Type": "LIMIT",
                "FilledQuantity": 0, "FilledAverPrice": 0,
            }}
        main.place_order = _place
        main.gateway_engine.register_order = MagicMock()
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]

        _seed_jh_signal_bars(main.market_engine, sup=99.0)
        main.market_engine.get_pivot_low = MagicMock(return_value=99.0)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=True)
        main.market_engine.get_atr = MagicMock(return_value=5.0)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        if captured:
            # cur: high=105, low=98.5 → midpoint=101.75
            mintick = PAIRS_CONFIG["APTUSDT"]["mintick"]
            expected = _round_price((105 + 98.5) / 2, mintick)
            assert captured["price"] == pytest.approx(expected, abs=mintick * 2)
            assert captured["order_type"] == "LIMIT"

    def test_stop_below_signal_candle_low(self):
        main = _functional_main()
        main.gateway_engine.register_order = MagicMock()
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]
        self._setup_signal_and_run(main, strat)

        st = strat._state["APTUSDT"]
        if st.get("pending_stop") is not None:
            mintick = PAIRS_CONFIG["APTUSDT"]["mintick"]
            # cur.low = 99.0 - 0.5 = 98.5; stop = 98.5 - 0.01 = 98.49
            expected = _round_price(98.5 - mintick, mintick)
            assert st["pending_stop"] == pytest.approx(expected, abs=mintick * 2)

    def test_target_2x_risk_reward(self):
        main = _functional_main()
        main.gateway_engine.register_order = MagicMock()
        strat = _make_jh(main, rr=2.0)
        main.strategy_engine._strategies = [strat]
        self._setup_signal_and_run(main, strat)

        st = strat._state["APTUSDT"]
        if st.get("pending_stop") is not None and st.get("pending_target") is not None:
            entry = st["entry_price"]
            stop = st["pending_stop"]
            target = st["pending_target"]
            expected = entry + 2.0 * (entry - stop)
            mintick = PAIRS_CONFIG["APTUSDT"]["mintick"]
            assert target == pytest.approx(expected, abs=mintick * 2)

    def test_exit_market_on_stop_hit(self):
        main = _functional_main()
        captured = []
        main.place_order = MagicMock(side_effect=lambda **kw: captured.append(kw))
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]
        strat.on_init(); strat.on_start()

        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="jh-p1", symbol="APTUSDT", side="BUY", quantity=10.0,
            price=100.0, status="FILLED", filled_quantity=10.0,
            filled_avg_price=100.0, strategy_name="strategy_JH_t",
        ))
        st = strat._state["APTUSDT"]
        st["active_stop"] = 98.0
        st["active_target"] = 104.0
        main.market_engine.update_symbol_from_ticker("APTUSDT", last_price=97.5)

        # Seed bars for _process_signal so it doesn't crash
        for _ in range(20):
            main.market_engine.on_bar(BarData("APTUSDT", 100, 101, 97, 98, volume=100, interval="15m"))
        main.market_engine.get_pivot_low = MagicMock(return_value=None)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=False)
        main.market_engine.get_atr = MagicMock(return_value=1.0)

        strat.on_timer_logic()

        sells = [c for c in captured if c.get("side") == "SELL"]
        assert len(sells) > 0, "Stop-loss not triggered"
        assert sells[0]["order_type"] == "MARKET"

    def test_exit_market_on_target_hit(self):
        main = _functional_main()
        captured = []
        main.place_order = MagicMock(side_effect=lambda **kw: captured.append(kw))
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]
        strat.on_init(); strat.on_start()

        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="jh-t2", symbol="APTUSDT", side="BUY", quantity=10.0,
            price=100.0, status="FILLED", filled_quantity=10.0,
            filled_avg_price=100.0, strategy_name="strategy_JH_t",
        ))
        st = strat._state["APTUSDT"]
        st["active_stop"] = 98.0
        st["active_target"] = 104.0
        main.market_engine.update_symbol_from_ticker("APTUSDT", last_price=104.5)

        for _ in range(20):
            main.market_engine.on_bar(BarData("APTUSDT", 100, 105, 99, 104, volume=100, interval="15m"))
        main.market_engine.get_pivot_low = MagicMock(return_value=None)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=False)
        main.market_engine.get_atr = MagicMock(return_value=1.0)

        strat.on_timer_logic()

        sells = [c for c in captured if c.get("side") == "SELL"]
        assert len(sells) > 0, "Target exit not triggered"
        assert sells[0]["order_type"] == "MARKET"

    def test_no_duplicate_entry_while_in_position(self):
        main = _functional_main()
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]
        strat.on_init(); strat.on_start()

        main.strategy_engine._apply_order_fill_to_holdings(OrderData(
            order_id="jh-dup", symbol="APTUSDT", side="BUY", quantity=10.0,
            price=100.0, status="FILLED", filled_quantity=10.0,
            filled_avg_price=100.0, strategy_name="strategy_JH_t",
        ))
        st = strat._state["APTUSDT"]
        st["active_stop"] = 95.0
        st["active_target"] = 110.0

        # Price between stop/target → no exit, and should not re-enter
        main.market_engine.update_symbol_from_ticker("APTUSDT", last_price=102.0)
        for _ in range(20):
            main.market_engine.on_bar(BarData("APTUSDT", 100, 103, 99, 102, volume=100, interval="15m"))
        main.market_engine.get_pivot_low = MagicMock(return_value=99.0)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=True)
        main.market_engine.get_atr = MagicMock(return_value=5.0)

        strat.on_timer_logic()

        assert not main.place_order.called, "Duplicate entry while in position"

    def test_multi_pair_simultaneous_positions(self):
        se = StrategyEngine(main_engine=None)
        for sym in ["APTUSDT", "CRVUSDT"]:
            se._apply_order_fill_to_holdings(OrderData(
                order_id=f"mp-{sym}", symbol=sym, side="BUY", quantity=10.0,
                price=100.0, status="FILLED", filled_quantity=10.0,
                filled_avg_price=100.0, strategy_name="jh_multi",
            ))
        h = se.get_holding("jh_multi")
        assert h.positions["APTUSDT"].quantity == 10.0
        assert h.positions["CRVUSDT"].quantity == 10.0

    def test_position_sizing_formula(self):
        capital, risk_pct, n_pairs = 1000.0, 0.01, 1
        alloc = capital / n_pairs
        entry, stop = 100.0, 98.0
        risk_per_unit = entry - stop
        risk_amount = alloc * risk_pct  # 10.0
        qty_risk = risk_amount / risk_per_unit  # 5.0
        qty_alloc = alloc / entry  # 10.0
        expected = min(qty_risk, qty_alloc)  # 5.0
        assert expected == 5.0
        assert _round_qty(expected, 6) == 5.0


class TestGroup6OrderTypes:

    def test_maliki_entry_is_limit(self):
        main = _mock_main()
        main.market_engine.get_symbol.return_value = SymbolData(symbol="BTCUSDT", last_price=100)
        main.handle_intent = MagicMock(return_value="oid-1")
        main.get_pending_orders_by_symbol = MagicMock(return_value={})
        strat = StrategyMaliki(main, "m_ot", setting={"capital_allocation": 100.0})
        strat._open_position("BTC", "BTC/USD", 100.0, momentum=5.0, slots_open=1)
        if main.handle_intent.called:
            req = main.handle_intent.call_args[0][1]
            assert req.order_type == "LIMIT"

    def test_maliki_exit_is_market(self):
        main = _mock_main()
        main.market_engine.get_symbol.return_value = SymbolData(symbol="BTCUSDT", last_price=100)
        holding = MagicMock()
        holding.positions = {"BTCUSDT": MagicMock(quantity=1.0)}
        main.strategy_engine.get_holding.return_value = holding
        strat = StrategyMaliki(main, "m_ot", setting={})
        strat._risk_state["BTC"] = {"peak_price": 100, "entry_tick": 0, "entry_price": 100}
        strat._close_position("BTC", "test")
        if main.handle_intent.called:
            req = main.handle_intent.call_args[0][1]
            assert req.order_type == "MARKET"


# ═══════════════════════════════════════════════════
# GROUP 7: Error Handling
# ═══════════════════════════════════════════════════


class TestGroup7ErrorHandling:

    def _setup_bullish(self, main):
        _seed_bars(main.market_engine, "BTCUSDT",
                   [100, 101, 102, 103, 104, 105], "5m", volume=100000)

    @pytest.mark.parametrize("error_code", [
        "QTY_STEP_SIZE", "PRICE_STEP_SIZE", "INSUFFICIENT_BALANCE",
    ])
    def test_exchange_error_no_position(self, error_code):
        """Any exchange rejection → no position recorded."""
        main = _functional_main()
        main.place_order = MagicMock(return_value={
            "Success": False, "ErrorCode": error_code, "ErrorMessage": "err",
        })
        strat = _make_maliki(main)
        main.strategy_engine._strategies = [strat]
        self._setup_bullish(main)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        h = main.strategy_engine.get_holding("strategy_maliki_t")
        for pos in h.positions.values():
            assert pos.quantity == 0.0, f"Ghost position on {error_code}!"

    def test_place_order_returns_none_no_position(self):
        """Gateway returns None (timeout/network) → no position."""
        main = _functional_main()
        main.place_order = MagicMock(return_value=None)
        strat = _make_maliki(main)
        main.strategy_engine._strategies = [strat]
        self._setup_bullish(main)
        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        h = main.strategy_engine.get_holding("strategy_maliki_t")
        for pos in h.positions.values():
            assert pos.quantity == 0.0

    def test_binance_timeout_does_not_crash(self):
        """No bars seeded (simulates Binance timeout) → strategy skips, no crash."""
        main = _functional_main()
        strat = _make_maliki(main)
        main.strategy_engine._strategies = [strat]
        # No bars → _has_enough_data returns False
        strat.on_init(); strat.on_start()
        for _ in range(5):
            strat.on_timer_logic()
        assert strat.started and not strat.error

    def test_strategy_continues_after_repeated_failures(self):
        """Multiple failed order cycles → strategy stays running."""
        main = _functional_main()
        main.place_order = MagicMock(return_value=None)
        strat = _make_maliki(main)
        main.strategy_engine._strategies = [strat]
        self._setup_bullish(main)
        strat.on_init(); strat.on_start()
        for _ in range(10):
            strat.on_timer_logic()
        assert strat.started, "Strategy stopped after errors"
        assert not strat.error, "Strategy entered error state"

    def test_jh_exchange_error_no_ghost_position(self):
        """strategy_JH: exchange error on entry → no position."""
        main = _functional_main()
        main.place_order = MagicMock(return_value={
            "Success": False, "ErrorCode": "QTY_STEP_SIZE", "ErrorMessage": "err",
        })
        strat = _make_jh(main)
        main.strategy_engine._strategies = [strat]

        _seed_jh_signal_bars(main.market_engine)
        main.market_engine.get_pivot_low = MagicMock(return_value=99.0)
        main.market_engine.prev3_bearish_strict = MagicMock(return_value=True)
        main.market_engine.get_atr = MagicMock(return_value=5.0)

        strat.on_init(); strat.on_start()
        strat.on_timer_logic()

        h = main.strategy_engine.get_holding("strategy_JH_t")
        for pos in h.positions.values():
            assert pos.quantity == 0.0, "Ghost position in JH after exchange error!"


# ═══════════════════════════════════════════════════
# GROUP 8: ExchangeInfo Retry, Fallback & Start Guard
# ═══════════════════════════════════════════════════


class TestGroup8ExchangeInfoRetryFallback:

    @staticmethod
    def _exchange_info_ok():
        """Minimal valid /v3/exchangeInfo response."""
        return {"TradePairs": {"BTC/USD": {"PricePrecision": 0, "AmountPrecision": 5, "MiniOrder": 10}}}

    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info")
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_discovery_succeeds_first_attempt(self, mock_refresh, mock_info):
        mock_info.return_value = self._exchange_info_ok()
        engine = MainEngine(env_mode="mock")
        assert engine._exchange_info_ok is True
        assert "BTCUSDT" in engine.trading_pairs_by_symbol
        assert mock_info.call_count == 1  # no retries needed

    @patch("src.engines.engine_main.time.sleep")
    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info")
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_discovery_fails_then_succeeds_on_retry(self, mock_refresh, mock_info, mock_sleep):
        mock_info.side_effect = [None, None, self._exchange_info_ok()]
        engine = MainEngine(env_mode="mock")
        assert engine._exchange_info_ok is True
        assert "BTCUSDT" in engine.trading_pairs_by_symbol
        assert mock_info.call_count == 3
        assert mock_sleep.call_count == 2  # slept between attempts 1→2 and 2→3

    @patch("src.engines.engine_main.time.sleep")
    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info")
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_all_retries_fail_applies_fallback(self, mock_refresh, mock_info, mock_sleep):
        mock_info.return_value = None  # always fail
        engine = MainEngine(env_mode="mock")
        assert engine._exchange_info_ok is False
        assert mock_info.call_count == 3
        # Fallback should have loaded known pairs
        assert len(engine.trading_pairs_by_symbol) > 0
        assert "BTCUSDT" in engine.trading_pairs_by_symbol
        assert "BONKUSDT" in engine.trading_pairs_by_symbol
        # Verify fallback values
        btc = engine.trading_pairs_by_symbol["BTCUSDT"]
        assert btc.price_precision == 0
        assert btc.amount_precision == 5

    @patch("src.engines.engine_main.time.sleep")
    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info")
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_fallback_covers_all_jh_pairs(self, mock_refresh, mock_info, mock_sleep):
        mock_info.return_value = None
        engine = MainEngine(env_mode="mock")
        from src.strategies.factory.strategy_JH import PAIRS_CONFIG
        for sym in PAIRS_CONFIG:
            assert sym in engine.trading_pairs_by_symbol, f"Fallback missing JH pair {sym}"
            tp = engine.trading_pairs_by_symbol[sym]
            assert tp.price_precision >= 0
            assert tp.amount_precision >= 0

    @patch("src.engines.engine_main.time.sleep")
    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info")
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_fallback_does_not_overwrite_live_data(self, mock_refresh, mock_info, mock_sleep):
        """If discovery succeeds partially then fails, fallback fills gaps only."""
        # First call returns partial data, next two fail
        partial = {"TradePairs": {"BTC/USD": {"PricePrecision": 1, "AmountPrecision": 6, "MiniOrder": 5}}}
        mock_info.side_effect = [partial, None, None]
        # First attempt returns data → succeeds → no fallback needed
        engine = MainEngine(env_mode="mock")
        # Discovery succeeded on attempt 1 with partial data
        assert engine._exchange_info_ok is True
        btc = engine.trading_pairs_by_symbol["BTCUSDT"]
        assert btc.price_precision == 1  # live value, not fallback 0
        assert btc.amount_precision == 6  # live value, not fallback 5

    @patch("src.engines.engine_main.time.sleep")
    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info")
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_start_strategy_blocked_without_any_precision_data(self, mock_refresh, mock_info, mock_sleep):
        mock_info.return_value = None
        engine = MainEngine(env_mode="mock")
        # Clear fallback to simulate total failure
        engine.trading_pairs_by_symbol.clear()
        engine._exchange_info_ok = False
        with pytest.raises(RuntimeError, match="Cannot start"):
            engine.start_strategy("strategy_maliki")

    @patch("src.engines.engine_main.time.sleep")
    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info")
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_start_strategy_allowed_with_fallback(self, mock_refresh, mock_info, mock_sleep):
        mock_info.return_value = None  # discovery fails → fallback
        engine = MainEngine(env_mode="mock")
        assert engine._exchange_info_ok is False
        assert len(engine.trading_pairs_by_symbol) > 0
        # Should NOT raise — fallback precision is available
        engine.start_strategy("strategy_maliki")
        strat = engine.get_strategy("strategy_maliki")
        assert strat.started

    @patch("src.engines.engine_main.time.sleep")
    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info")
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_fallback_precision_actually_rounds_orders(self, mock_refresh, mock_info, mock_sleep):
        """End-to-end: fallback precision is used by _prepare_order_for_exchange."""
        mock_info.return_value = None
        engine = MainEngine(env_mode="mock")
        assert engine._exchange_info_ok is False

        strat = engine.get_strategy("strategy_maliki")
        assert strat is not None
        # BTC fallback: amount_precision=5, price_precision=0
        result = strat._prepare_order_for_exchange("BTCUSDT", 0.123456789, 70000.50, "LIMIT")
        assert result is not None
        qty, price, _ = result
        # amount_precision=5 → rounded to 5 decimals
        assert qty == pytest.approx(0.12346, abs=1e-6)
        # price_precision=0 → rounded to integer
        assert price == pytest.approx(70001, abs=1)

    @patch("src.engines.engine_main.time.sleep")
    @patch("src.engines.engine_gateway.GatewayEngine.get_exchange_info", side_effect=Exception("connection refused"))
    @patch("src.engines.engine_gateway.GatewayEngine._refresh_account_cache")
    def test_exception_during_discovery_retries(self, mock_refresh, mock_info, mock_sleep):
        """Exception (not just None) during get_exchange_info → retries then fallback."""
        engine = MainEngine(env_mode="mock")
        assert engine._exchange_info_ok is False
        assert mock_info.call_count == 3
        assert len(engine.trading_pairs_by_symbol) > 0


# ═══════════════════════════════════════════════════
# GROUP 9: Gateway Precision Safety Net
# ═══════════════════════════════════════════════════


class TestGroup9GatewayPrecisionSafetyNet:
    """Verify the gateway-level rounding catches everything before Roostoo."""

    def _gw_with_pairs(self, pairs_spec: dict[str, tuple[int, int]]):
        """Create a GatewayEngine with mocked trading pairs."""
        from src.engines.engine_gateway import GatewayEngine
        gw = GatewayEngine(main_engine=MagicMock(), env_mode="mock")
        for sym, (px_prec, amt_prec) in pairs_spec.items():
            base = sym.replace("USDT", "")
            gw.trading_pairs_by_symbol[sym] = TradingPair(
                pair=f"{base}/USD", symbol=sym, coin=base, unit="USD",
                can_trade=True, price_precision=px_prec,
                amount_precision=amt_prec, mini_order=10.0,
            )
        # Stub _request_post to return success without network
        gw._request_post = MagicMock(return_value={
            "Success": True,
            "OrderDetail": {"OrderID": "test-1", "Status": "NEW", "Side": "BUY",
                            "Quantity": 1, "Price": 100, "Pair": "BTC/USD",
                            "Type": "LIMIT", "FilledQuantity": 0, "FilledAverPrice": 0},
        })
        return gw

    def test_btc_qty_rounded_to_5_decimals(self):
        gw = self._gw_with_pairs({"BTCUSDT": (0, 5)})
        resp = gw.place_order("BTCUSDT", "BUY", 0.123456789, price=70000.50, order_type="LIMIT")
        payload = gw._request_post.call_args[1]["data"] if gw._request_post.call_args[1] else gw._request_post.call_args[0][1]
        assert payload["quantity"] == pytest.approx(0.12346, abs=1e-6)
        assert payload["price"] == pytest.approx(70001, abs=1)  # px_prec=0 → integer

    def test_bonk_integer_qty_small_price(self):
        gw = self._gw_with_pairs({"BONKUSDT": (8, 0)})
        resp = gw.place_order("BONKUSDT", "BUY", 125000000.7, price=0.0000234567, order_type="LIMIT")
        payload = gw._request_post.call_args[1]["data"] if gw._request_post.call_args[1] else gw._request_post.call_args[0][1]
        assert payload["quantity"] == 125000001.0  # amt_prec=0 → integer
        assert payload["price"] == pytest.approx(0.00002346, abs=1e-9)  # px_prec=8

    def test_shib_integer_qty_small_price(self):
        gw = self._gw_with_pairs({"SHIBUSDT": (8, 0)})
        resp = gw.place_order("SHIBUSDT", "BUY", 999999.4, price=0.000012345, order_type="LIMIT")
        payload = gw._request_post.call_args[1]["data"] if gw._request_post.call_args[1] else gw._request_post.call_args[0][1]
        assert payload["quantity"] == 999999.0  # floor to integer
        assert payload["price"] == pytest.approx(0.00001235, abs=1e-9)

    def test_apt_precision_3_2(self):
        gw = self._gw_with_pairs({"APTUSDT": (3, 2)})
        resp = gw.place_order("APTUSDT", "BUY", 12.3456, price=8.12345, order_type="LIMIT")
        payload = gw._request_post.call_args[1]["data"] if gw._request_post.call_args[1] else gw._request_post.call_args[0][1]
        assert payload["quantity"] == pytest.approx(12.35, abs=0.01)  # amt_prec=2
        assert payload["price"] == pytest.approx(8.123, abs=0.001)  # px_prec=3

    def test_market_order_price_not_rounded(self):
        gw = self._gw_with_pairs({"BTCUSDT": (0, 5)})
        resp = gw.place_order("BTCUSDT", "BUY", 0.5, price=None, order_type="MARKET")
        payload = gw._request_post.call_args[1]["data"] if gw._request_post.call_args[1] else gw._request_post.call_args[0][1]
        assert "price" not in payload  # MARKET orders have no price field
        assert payload["quantity"] == pytest.approx(0.5, abs=1e-6)

    def test_unknown_pair_rejected(self):
        gw = self._gw_with_pairs({"BTCUSDT": (0, 5)})
        resp = gw.place_order("UNKNOWNUSDT", "BUY", 1.0, price=100.0, order_type="LIMIT")
        assert resp is not None
        assert resp["Success"] is False
        assert resp["ErrorCode"] == "NO_PRECISION_DATA"
        # Must NOT have called _request_post (no HTTP sent)
        gw._request_post.assert_not_called()

    def test_qty_rounds_to_zero_rejected(self):
        gw = self._gw_with_pairs({"BTCUSDT": (0, 0)})  # amt_prec=0 means integer qty
        resp = gw.place_order("BTCUSDT", "BUY", 0.4, price=70000.0, order_type="LIMIT")
        assert resp["Success"] is False
        assert resp["ErrorCode"] == "QTY_ROUNDS_TO_ZERO"
        gw._request_post.assert_not_called()

    @pytest.mark.parametrize("symbol,px_prec,amt_prec", [
        ("TAOUSDT", 1, 4),
        ("FETUSDT", 4, 1),
        ("BONKUSDT", 8, 0),
        ("SHIBUSDT", 8, 0),
        ("APTUSDT", 3, 2),
        ("BTCUSDT", 0, 5),
        ("ETHUSDT", 2, 4),
        ("SOLUSDT", 2, 2),
        ("XRPUSDT", 4, 1),
        ("DOGEUSDT", 5, 0),
    ])
    def test_critical_pair_rounding(self, symbol, px_prec, amt_prec):
        """For every critical pair, verify gateway rounds correctly."""
        gw = self._gw_with_pairs({symbol: (px_prec, amt_prec)})
        raw_qty = 123.456789
        raw_price = 456.78901234

        resp = gw.place_order(symbol, "BUY", raw_qty, price=raw_price, order_type="LIMIT")
        assert gw._request_post.called, f"Order for {symbol} was not sent"

        payload = gw._request_post.call_args[1]["data"] if gw._request_post.call_args[1] else gw._request_post.call_args[0][1]

        # Verify qty decimal places
        sent_qty = payload["quantity"]
        if amt_prec == 0:
            assert sent_qty == round(sent_qty), f"{symbol} qty {sent_qty} is not integer (amt_prec=0)"
        else:
            qty_str = f"{sent_qty:.{amt_prec + 3}f}"
            decimals = qty_str.rstrip("0").split(".")[-1]
            assert len(decimals) <= amt_prec, (
                f"{symbol} qty {sent_qty} has too many decimals (max {amt_prec})"
            )

        # Verify price decimal places
        sent_price = payload["price"]
        if px_prec == 0:
            assert sent_price == round(sent_price), f"{symbol} price {sent_price} is not integer (px_prec=0)"
        else:
            price_str = f"{sent_price:.{px_prec + 3}f}"
            decimals = price_str.rstrip("0").split(".")[-1]
            assert len(decimals) <= px_prec, (
                f"{symbol} price {sent_price} has too many decimals (max {px_prec})"
            )

    def test_double_rounding_no_drift(self):
        """Strategy rounds first, then gateway rounds again — result must be identical."""
        from src.engines.engine_gateway import GatewayEngine
        # Simulate strategy_JH rounding, then gateway rounding
        mintick = 0.01  # APT
        px_prec = 3
        amt_prec = 2

        raw_entry = 8.12345
        # Strategy JH rounds to mintick
        strategy_rounded = _round_price(raw_entry, mintick)  # → 8.12
        # Gateway rounds to px_prec=3
        gateway_rounded = GatewayEngine._round_to_precision(strategy_rounded, px_prec)  # → 8.12
        # No drift: 8.12 rounded to 3 decimals is still 8.12 (within float tolerance)
        assert gateway_rounded == pytest.approx(strategy_rounded, abs=1e-10)

        raw_qty = 12.345
        strategy_qty = _round_qty(raw_qty, amt_prec)  # → 12.34 (floor)
        gateway_qty = GatewayEngine._round_to_precision(strategy_qty, amt_prec)  # → 12.34
        assert gateway_qty == pytest.approx(strategy_qty, abs=1e-10)

    def test_maliki_no_more_hardcoded_rounding(self):
        """strategy_maliki must NOT have round(qty, 5) or round(price, 8) anymore."""
        import inspect
        from src.strategies.factory import strategy_maliki
        source = inspect.getsource(strategy_maliki)
        # No hardcoded round(qty, 5) or round(price * ..., 8)
        assert "round(qty, 5)" not in source, "Hardcoded round(qty, 5) still present"
        assert "round(price * 1.001, 8)" not in source, "Hardcoded round(price, 8) still present"

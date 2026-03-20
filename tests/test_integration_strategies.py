"""
Integration tests for strategies interacting with MarketEngine and Binance.

These tests are separated from unit tests so we can:
- Run cache-level integration cheaply.
- Optionally run live Binance history tests behind an env flag.
"""

import os
from datetime import datetime, timezone

import pytest
from unittest.mock import MagicMock

from src.strategies.factory import StrategyJH, StrategyMaliki


class TestStrategyHistoryIntegration:
  """Integration-style checks for strategy ↔ MarketEngine behavior."""

  @pytest.mark.skipif(
      os.getenv("LIVE_BINANCE_TESTS") != "1",
      reason="Set LIVE_BINANCE_TESTS=1 to run live Binance integration test",
  )
  def test_strategy_maliki_uses_real_binance_history(self):
      """
      StrategyMaliki.on_init() should cause MarketEngine.ensure_history()
      to fetch real BTCUSDT klines from Binance when LIVE_BINANCE_TESTS=1.
      """
      from src.engines.engine_market import MarketEngine

      class DummyMain:
          pass

      main = DummyMain()
      main.market_engine = MarketEngine(main_engine=None)
      main.gateway_engine = MagicMock()
      main.put_event = MagicMock()

      strat = StrategyMaliki(main, "strategy_maliki_integration", setting={})
      strat.on_init()

      me = main.market_engine
      bars = me.get_last_bars("BTCUSDT", strat.regime_ma_candles, strat.interval.binance)
      assert len(bars) >= strat.regime_ma_candles, (
          f"Expected at least {strat.regime_ma_candles} BTCUSDT bars, got {len(bars)}"
      )


class TestStrategyCacheIntegration:
  """Checks that strategies can read symbols from MarketEngine's cached data."""

  def test_strategy_maliki_reads_symbol_from_market_cache(self):
      """StrategyMaliki.get_symbol should return SymbolData from MarketEngine cache."""
      from src.engines.engine_market import MarketEngine
      from src.utilities.object import BarData

      class DummyMain:
          pass

      main = DummyMain()
      main.market_engine = MarketEngine(main_engine=None)
      main.gateway_engine = MagicMock()
      main.put_event = MagicMock()

      me = main.market_engine
      bar = BarData(
          symbol="BTCUSDT",
          open=100.0,
          high=101.0,
          low=99.0,
          close=100.5,
          volume=1.0,
          ts=datetime.now(timezone.utc),
          interval="5m",
      )
      # Use on_bar so SymbolData cache is updated consistently.
      me.on_bar(bar)

      strat = StrategyMaliki(main, "strategy_maliki_cache_test", setting={})
      sym_data = strat.get_symbol("BTCUSDT")
      assert sym_data is not None
      assert sym_data.last_price == pytest.approx(100.5)

  def test_strategy_jh_reads_symbol_from_market_cache(self):
      """StrategyJH.get_symbol should return SymbolData from MarketEngine cache."""
      from src.engines.engine_market import MarketEngine
      from src.utilities.object import BarData

      class DummyMain:
          pass

      main = DummyMain()
      main.market_engine = MarketEngine(main_engine=None)
      main.gateway_engine = MagicMock()
      main.put_event = MagicMock()

      me = main.market_engine
      bar = BarData(
          symbol="APTUSDT",
          open=10.0,
          high=10.5,
          low=9.5,
          close=10.25,
          volume=5.0,
          ts=datetime.now(timezone.utc),
          interval="15m",
      )
      me.on_bar(bar)

      strat = StrategyJH(main, "strategy_JH_cache_test", setting={})
      sym_data = strat.get_symbol("APTUSDT")
      assert sym_data is not None
      assert sym_data.last_price == pytest.approx(10.25)


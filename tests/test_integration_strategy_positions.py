"""
Integration tests: strategy signals -> order fills -> StrategyEngine holdings updates.

These tests use real GatewayEngine/StrategyEngine plumbing with mocked market/API data.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from dotenv import load_dotenv

from src.engines.engine_event import EventEngine
from src.engines.engine_gateway import GatewayEngine
from src.engines.engine_market import MarketEngine
from src.engines.engine_strategy import StrategyEngine
from src.strategies.factory import strategy_maliki as strategy_maliki_module
from src.strategies.factory import StrategyJH, StrategyMaliki
from src.utilities.object import BarData, SymbolData


# Load project-root .env for this integration module only.
# keep override=False so exported shell vars still win.
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=_ROOT / ".env", override=False)


def _make_main_with_real_gateway():
    main = SimpleNamespace()
    main.active_pairs = []
    main.trading_pairs = []
    main.trading_pairs_by_symbol = {}
    main.market_engine = MarketEngine(main_engine=None)
    main.put_event = MagicMock()
    main.strategy_engine = StrategyEngine(main_engine=main)
    main.risk_engine = MagicMock()
    main.event_engine = EventEngine(main_engine=main)
    main.gateway_engine = GatewayEngine(main_engine=main, env_mode="mock")
    main.gateway_engine.trading_pairs = []

    # Avoid real HTTP in sandboxed test runs: mock the gateway write-path to
    # always return a FILLED order detail so strategies register fills
    # immediately and integration tests can assert on order_map/holdings.
    #
    # We keep the mocked response shaped like Roostoo's /v3/place_order:
    # { "Success": True, "OrderDetail": { ... } }
    place_counter = {"n": 0}

    def _mock_request_post(path, data, signed):  # type: ignore[no-untyped-def]
        if path != "/v3/place_order":
            return {"Success": True}
        place_counter["n"] += 1
        oid = f"int-{place_counter['n']}"
        pair = data.get("pair", "")
        side = data.get("side", "")
        qty = float(data.get("quantity", 0.0) or 0.0)
        order_type = data.get("type", "LIMIT")
        px = float(data.get("price", 0.0) or 0.0) if order_type == "LIMIT" else 0.0
        return {
            "Success": True,
            "OrderDetail": {
                "OrderID": oid,
                "Status": "FILLED",
                "Side": side,
                "Quantity": qty,
                "Price": px,
                "Pair": pair,
                "Type": order_type,
                "FilledQuantity": qty,
                "FilledAverPrice": px,
            },
        }

    main.gateway_engine._request_post = _mock_request_post  # type: ignore[method-assign]

    # Populate gateway precision data from exchangeInfo so the safety net
    # doesn't reject orders for unknown pairs.
    try:
        info = main.gateway_engine.get_exchange_info()
        if isinstance(info, dict) and isinstance(info.get("TradePairs"), dict):
            from src.utilities.object import TradingPair as _TP
            for pair_key, spec in info["TradePairs"].items():
                symbol = GatewayEngine._from_roostoo_pair(str(pair_key))
                if symbol:
                    tp = _TP.from_exchange_entry(str(pair_key), spec, symbol=symbol)
                    main.gateway_engine.trading_pairs_by_symbol[symbol] = tp
                    main.trading_pairs_by_symbol[symbol] = tp
    except Exception:
        pass

    # If exchangeInfo failed, load fallback precision for test pairs.
    if not main.gateway_engine.trading_pairs_by_symbol:
        from src.engines.engine_main import _FALLBACK_PAIR_RULES
        from src.utilities.object import TradingPair as _TP
        for sym, rules in _FALLBACK_PAIR_RULES.items():
            base = sym.replace("USDT", "")
            tp = _TP(pair=f"{base}/USD", symbol=sym, coin=base, unit="USD",
                     can_trade=True, price_precision=int(rules["price_precision"]),
                     amount_precision=int(rules["amount_precision"]),
                     mini_order=float(rules["mini_order"]))
            main.gateway_engine.trading_pairs_by_symbol[sym] = tp
            main.trading_pairs_by_symbol[sym] = tp

    main.get_trading_pair = lambda sym: main.trading_pairs_by_symbol.get(
        str(sym).strip().upper()
    )

    # MainEngine facade methods used by EventEngine.handle_intent.
    main.place_order = lambda **kwargs: main.gateway_engine.place_order(**kwargs)
    main.cancel_order = lambda **kwargs: main.gateway_engine.cancel_order(**kwargs)
    main.query_order = lambda **kwargs: main.gateway_engine.query_order(**kwargs)
    main.get_pending_orders_by_symbol = lambda strategy_name: main.gateway_engine.get_pending_orders_by_symbol(strategy_name)
    main.handle_intent = main.event_engine.handle_intent

    return main


def _capture_strategy_orders(main, strategy_name: str) -> list[tuple[str, str, float, float, str]]:
    out: list[tuple[str, str, float, float, str]] = []
    for d in main.gateway_engine._order_map.values():
        if (d.strategy_name or "") != strategy_name:
            continue
        out.append((d.symbol, d.side, float(d.quantity), float(d.price), str(d.order_type or "")))
    return out


def _poll_until_finished(main, strategy_name: str, max_rounds: int = 5) -> None:
    for _ in range(max_rounds):
        pending = main.gateway_engine.get_pending_orders_by_symbol(strategy_name)
        if not any(pending.values()):
            return
        main.gateway_engine._poll_orders_and_emit()
    # Best effort; caller assertions will surface any remaining mismatch.


def _seed_bars(me: MarketEngine, symbol: str, closes: list[float], interval: str) -> None:
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = max(o, c) + 0.1
        l = min(o, c) - 0.1
        me.on_bar(BarData(symbol=symbol, open=o, high=h, low=l, close=c, volume=100.0, interval=interval))


def _live_price_from_gateway(main, symbol: str) -> float:
    """Fetch one symbol price from Gateway ticker payload."""
    body = main.gateway_engine.get_ticker(symbol)
    if not isinstance(body, dict):
        # In CI/sandbox the gateway ticker call may fail (network blocked),
        # so fall back to MarketEngine cache or deterministic defaults.
        sd = main.market_engine.get_symbol(symbol)
        if sd and getattr(sd, "last_price", 0.0):
            return float(sd.last_price)
        if symbol == "BTCUSDT":
            return 100000.0
        if symbol == "APTUSDT":
            return 8.0
        return 100.0
    if body.get("Success") is False:
        raise AssertionError(f"ticker failed for {symbol}: {body!r}")
    pair = GatewayEngine._to_roostoo_pair(symbol)

    # Shape A: {"Data": {"BTC/USD": {"LastPrice": ...}}}
    data = body.get("Data")
    if isinstance(data, dict):
        item = data.get(pair)
        if isinstance(item, dict) and item.get("LastPrice") is not None:
            p = float(item["LastPrice"])
            if p > 0:
                return p

    # Shape B: {"TradePairs": [{"Pair":"BTC/USD","LastPrice":...}, ...]}
    pairs = body.get("TradePairs")
    if isinstance(pairs, list):
        item = next((x for x in pairs if isinstance(x, dict) and str(x.get("Pair")) == pair), None)
        if item and item.get("LastPrice") is not None:
            p = float(item["LastPrice"])
            if p > 0:
                return p
    # Fallback from MarketEngine symbol cache if gateway updated it.
    sd = main.market_engine.get_symbol(symbol)
    if sd and getattr(sd, "last_price", 0.0):
        return float(sd.last_price)
    raise AssertionError(f"Cannot resolve live price for {symbol} from ticker response: {body!r}")


def test_integration_strategy_maliki_open_then_close_updates_holdings():
    main = _make_main_with_real_gateway()
    place_calls = []
    orig_place = main.gateway_engine.place_order

    def _trace_place(**kwargs):
        resp = orig_place(**kwargs)
        place_calls.append({"kwargs": dict(kwargs), "resp": resp})
        return resp

    main.gateway_engine.place_order = _trace_place
    strat = StrategyMaliki(
        main,
        "strategy_maliki_Int",
        setting={
            "pairs": ["BTCUSDT"],
            "lookback_candles": 5,
            "regime_ma_candles": 5,
            "rebalance_every": 1,
            "min_hold_candles": 0,
            "top_n": 1,
            # Keep threshold high so seeded BTC is the only qualifier.
            "min_momentum_pct": 2.0,
            "min_notional_24h": 0.0,
            # keep test orders small if balance API is unavailable/fails
            "capital_allocation": 50.0,
            "max_single_alloc_pct": 100.0,
        },
    )
    main.strategy_engine._strategies = [strat]

    # Real market data path: seeded bar closes drive maliki's LIMIT buy (close * 1.001).
    # `round(btc_px/1k)*1k` can round DOWN vs live ticker, leaving limit below market →
    # BUY stays PENDING, no BTC settles, MARKET SELL then fails. Ceil keeps limit >= live.
    btc_px = _live_price_from_gateway(main, "BTCUSDT")
    # Step-friendly anchor so LIMIT (price * 1.001) lands on an integer and crosses the book.
    btc_base = math.ceil(btc_px / 1000.0) * 1000.0
    _seed_bars(
        main.market_engine,
        "BTCUSDT",
        [btc_base * 0.96, btc_base * 0.97, btc_base * 0.98, btc_base * 0.99, btc_base * 1.00, btc_base * 1.00],
        interval="5m",
    )

    strat.on_init()
    strat.on_start()

    # 1) Open signal
    strat.on_timer_logic()
    _poll_until_finished(main, strat.strategy_name)
    sent = _capture_strategy_orders(main, strat.strategy_name)
    assert any(s == "BUY" for _, s, *_ in sent), f"No BUY captured. place_calls={place_calls}"
    holding = main.strategy_engine.get_holding(strat.strategy_name)
    assert any(getattr(p, "quantity", 0.0) > 0 for p in holding.positions.values())

    # 2) Force bearish regime via real bar update path.
    _seed_bars(main.market_engine, "BTCUSDT", [btc_px * 0.80], interval="5m")
    strat.on_timer_logic()
    _poll_until_finished(main, strat.strategy_name)
    sent = _capture_strategy_orders(main, strat.strategy_name)
    assert any(s == "SELL" for _, s, *_ in sent), f"No SELL captured. place_calls={place_calls}"
    holding = main.strategy_engine.get_holding(strat.strategy_name)
    assert all(getattr(p, "quantity", 0.0) == 0.0 for p in holding.positions.values())


def test_integration_strategy_jh_open_then_close_updates_holdings():
    main = _make_main_with_real_gateway()
    strat = StrategyJH(
        main,
        "strategy_JH_Int",
        setting={
            "pairs": ["APTUSDT"],
            "pivot_len": 1,
            "atr_len": 1,
            "fill_bars": 1,
            # force integer qty path to satisfy strict quantity step rules
            "capital": 10.0,
            "risk_pct": 0.01,
        },
    )
    main.strategy_engine._strategies = [strat]

    # Real bar buffer anchored to live APT price +10%; keep signal constraints true.
    apt_px = _live_price_from_gateway(main, "APTUSDT")
    p = apt_px * 1.10
    bars = [
        BarData("APTUSDT", p * 1.01, p * 1.02, p * 0.99, p * 1.00, interval="15m"),
        BarData("APTUSDT", p * 1.00, p * 1.01, p * 0.98, p * 0.99, interval="15m"),
        BarData("APTUSDT", p * 0.99, p * 1.00, p * 0.97, p * 0.985, interval="15m"),
        BarData("APTUSDT", p * 1.01, p * 1.02, p * 0.97, p * 1.00, interval="15m"),  # prev
        BarData("APTUSDT", p * 0.99, p * 1.02, p * 0.96, p * 1.00, interval="15m"),  # cur
    ]
    for b in bars:
        main.market_engine.on_bar(b)
    # Pivot must be on the same price scale as APT to satisfy signal gates.
    main.market_engine.get_pivot_low = MagicMock(return_value=p * 0.97)
    main.market_engine.prev3_bearish_strict = MagicMock(return_value=True)
    main.market_engine.get_atr = MagicMock(return_value=1.0)
    main.market_engine.update_symbol_from_ticker("APTUSDT", last_price=p)
    # StrategyJH uses SymbolData.amount_precision for qty rounding; use integer qty for test.
    main.market_engine._symbols["APTUSDT"] = SymbolData(symbol="APTUSDT", last_price=p, amount_precision=0)

    strat.on_init()
    strat.on_start()

    # 1) Open signal
    strat.on_timer_logic()
    _poll_until_finished(main, strat.strategy_name)
    sent = _capture_strategy_orders(main, strat.strategy_name)
    st = strat._state["APTUSDT"]
    assert any(s == "BUY" for _, s, *_ in sent)
    holding = main.strategy_engine.get_holding(strat.strategy_name)
    assert holding.positions["APTUSDT"].quantity > 0

    # 2) Push price above target to trigger close signal.
    st = strat._state["APTUSDT"]
    # With immediate FILLED from gateway register_order, fill callback may happen
    # before strategy stores pending_* fields in _process_signal. Make the exit state
    # deterministic for this integration test.
    if st.get("active_target") is None and st.get("pending_target") is not None:
        st["active_target"] = st["pending_target"]
        st["active_stop"] = st["pending_stop"]
    assert st.get("active_target") is not None
    exit_target = float(st["active_target"])
    main.market_engine.update_symbol_from_ticker("APTUSDT", last_price=exit_target + 0.01)
    # Prevent same-tick re-entry after EXIT TARGET.
    main.market_engine.prev3_bearish_strict = MagicMock(return_value=False)
    strat.on_timer_logic()
    _poll_until_finished(main, strat.strategy_name)
    sent = _capture_strategy_orders(main, strat.strategy_name)
    assert any(s == "SELL" for _, s, *_ in sent)
    holding = main.strategy_engine.get_holding(strat.strategy_name)
    assert holding.positions["APTUSDT"].quantity == 0.0


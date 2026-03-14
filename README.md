# T-hackathon

## Crypto trading system (skeleton)

Deterministic, event-driven crypto trading skeleton inspired by OTrader:

- **REST vendor**: market data and orders use stateless HTTP (no persistent connection).
- **Timer-driven loop**: each timer tick runs gateway → position → strategy → risk. Gateway fetches and emits `EVENT_BAR` (payload: `BarData`); event engine routes bars to the market engine, which stores `BarData` and updates the symbol cache and indicators; strategies and position read via `market_engine.get_symbol()`, `get_last_bars()`, etc.
- **Bar data only**: all bar handling uses the `BarData` dataclass (symbol, open, high, low, close, volume, ts); no separate tuple type.
- **Central routing**: the event engine owns the routing and call order (no dynamic registration).
- **gRPC**: remote dashboard and control over gRPC (stub only until codegen is wired).
- **Long-only positions**: position engine enforces quantity ≥ 0; shorting raises `ValueError`.

---

## Code layout

```text
src/
├── engines/
│   ├── engine_main.py      # Composition root and façade
│   ├── engine_event.py     # Event queue and deterministic routing
│   ├── engine_gateway.py   # REST I/O; on_timer() fetches and put_bar(BarData); emits EVENT_BAR
│   ├── engine_market.py    # BarData buffer + SymbolData; on_bar(); get_symbol(), get_atr(), get_pivot_low(), prev3_bearish_strict()
│   ├── engine_strategy.py  # AVAILABLE_STRATEGIES (name→class); add_strategy_for_pair; init/start/stop_strategy
│   ├── engine_position.py  # Per-strategy positions and PnL from trades; long-only
│   └── engine_risk.py      # Risk checks and alerts
├── grpc/
│   ├── __init__.py
│   ├── service.proto       # Dashboard/control RPCs
│   └── server.py           # GrpcServer(main_engine) stub
├── strategies/
│   ├── template.py         # StrategyTemplate: on_init, on_start, on_stop, on_timer, on_order, on_trade; get_symbol, send_order, clear_all_positions
│   └── factory/            # Strategy implementations (e.g. strat1_pine.py); register in engine_strategy.AVAILABLE_STRATEGIES
└── utilities/
    ├── base_engine.py      # BaseEngine: main_engine, engine_name, close()
    ├── events.py           # Event type constants (EVENT_BAR, EVENT_ORDER, EVENT_TRADE, ...)
    ├── intents.py          # Intent constants (INTENT_PLACE_ORDER, INTENT_CANCEL_ORDER, INTENT_LOG)
    └── object.py           # BarData, SymbolData, OrderRequest, CancelOrderRequest, OrderData, TradeData, PositionData, StrategyHolding, LogData, ...
```

---

## Engines

**MainEngine** — Builds all engines, starts the event loop. Holds `TRADING_PAIRS` (e.g. `["BTCUSDT", "ETHUSDT"]`); market and gateway are given this list. `add_strategy(strategy_name, trading_pair)` looks up the class in `StrategyEngine.AVAILABLE_STRATEGIES` and creates an instance. Exposes `get_strategy`, `init_strategy`, `start_strategy`, `stop_strategy`, `put_event`, `handle_intent`, `send_order`, `cancel_order`.

**EventEngine** — Single event queue and timer thread. Routes events and intents to the right engines in a fixed order (no plug-in registration).

**GatewayEngine** — Sole contact with the vendor (HTTP). Initialized with `trading_pairs`. In `on_timer()` fetch bars and call `put_bar(BarData(...))`. Implements `send_order` and `cancel_order`.

**MarketEngine** — Stores `BarData` per symbol; receives `EVENT_BAR` and updates bar buffer + symbol cache. Exposes `get_symbol(symbol)`, `get_last_bars(symbol, n)`, `get_bar_count`, `get_atr`, `get_pivot_low`, `prev3_bearish_strict`.

**StrategyEngine** — `AVAILABLE_STRATEGIES` dict (name → class). `add_strategy_for_pair(strategy_name, trading_pair)` creates one instance; `get_strategy`, `init_strategy`, `start_strategy`, `stop_strategy` for per-strategy control. Dispatches `on_order`, `on_trade`, `on_timer` to each strategy.

**PositionEngine** — Per-strategy positions and PnL; long-only (quantity ≥ 0). Consumes trades via `on_trade`. On each timer tick, `process_timer_event()` refreshes metrics from market engine mark prices. Exposes `get_holding(strategy_name)`, `serialize_holding`, `load_serialized_holding`.

**RiskEngine** — Receives `on_order`, `on_trade`, `on_timer` and can emit `EVENT_RISK_ALERT`.

---

## Event and intent routing

**Bar** — `EVENT_BAR` (payload: `BarData`) → `MarketEngine.on_bar()` (appends bar, updates symbol cache).

**Timer** — `Gateway.on_timer()` (may call `put_bar(BarData)`) → `Position.process_timer_event()` → `Strategy.on_timer()` → `Risk.on_timer()`.

**Order** — `Strategy.on_order()` → `Risk.on_order()`.

**Trade** — `Position.on_trade()` → `Strategy.on_trade()` → `Risk.on_trade()`.

**Log / risk alert** — Printed to stdout.

**Intents** — `INTENT_PLACE_ORDER` → `send_order`; `INTENT_CANCEL_ORDER` → `cancel_order`; `INTENT_LOG` → `put_event(EVENT_LOG, ...)`.

---

## gRPC layer

Stub only: add `grpcio` and `grpcio-tools`, then run codegen. `grpc/service.proto` defines control (SendOrder, CancelOrder, Log) and dashboard (GetPositions, GetSymbol, StreamLogs). `GrpcServer(main_engine)` would forward RPCs to the main engine.

```bash
python -m grpc_tools.protoc -I src/grpc --python_out=src/grpc --grpc_python_out=src/grpc src/grpc/service.proto
```

---

## How to use

1. `main = MainEngine()` — uses `TRADING_PAIRS`; timer starts; market and gateway have bar buffers for each symbol.
2. `main.add_strategy("Strat1Pine", "BTCUSDT")` — looks up the class in `AVAILABLE_STRATEGIES` and adds it for that pair. Add new strategies under `src/strategies/factory` and register them in `engine_strategy.AVAILABLE_STRATEGIES`.
3. Optionally `main.init_strategy("Strat1Pine_BTCUSDT")`, `main.start_strategy(...)`, `main.stop_strategy(...)` for lifecycle control.
4. Gateway implements `on_timer()` to fetch bars for `self.trading_pairs` and call `put_bar(BarData(...))`. Strategies use `get_symbol(symbol)` and market engine indicator methods; place orders via `send_order(...)`. Template provides `clear_all_positions()` to flatten long positions.

# T-hackathon

## Quick start: how the system runs

- **Two modes**:
  - `python main.py mock` — safe paper-trading against Roostoo mock (`https://mock-api.roostoo.com`).
  - `python main.py real` — live trading against the real Roostoo API (`https://api.roostoo.com` or `ROOSTOO_REAL_BASE_URL`).
- **Config‑driven strategies (current behavior)**:
  - On startup, `main.py` reads `strategies_config.json` (or `STRATEGY_CONFIG_PATH` if set).
  - For each entry `{ "strategy": "...", "symbol": "..." }` it automatically:
    - calls `main.add_strategy(strategy, symbol)`
    - then `main.init_strategy(...)`
    - then `main.start_strategy(...)`
  - There is no manual CLI to add strategies yet; edit `strategies_config.json` to control what runs.

## Crypto trading system (skeleton)

Event-driven crypto trading skeleton for a mock exchange (Roostoo):

- **Pure HTTP integration**: both market data and orders go through stateless REST calls.
- **Timer-driven core loop**: on each tick, the system pulls market data, refreshes positions, lets strategies run, then applies risk.
- **Bars, not ticks**: market data is modeled as OHLC bars; the market engine is the single source of truth for symbol state and indicators.
- **Order-status driven positions**: positions are derived from order status (fills) and marked to market using the latest prices.
- **Centralized routing**: a single event engine controls how data flows between engines.
- **Long-only**: the position engine enforces non-negative quantities; shorting is intentionally out of scope.

---

## Code layout

```text
src/
├── engines/
│   ├── engine_main.py      # Composition root and façade
│   ├── engine_event.py     # Event queue and deterministic routing
│   ├── engine_gateway.py   # Roostoo REST adapter for market data, orders, and account state
│   ├── engine_market.py    # Central symbol cache and bar/indicator storage
│   ├── engine_strategy.py  # Strategy registry, lifecycle, and event fan-out
│   ├── engine_position.py  # Per-strategy holdings and mark-to-market PnL
│   └── engine_risk.py      # Risk hooks (order/timer)
├── grpc/
│   ├── __init__.py
│   ├── service.proto       # Dashboard/control RPCs
│   └── server.py           # GrpcServer(main_engine) stub
├── strategies/
│   ├── template.py         # Common lifecycle and helper API for strategies
│   └── factory/            # Concrete strategies, discoverable by name
└── utilities/
    ├── base_engine.py      # BaseEngine: main_engine, engine_name, close()
    ├── events.py           # Event-type constants
    ├── intents.py          # Intent-type constants
    └── object.py           # Shared dataclasses used as event payloads
```

---

## Engines

**MainEngine** — Composition root and façade. It wires and owns all engines, starts the event loop, and exposes a simple API for:

- Managing strategies (register, init, start, stop)
- Pushing events into the system
- Calling high-level gateway operations (send/cancel order, query orders, pull balances/tickers)

**EventEngine** — In-process event bus and timer. It owns the deterministic call order between engines and keeps the system loosely coupled:

- Translates timer ticks into a fixed “gateway → position → strategy → risk” pipeline
- Routes bar events from gateway to market engine
- Routes intents (place/cancel/log) to the appropriate high-level operations

**GatewayEngine** — The only component that talks to Roostoo. It:

- Pulls market data on each timer tick and turns it into bar events
- Sends orders, cancels orders, and polls order status on behalf of strategies
- Maintains a per-strategy view of active/pending orders so higher layers don’t have to know API details

**MarketEngine** — In-memory view of the market. It:

- Tracks recent bars per symbol
- Maintains a simple symbol cache (last price and timestamp)
- Offers a surface for strategies to fetch prices and indicators without touching the vendor API

**StrategyEngine** — Strategy container. It:

- Discovers and instantiates strategies by name
- Owns strategy lifecycle transitions
- Fans out relevant events (order updates and timer ticks) to each strategy instance

**PositionEngine** — Strategy-level positions and PnL. It:

- Derives position changes from order status (fills)
- Uses the latest prices from the market engine to compute mark-to-market values
- Presents a clean per-strategy holdings view for strategies, risk, and dashboards

**RiskEngine** — Hook point for custom risk logic. It:

- Observes orders and timer ticks
- Can emit risk alerts via the event system

---

## Event and intent routing

At a high level, the data flow is:

- **Market data**: gateway pulls from the exchange, converts to bars, and pushes into the event bus; market engine is the single consumer and cache.
- **Orders**: strategies express intent to trade; gateway turns that into API calls and periodically turns order status into internal order events.
- **Positions & PnL**: position engine interprets order events, keeps holdings per strategy, and uses the market view for valuing those holdings.
- **Intents & control**: high-level actions like “place order”, “cancel order”, and “log” remain intents; the event engine translates them into concrete engine calls.

---

## gRPC layer

Stub only: add `grpcio` and `grpcio-tools`, then run codegen. `grpc/service.proto` defines control (SendOrder, CancelOrder, Log) and dashboard (GetPositions, GetSymbol, StreamLogs). `GrpcServer(main_engine)` would forward RPCs to the main engine.

```bash
python -m grpc_tools.protoc -I src/grpc --python_out=src/grpc --grpc_python_out=src/grpc src/grpc/service.proto
```

---

## How to use

### 1. Prepare environment

- **Install dependencies** (inside a virtualenv):

  ```bash
  pip install -r requirements.txt
  ```

- **Create `.env` at repo root** (see `.env.sample` for keys):
  - `General_Portfolio_Testing_API_KEY`
  - `General_Portfolio_Testing_API_SECRET`
  - Optionally `ROOSTOO_MOCK_BASE_URL` (defaults to `https://mock-api.roostoo.com`)
  - Optionally `ROOSTOO_REAL_BASE_URL` for real trading.

The gateway will read these on startup; without keys, signed endpoints (balance, orders) will fail.

### 2. Running in mock mode (paper trading on Roostoo mock)

Mock mode is the default and is **safe**: all trading happens against the Roostoo mock environment.

```bash
python main.py mock
```

What happens:

1. **Process bootstrap**
   - Ensures the repo root is on `sys.path`.
   - Loads strategy config from `strategies_config.json` (or `STRATEGY_CONFIG_PATH` if set).  
     **Right now `main.py` only supports this config-driven mode: it auto-creates, inits, and starts all strategies defined in that JSON file.**

2. **Engine startup**
   - `MainEngine(env_mode="mock")` is created.
   - `GatewayEngine` points to `ROOSTOO_MOCK_BASE_URL`.
   - `MainEngine` calls `GET /v3/exchangeInfo` and:
     - Discovers all available pairs from `TradePairs`.
     - Caches them in `main_engine.trading_pairs` (available universe).
     - Does **not** poll all of them each tick; it only polls pairs used by strategies.
   - `EventEngine` starts its worker + timer threads (1s tick).

3. **Strategy wiring**
   - For each entry in `strategies_config.json`, `main.py` does:
     - `main.add_strategy(strategy_name, symbol)`
     - `main.init_strategy(f"{strategy_name}_{symbol}")`
     - `main.start_strategy(f"{strategy_name}_{symbol}")`
   - Adding a strategy for `BTCUSDT`:
     - Marks `BTCUSDT` as **active**.
     - Subscribes `GatewayEngine` ticker polling for that symbol.
     - Pre-creates bar buffers for `BTCUSDT` in `MarketEngine`.

4. **Live loop**
   - On each timer tick:
     - `GatewayEngine` calls **one** `GET /v3/ticker?timestamp=...` with no `pair`, receiving all pairs,
       then filters down to active symbols (e.g. `BTCUSDT`) and emits `EVENT_BAR` for each as a 1‑tick OHLC bar.
     - `MarketEngine` updates `SymbolData` (latest price) and appends bars per symbol.
     - `PositionEngine` recomputes mark‑to‑market values.
     - `StrategyEngine` calls `on_timer()` on each started strategy; strategies:
       - Read prices via `get_symbol(symbol)` / indicator helpers.
       - Place orders via `StrategyTemplate.send_order(...)` (MARKET/LIMIT).
     - `GatewayEngine` polls order status with `POST /v3/query_order` and emits `EVENT_ORDER` updates,
       which flow into `PositionEngine` and strategies.

5. **Shutdown**
   - `Ctrl+C` in the terminal:
     - `main.py` stops all started strategies (`main.stop_strategy(name)`).
     - Calls `main.disconnect()` to stop the event engine and close the gateway.

### 3. Running in real mode (live Roostoo trading)

Real mode talks to the live Roostoo API. **Only use this if you understand the risk and have real credentials.**

```bash
python main.py real
```

Differences vs mock:

- `MainEngine(env_mode="real")`:
  - `GatewayEngine` switches base URL to `ROOSTOO_REAL_BASE_URL` (or `https://api.roostoo.com` by default).
  - Still uses the same discovery flow (`/v3/exchangeInfo`) and the same timer‑driven architecture.
- API keys:
  - You should point `ROOSTOO_REAL_BASE_URL` and appropriate API key/secret env vars to your live account.
- Behavior:
  - Strategies, position tracking, and logging behave identically; only the underlying HTTP endpoints and balances are different.

### 4. Programmatic usage

If you want to embed `MainEngine` directly instead of using `main.py`:

1. Create and start the engine:

   ```python
   from src.engines.engine_main import MainEngine

   main = MainEngine(env_mode="mock")  # or "real"
   ```

2. Add and control strategies:

   ```python
   main.add_strategy("Strat1Pine", "BTCUSDT")
   name = "Strat1Pine_BTCUSDT"
   main.init_strategy(name)
   main.start_strategy(name)
   # ...
   main.stop_strategy(name)
   main.disconnect()
   ```

3. Interact with gateway/positions:

   ```python
   main.get_all_trading_pairs()
   main.get_ticker("BTCUSDT")
   main.get_balance()
   main.place_order("BTCUSDT", "BUY", 0.001, order_type="MARKET")
   holding = main.position_engine.get_holding("Strat1Pine_BTCUSDT")
   ```

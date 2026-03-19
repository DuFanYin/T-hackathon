# T-hackathon Architecture (current)

This document describes the **current** architecture implemented in this repository: a single-process Python trading system with a FastAPI control plane and a React (Vite) operator dashboard. The dashboard is **poll-based** (no WebSockets/SSE).

## Repository layout

- `api_server.py`: starts FastAPI (Uvicorn) and owns engine lifetime via `EngineManager`.
- `src/control/`: HTTP API (`api.py`), engine lifecycle (`engine_manager.py`), persistence helpers (`order_store.py`, `log_store.py`).
- `src/engines/`: composition root (`engine_main.py`) + engines (`engine_event.py`, `engine_gateway.py`, `engine_market.py`, `engine_strategy.py`, `engine_risk.py`).
- `src/strategies/`: strategy base + implementations (`template.py`, `factory/*.py`).
- `src/utilities/`: shared models/constants (`object.py`, `events.py`, `intents.py`, etc.).
- `frontend/`: React + TypeScript + Vite dashboard (`frontend/src/`).
- `data/`:
  - `data/orders/orders.db`: SQLite order persistence (filled orders)
  - `data/logs/system.log`: rotating disk logs
- `scripts/`: standalone utilities (not part of the running service).

## System overview

The system is split into:

- **Control plane (FastAPI)**: starts/stops the engine and exposes snapshots (strategies, holdings, account cache, orders DB, logs tail).
- **Engine (in-process)**: event-driven engines running inside the same Python process (threads).
- **Dashboard (React SPA)**: operator UI calling the control API and polling snapshots.

High-level runtime diagram:

```text
                         HTTP (fetch/poll)                 start/stop
┌───────────────────────────────┐    ┌───────────────────────────────────────────┐
│ React Dashboard (Vite)        │    │ FastAPI Control Plane                     │
│ frontend/                     │───▶│ src/control/api.py                        │
│ - Strategies/Account/Orders   │    │ - CORS + optional x-admin-token auth      │
│ - Logs (tail polling)         │    │ - Snapshots + lifecycle calls             │
└───────────────────────────────┘    └───────────────┬───────────────────────────┘
                                                      owns lifetime via
                                           ┌───────────────────────────────────┐
                                           │ EngineManager                     │
                                           │ src/control/engine_manager.py     │
                                           └─────────────────┬─────────────────┘
                                                             │ creates/stops
                                           ┌─────────────────▼─────────────────┐
                                           │ MainEngine                        │
                                           │ src/engines/engine_main.py        │
                                           │ (composition root)                │
                                           └───┬───────────┬───────────────┬───┘
                                               │           │               │
                                     ┌─────────▼───┐  ┌────▼─────────┐ ┌───▼───────────┐
                                     │ EventEngine │  │ MarketEngine │ │ GatewayEngine │
                                     │ timer+queue │  │ Binance      │ │ Roostoo REST  │
                                     └──────┬──────┘  └──────┬───────┘ └───────┬───────┘
                                            │                │                 │ poll+persist
                                            │                │                 │
                                     ┌──────▼─────────┐  ┌───▼─────────┐  ┌────▼──────────────────┐
                                     │ StrategyEngine │  │ RiskEngine  │  │ OrderStore (SQLite)   │
                                     │ holdings+PnL   │  │ account PnL │  │ data/orders/orders.db │
                                     └────────────────┘  └─────────────┘  └───────────────────────┘
```

## Process model and entrypoint

### Control plane entrypoint

`api_server.py`:

- loads `.env` from repo root (via `python-dotenv`)
- instantiates `EngineManager`
- constructs FastAPI app via `src/control/api.py:create_app(mgr)`
- runs Uvicorn on `CONTROL_HOST`/`CONTROL_PORT` (defaults `0.0.0.0:8000`)

### Engine concurrency model

There is **one Python process**. The engine runs **in-process** and uses threads:

- `EventEngine` has:
  - a worker thread consuming an in-memory queue of events
  - a timer thread emitting `EVENT_TIMER` every `interval` seconds (default 1.0)

The UI does **not** open a streaming connection; it polls logs using `GET /logs/tail`.

## Backend architecture

### Composition root: `MainEngine`

`src/engines/engine_main.py:MainEngine` wires the system together:

- `EventEngine`: deterministic routing + timer
- `MarketEngine`: Binance klines -> bars/symbol snapshots + indicators
- `GatewayEngine`: Roostoo adapter + order polling + cached account snapshots
- `StrategyEngine`: strategy registry + holdings + mark-to-market PnL
- `RiskEngine`: provides the `GET /account/pnl` snapshot
- `OrderStore`: SQLite persistence for FILLED orders
- `LogStore`: in-memory log tail + disk rotation writer

`MainEngine` init sequence (simplified):

- construct engines
- discover tradeable pairs via Roostoo `/v3/exchangeInfo`
- seed `MarketEngine` symbol buffers for discovered pairs
- **auto-create an instance for every strategy** in `src/engines/engine_strategy.py:AVAILABLE_STRATEGIES`
- start the `EventEngine`
- warm cached account snapshot (balance + pending query)

Important design choice:

- Strategies are created in a **Created** state and only run when explicitly started.
- There is no longer an “add/delete strategy” lifecycle in the control plane.

### Lifecycle boundary: `EngineManager`

`src/control/engine_manager.py:EngineManager` owns engine lifetime:

- **Start**: constructs `MainEngine(env_mode=mock|real)` if not already running
- **Stop**: stops the event engine and drops the engine reference

The HTTP server stays up regardless of engine state.

### Tick pipeline: `EventEngine`

On each `EVENT_TIMER` tick (`src/engines/engine_event.py`):

1. `MarketEngine.on_timer()` — refresh market bars/snapshots from Binance for active pairs
2. `GatewayEngine.on_timer()` — poll tracked orders; refresh cached account snapshot on cadence
3. `StrategyEngine.process_timer_event()` — recompute holdings/PnL from latest prices
4. `StrategyEngine.on_timer()` — run each started strategy’s timer logic
5. `RiskEngine.on_timer()` — update account PnL snapshot

### Engines and responsibilities

#### `GatewayEngine` (Roostoo adapter + polling + cache)

`src/engines/engine_gateway.py:GatewayEngine`:

- places/cancels orders via Roostoo REST
- polls order status via `/v3/query_order` for tracked orders
- maintains cached account snapshots:
  - `balance` (from `/v3/balance`)
  - `pending_count` (derived from cached pending map)
  - `orders snapshot` (tracks list for UI)

Important behavior:

- MARKET orders can return **FILLED immediately** from `place_order`. The engine emits fills immediately so `StrategyEngine` holdings update even if the order never enters the polling loop.

Mode and base URLs:

- `env_mode`: `mock` or `real` (selected by `POST /system/start`)
- `ROOSTOO_MOCK_BASE_URL` / `ROOSTOO_REAL_BASE_URL`: optional overrides

Credentials are sourced from `.env` (see `.env.sample`).

#### `MarketEngine` (market data + indicators)

`src/engines/engine_market.py:MarketEngine`:

- keeps per-symbol, per-interval bar buffers
- refreshes bars from Binance klines on a throttled schedule
- provides indicator helpers consumed by strategies (ATR, pivots, pattern checks)

#### `StrategyEngine` (strategy registry + holdings/PnL)

`src/engines/engine_strategy.py:StrategyEngine`:

- owns the strategy instances (auto-created during engine init)
- applies `OrderData` fill deltas to per-strategy holdings
- computes mark-to-market totals:
  - `total_cost` (cost value: avg_cost × quantity)
  - `current_value` (quantity × mid_price)
  - `unrealized_pnl`, `realized_pnl`, `pnl`
- enforces “must be FLAT” before stopping a strategy

#### `RiskEngine` (account PnL snapshot)

`src/engines/engine_risk.py:RiskEngine` provides the snapshot returned by `GET /account/pnl`.

## State and persistence

### Orders DB (`OrderStore`)

`src/control/order_store.py:OrderStore` persists orders in SQLite at `data/orders/orders.db`.

The engine writes to SQLite when an order becomes **FILLED**. The control API exposes:

- `GET /orders`: read-only query against SQLite (works even when the engine is stopped)

### Logs (disk rotation + tail)

`MainEngine.write_log()` appends to a rotating file:

- default: `data/logs/system.log`

Control API exposes:

- `GET /logs/tail?n=...`: last \(n\) non-empty lines (works even if engine is stopped; returns `[]` if file missing)

## Control plane (FastAPI) contract

`src/control/api.py:create_app(engine_manager)` configures:

- **CORS**:
  - `CONTROL_CORS_ORIGINS` (comma-separated list)
  - when `ENVIRONMENT=local`, Vite dev origins are always allowed (`http://localhost:5173`, `http://127.0.0.1:5173`)
- **Admin token auth (optional)**:
  - if `CONTROL_ADMIN_TOKEN` is set, privileged endpoints require `x-admin-token: <token>`
  - if unset, endpoints are open (dev convenience)

### Endpoint inventory (source of truth: `src/control/api.py`)

- **Auth**
  - `GET /auth/check`
- **System**
  - `GET /system/status`
  - `POST /system/start` with `{ "mode": "mock" | "real" }`
  - `POST /system/stop`
  - `GET /health`
- **Strategies**
  - `GET /strategies/available`
  - `GET /strategies/running`
  - `POST /strategies/start`
  - `POST /strategies/stop`
  - (removed) `POST /strategies/add`
  - (removed) `POST /strategies/delete`
- **Holdings / positions**
  - `GET /positions`
  - `POST /positions/close`
  - `POST /positions/close_all`
- **Market pairs**
  - `GET /pairs`
- **Account (cached)**
  - `GET /account/balance`
  - `GET /account/pending_count`
  - `GET /account/orders`
  - `GET /account/pnl`
- **Orders DB**
  - `GET /orders`
- **Logs**
  - `GET /logs/tail`

## Frontend architecture (React + Vite)

The dashboard is a SPA under `frontend/`:

- `frontend/src/App.tsx`: layout + polling loop (system status, strategies, positions; account snapshots when authed)
- `frontend/src/lib/api.ts`: API client wrapper around `fetch()`
- Panels in `frontend/src/components/`:
  - `Sidebar.tsx` (auth + engine controls)
  - `StrategiesPanel.tsx` (start/stop + holdings rows)
  - `AccountValuePanel.tsx` (balance + account PnL)
  - `OrdersPanel.tsx` (cached order tracks)
  - `LogsPanel.tsx` (log tail viewer)

Constraints:

- UI polls; no streaming transport
- browser does not call Roostoo directly; exchange calls stay inside the engine

Configuration:

- `VITE_API_BASE` controls backend base URL (defaults to `http://localhost:8000`)
- admin token is stored in `localStorage` and sent as `x-admin-token`

## Scripts

- `scripts/debug_order_parse.py`: place MARKET → query → print raw detail → parse into `OrderData`
- `scripts/flatten_account.py`: cancel pending orders → market-sell all non-USD wallet positions

## Known gaps / sharp edges

- Many endpoints return **cached snapshots** by design (UI should not trigger exchange calls).
- Strategies that derive symbol lists from `MarketEngine.get_cached_symbols()` depend on `MainEngine` seeding market buffers first (current init order handles this).

# T-hackathon Architecture (current)

This document describes the *actual* architecture implemented in this repository: a single-process Python trading engine with a FastAPI control plane, plus a React (Vite) dashboard that polls snapshots and uses Server-Sent Events (SSE) for live logs.

## Repository layout

- `api_server.py`: starts the FastAPI control plane (Uvicorn) and owns engine lifetime via `EngineManager`.
- `src/control/`: HTTP API (`api.py`), engine lifecycle wrapper (`engine_manager.py`), persistence helpers (`order_store.py`, `log_store.py`).
- `src/engines/`: composition root (`engine_main.py`) + core engines (`engine_event.py`, `engine_gateway.py`, `engine_market.py`, `engine_strategy.py`, `engine_risk.py`).
- `src/strategies/`: strategy base + concrete strategies (`template.py`, `factory/*.py`).
- `src/utilities/`: internal data models and shared constants (`object.py`, `events.py`, `intents.py`, etc.).
- `frontend/`: React + TypeScript + Vite dashboard (`frontend/src/`).
- `data/`: runtime state on disk:
  - `data/orders/orders.db`: SQLite order persistence (latest view + append-only history).
  - `data/logs/system.log`: rotating disk logs (mirrors in-memory log tail).
- `scripts/`: standalone utilities, including `scripts/test_roostoo_api.py`.

## System overview

The system is intentionally split into:

- **Control plane (FastAPI)**: starts/stops the engine and exposes read-mostly snapshots (strategies, positions, account cache, orders DB, logs).
- **Engine (in-process)**: event-driven engines running on threads inside the same Python process.
- **Dashboard (React SPA)**: operator UI that calls the control API, polls most state, and connects to an SSE stream for live logs.

High-level runtime diagram:

```text
                         HTTP (fetch/poll)                 start/stop
┌───────────────────────────────┐    ┌───────────────────────────────────────────┐
│ React Dashboard               │    │ FastAPI Control Plane                     │
│ frontend/                     │───▶│ src/control/api.py                        │
│ - Strategies/Account/Orders   │    │ - CORS + optional x-admin-token auth      │
│ - Logs (SSE)                  │    │ - Read-mostly snapshots + lifecycle calls │
└───────────────┬───────────────┘    └───────────────┬───────────────────────────┘
                │ SSE: GET /logs/stream              │
                └────────────────────────────────────┘
                                                        owns lifetime via
                                           ┌───────────────────────────────────┐
                                           │ EngineManager                     │
                                           │ src/control/engine_manager.py     │
                                           └─────────────────┬─────────────────┘
                                                             │ creates/stops
                                           ┌─────────────────▼─────────────────┐
                                           │ MainEngine                        │
                                           │ src/engines/engine_main.py        │
                                           │ (composition root)                │
                                           └───┬───────────┬───────────────┬───┘
                                               │           │               │
                                     ┌─────────▼───┐  ┌────▼─────────┐ ┌───▼───────────┐
                                     │ EventEngine │  │ MarketEngine │ │ GatewayEngine │
                                     │ timer+queue │  │ Binance      │ │ Roostoo REST  │
                                     └──────┬──────┘  └──────┬───────┘ └───────┬───────┘
                                            │                │                 │ poll+persist
                                            │                │                 │
                                     ┌──────▼─────────┐  ┌───▼─────────┐  ┌────▼──────────────────┐
                                     │ StrategyEngine │  │ RiskEngine  │  │ OrderStore (SQLite)   │
                                     │ strategies+PnL │  │ (stub)      │  │ data/orders/orders.db │
                                     └──────┬─────────┘  └─────────────┘  └───────────────────────┘
                                            │
                                            │ logs (tail + fanout)
                                      ┌─────▼─────────────────────────────┐
                                      │ LogStore + disk rotation          │
                                      │ data/logs/system.log              │
                                      └───────────────────────────────────┘
```

## Process model and entrypoint

### Control plane entrypoint

`api_server.py` is the main entrypoint for the backend. It:

- loads `.env` at repo root (via `python-dotenv`)
- instantiates `EngineManager`
- constructs the FastAPI app via `src/control/api.py:create_app(mgr)`
- runs Uvicorn on `CONTROL_HOST`/`CONTROL_PORT` (defaults `0.0.0.0:8000`)

### Engine concurrency model

There is **one Python process**. The engine runs **in-process** and uses threads:

- `EventEngine` runs:
  - a **worker thread** that consumes an in-memory queue of events
  - a **timer thread** that emits `EVENT_TIMER` every `interval` seconds (default 1.0)
- The dashboard receives live logs via **SSE** (`GET /logs/stream`) rather than WebSockets.

## Backend architecture

### Composition root: `MainEngine`

`src/engines/engine_main.py:MainEngine` wires the engine together and holds cross-cutting state:

- `EventEngine`: event router and clock
- `MarketEngine`: price/bars + indicators; periodically fetches Binance klines
- `GatewayEngine`: exchange adapter for Roostoo (mock/real modes), order polling, cached account snapshots
- `StrategyEngine`: strategy registry, order -> holdings updates, mark-to-market valuation, per-strategy timers
- `RiskEngine`: present as an engine boundary, currently a placeholder
- `OrderStore`: SQLite persistence for orders at `data/orders/orders.db`
- `LogStore`: bounded in-memory tail + subscriber fanout; disk log rotation to `data/logs/system.log`

`MainEngine` also performs trading-pair discovery via Roostoo `GET /v3/exchangeInfo` and maintains:

- `trading_pairs`: discovered universe
- `active_pairs`: pairs actively used by running strategies (market polling prioritizes these)

### Lifecycle boundary: `EngineManager`

`src/control/engine_manager.py:EngineManager` is the control plane’s handle to the engine:

- **Start**: constructs a new `MainEngine(env_mode=mock|real)` if not already running
- **Stop**: stops the engine clock (`event_engine.stop()`) and drops the engine reference

This keeps the HTTP service “always on” while making the engine itself explicitly start/stop.

### Eventing and tick pipeline: `EventEngine`

`src/engines/engine_event.py:EventEngine` is the deterministic router. On each `EVENT_TIMER` tick, it runs the “tick pipeline” in order:

1. `MarketEngine.on_timer()` (refresh bars / symbols)
2. `GatewayEngine.on_timer()` (poll orders; refresh cached account snapshot periodically)
3. `StrategyEngine.process_timer_event()` (update holdings mark-to-market)
4. `StrategyEngine.on_timer()` (strategy timers)
5. `RiskEngine.on_timer()` (currently stub)

In addition to timer ticks, it routes *intents* (e.g., order placement) using the intent constants in `src/utilities/intents.py`.

### Domain engines

#### `GatewayEngine` (exchange adapter + polling + caching)

`src/engines/engine_gateway.py:GatewayEngine` wraps Roostoo REST calls and provides:

- **Order placement/cancel** (e.g., `/v3/place_order`, `/v3/cancel_order`)
- **Order status polling** for tracked orders (`/v3/query_order`), emitting internal `OrderData` updates
- **Cached account snapshot** refreshed on a cadence (e.g., balance/pending count)

Modes and base URLs are controlled by environment variables:

- `env_mode`: `mock` or `real` (selected by `POST /system/start`)
- `ROOSTOO_MOCK_BASE_URL` / `ROOSTOO_REAL_BASE_URL` (optional overrides)

Credentials are sourced from `.env` (see `.env.sample`), primarily via:

- `General_Portfolio_Testing_API_KEY` / `General_Portfolio_Testing_API_SECRET`
- optionally `Competition_API_KEY` / `Competition_API_SECRET`

#### `MarketEngine` (market data + indicators)

`src/engines/engine_market.py:MarketEngine` maintains bar buffers and symbol snapshots used by strategies and valuations. It fetches klines from Binance (`/api/v3/klines`) on a throttled schedule and computes indicator helpers (e.g., ATR and pattern checks) consumed by strategies.

#### `StrategyEngine` (strategies + holdings/PnL)

`src/engines/engine_strategy.py:StrategyEngine` manages:

- strategy instance lifecycle (add/init/start/stop/delete)
- holdings accounting based on order updates
- mark-to-market PnL valuation using latest market data

Available strategies are currently defined in a hard-coded mapping (`AVAILABLE_STRATEGIES`) and instantiated by name.

#### `RiskEngine` (risk boundary)

`src/engines/engine_risk.py:RiskEngine` is present as an architectural boundary but currently contains placeholder logic (`pass` on order/timer hooks). The intended integration point is that it observes orders/ticks and can emit risk alerts without owning execution.

### State and persistence surfaces

#### Orders DB (`OrderStore`)

`src/control/order_store.py:OrderStore` persists orders in SQLite at `data/orders/orders.db` using:

- `orders_latest`: latest row per `order_id` (used for UI queries)
- `order_updates`: append-only history

The engine writes order updates as it polls Roostoo order status. The control API exposes a read-only view:

- `GET /orders`: queries SQLite and returns rows even if the engine is stopped.

#### Logs (`LogStore`, disk rotation, SSE)

`src/control/log_store.py:LogStore` keeps a bounded in-memory tail and supports subscribers (async queues) used by SSE.

`MainEngine.write_log()` writes to:

- the in-memory `LogStore` (for UI and streaming)
- a rotating disk log (defaults `data/logs/system.log`)

Log rotation knobs:

- `LOG_FILE` (default `data/logs/system.log`)
- `LOG_MAX_BYTES` (default `5_000_000`)
- `LOG_BACKUP_COUNT` (default `5`)

Control API endpoints:

- `GET /logs/tail?n=...`: last \(n\) lines (empty if engine not running)
- `GET /logs/stream`: SSE stream (returns a valid stream even when engine is stopped)

## Control plane (FastAPI) contract

### App construction

The FastAPI app is built by `src/control/api.py:create_app(engine_manager)` and is responsible for:

- **CORS**:
  - `CONTROL_CORS_ORIGINS` (comma-separated list)
  - when `ENVIRONMENT=local`, dev origins for Vite (`http://localhost:5173`, `http://127.0.0.1:5173`) are always allowed
- **Admin token auth (optional)**:
  - if `CONTROL_ADMIN_TOKEN` is set, privileged endpoints require `x-admin-token: <token>`
  - if unset, all endpoints are effectively open (dev convenience)

### Endpoint inventory (source of truth: `src/control/api.py`)

- **System**
  - `GET /system/status`
  - `POST /system/start` with `{ "mode": "mock" | "real" }`
  - `POST /system/stop`
  - `GET /health`
- **Auth**
  - `GET /auth/check`
- **Strategies**
  - `GET /strategies/available`
  - `GET /strategies/running`
  - (removed) `POST /strategies/add` — strategies are created on system init
  - `POST /strategies/start`
  - `POST /strategies/stop`
  - (removed) `POST /strategies/delete` — strategies are created on system init and not deleted
- **Positions / holdings**
  - `GET /positions`
- **Market pairs**
  - `GET /pairs`
- **Account (cached; does not trigger exchange calls)**
  - `GET /account/balance`
  - `GET /account/pending_count`
  - `GET /account/orders`
- **Orders DB**
  - `GET /orders`
- **Logs**
  - `GET /logs/tail`
  - `GET /logs/stream` (SSE)

## Frontend architecture (React + Vite)

### UI structure and data access pattern

The dashboard lives in `frontend/` and is a single-page app:

- `frontend/src/App.tsx`: global layout, polling loop, and log stream wiring
- `frontend/src/lib/api.ts`: typed-ish API client wrapper around `fetch()`
- Panels in `frontend/src/components/`:
  - `StrategiesPanel.tsx`
  - `AccountPanel.tsx`
  - `OrdersPanel.tsx`
  - `LogsPanel.tsx`

Data access is split deliberately:

- **Polling snapshots**: the app polls status/strategies/positions (and account snapshots when authed) on a fixed cadence.
- **Streaming logs**: the app opens an `EventSource` to `/logs/stream` for live logs.
- **No direct exchange calls from the browser**: exchange traffic is confined to `GatewayEngine` in the backend.

### Configuration

- Backend base URL: `VITE_API_BASE` (see `frontend/.env.example`), defaults to `http://localhost:8000`.
- Admin token: stored in `localStorage` and sent as `x-admin-token`.

## Operational notes and known gaps

These are current design realities (not aspirations):

- There is **no `/symbols` endpoint** in the control API (despite some older documentation references).
- `RiskEngine` is an architectural placeholder; risk logic is not yet implemented.
- Some older scripts/tests may be stale relative to the current strategy creation APIs.


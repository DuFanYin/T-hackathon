# T-hackathon — Architecture (current)

Single-process Python trading engine, **FastAPI** control plane, **React (Vite)** operator UI. Exchange traffic stays inside `GatewayEngine`; the browser never calls Roostoo directly.

## Repository layout

| Path | Role |
|------|------|
| `api_server.py` | Loads `.env`, starts Uvicorn, wires `EngineManager` → FastAPI app |
| `src/control/api.py` | HTTP routes (system, strategies, positions, account snapshots, orders DB, logs tail) |
| `src/control/engine_manager.py` | Start/stop `MainEngine` (`mock` \| `real`) |
| `src/engines/` | `MainEngine`, `EventEngine`, `MarketEngine`, `GatewayEngine`, `StrategyEngine` |
| `src/strategies/` | `StrategyTemplate` + `factory/*` strategies |
| `data/orders/orders.db` | SQLite (filled orders via `OrderStore`) |
| `data/logs/system.log` | Rotating file logs (default; override `LOG_FILE`) |
| `frontend/` | Dashboard: polling + manual log tail |
| `scripts/` | Standalone utilities (not required for the service) |

## System overview

```text
                    HTTP (fetch)              engine lifecycle
┌─────────────────────────┐    ┌──────────────────────────────────────┐
│ React dashboard         │───▶│ FastAPI (src/control/api.py)       │
│ frontend/               │    │ CORS, snapshots, start/stop        │
└─────────────────────────┘    └──────────────────┬───────────────────┘
                                                  │
                                      ┌───────────▼───────────┐
                                      │ EngineManager         │
                                      │ start/stop MainEngine │
                                      └───────────┬───────────┘
                                                  │ creates
                                      ┌───────────▼───────────┐
                                      │ MainEngine            │
                                      └───┬─────────┬────┬────┘
                                          │         │    │
                            ┌─────────────▼──┐  ┌───▼────▼────────────┐
                            │ EventEngine    │  │ MarketEngine        │
                            │ timer + queue  │  │ Binance klines      │
                            └────────┬───────┘  └────────────────────┘
                                     │
                            ┌────────▼───────────┐  ┌──────────────────┐
                            │ GatewayEngine      │  │ StrategyEngine   │
                            │ Roostoo REST       │  │ strategies + PnL│
                            └────────┬───────────┘  └──────────────────┘
                                     │
                            ┌────────▼───────────┐
                            │ OrderStore (SQLite)│
                            │ LogStore + disk    │
                            └────────────────────┘
```

## Process and concurrency

- **One Python process** for API + engine.
- `EventWorker` + **timer thread** (~1s): emits timer ticks; engines run the tick pipeline in order (market → gateway → strategy PnL → strategy timers).
- **EngineManager**
  - **Start**: `MainEngine(env_mode)` — `env_mode` is `mock` or `real` from `POST /system/start`.
  - **Stop**: refuses if any strategy is still **started**; then stops `EventEngine` and drops the engine reference. HTTP server keeps running.

## Gateway: mode, URL, keys

- Default Roostoo host is the same for mock/real (`https://mock-api.roostoo.com`); optional overrides: `ROOSTOO_MOCK_BASE_URL`, `ROOSTOO_REAL_BASE_URL`.
- **`live`** in `MainEngine` / scripts is normalized to **`real`** inside `GatewayEngine`.
- **Key selection (default):**
  - **`mock`** → `General_Portfolio_Testing_API_KEY` / `General_Portfolio_Testing_API_SECRET`
  - **`real` / `live`** → `Competition_API_KEY` / `Competition_API_SECRET`  
  (`use_competition_keys` can override explicitly.)

## Gateway timer cadence

- `GatewayEngine.on_timer()` runs **every 10** event-engine ticks (~10s if tick = 1s): order polling + `_refresh_account_cache()` (`/v3/balance` + pending `query_order`).

## Control plane vs exchange

- **`/account/*`** returns **cached** gateway snapshots (no per-request Roostoo calls).
- **`GET /orders`** reads **SQLite** (works when engine is stopped).

## Logs

- **`GET /logs/tail?n=...`**: reads the rotating log file (last *n* non-empty lines).
- **No `GET /logs/stream` (SSE)** in the current API — the UI uses **polling** (`App.tsx` refreshes state every **3s**) and the Logs tab uses **manual tail** (`api.logsTail()`).

## Frontend

- `frontend/src/App.tsx`: 3s poll for system/strategies/positions/account.
- `frontend/src/components/`: `Sidebar`, `StrategiesPanel`, `AccountValuePanel`, `OrdersPanel`, `LogsPanel`, `StrategyHealthPanel`.
- Base URL: `VITE_API_BASE` (default `http://localhost:8000`).

## API surface

Authoritative list: **`src/control/api.py`** (decorated routes). This doc avoids duplicating every path; see the file for additions.

## Scripts (examples)

- `scripts/run_system_background.py` — long-running `MainEngine` + selected strategies.
- `scripts/check_roostoo_api.py` — smoke test against Roostoo.
- `scripts/show_account_balance_and_holding.py` — direct signed balance/query (debug).

## Strategy docs

Per-strategy detail: `doc/strategies/*.md`.

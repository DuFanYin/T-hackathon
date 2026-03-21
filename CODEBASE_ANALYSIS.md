# T-Hackathon — Codebase Analysis

## Overview

T-Hackathon is an **event-driven cryptocurrency trading engine** with a FastAPI control plane and a React dashboard. It executes automated trading strategies on the Roostoo exchange, supports mock (paper) and live trading modes, and provides real-time monitoring via a web UI.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS |
| Exchange APIs | Roostoo (v3, HMAC-SHA256 auth), Binance (public klines) |
| Database | SQLite (filled orders) |
| Testing | Pytest |
| Deployment | AWS EC2, Session Manager, tmux, ngrok |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│           React Dashboard (frontend/)           │
│     Polling (3s) + SSE for live log stream      │
└────────────────┬────────────────────────────────┘
                 │ HTTP
┌────────────────▼────────────────────────────────┐
│       FastAPI Control Plane (api_server.py)      │
│   CORS · optional x-admin-token auth · 20+ routes│
└────────────────┬────────────────────────────────┘
                 │ EngineManager
┌────────────────▼────────────────────────────────┐
│              MainEngine (composition root)        │
├─────────────────────────────────────────────────┤
│  EventEngine ─ event router + 1s timer thread    │
│  MarketEngine ─ Binance klines, ATR, pivots      │
│  GatewayEngine ─ Roostoo REST, order polling     │
│  StrategyEngine ─ strategy registry, holdings    │
│  OrderStore (SQLite) · LogStore (in-memory tail) │
└─────────────────────────────────────────────────┘
```

**Timer tick flow (every 1s):**

1. `MarketEngine.on_timer()` — refresh OHLC bars from Binance
2. `GatewayEngine.on_timer()` — poll order status, refresh account
3. `StrategyEngine.process_timer_event()` — mark-to-market PnL
4. `StrategyEngine.on_timer()` — run each strategy's logic

---

## Directory Structure

```
T-hackathon/
├── src/
│   ├── engines/           # Core engine modules
│   │   ├── engine_main.py       # Composition root, lifecycle
│   │   ├── engine_event.py      # Event router + timer thread
│   │   ├── engine_gateway.py    # Roostoo REST adapter + order polling
│   │   ├── engine_market.py     # Binance klines, ATR, pivot indicators
│   │   └── engine_strategy.py   # Strategy registry & holdings accounting
│   ├── strategies/        # Trading strategy implementations
│   │   ├── template.py          # Base class (StrategyTemplate)
│   │   └── factory/
│   │       ├── strategy_maliki.py   # 48h momentum rotation
│   │       ├── strategy_JH.py      # 15m support-bounce scalper
│   │       └── strat_test_alt.py   # Simple BUY/SELL heartbeat (testing)
│   ├── control/           # HTTP API + lifecycle
│   │   ├── api.py               # FastAPI routes (20+ endpoints)
│   │   ├── engine_manager.py    # Engine lifetime management
│   │   ├── order_store.py       # SQLite persistence (filled orders)
│   │   └── log_store.py         # In-memory log formatting
│   └── utilities/         # Shared models & constants
│       ├── object.py            # Data models (OrderData, BarData, etc.)
│       ├── events.py            # Event type constants
│       ├── intents.py           # Intent type constants
│       ├── interval.py          # Candle interval enum
│       └── base_engine.py       # Base class for all engines
├── frontend/
│   └── src/
│       ├── App.tsx              # Root layout, polling loop, tab router
│       ├── components/
│       │   ├── Sidebar.tsx          # Auth, engine start/stop, status
│       │   ├── StrategiesPanel.tsx   # Strategy table, holdings, controls
│       │   ├── AccountValuePanel.tsx # Balance, equity, P&L
│       │   ├── OrdersPanel.tsx      # Cached orders table
│       │   └── LogsPanel.tsx        # Scrollable live log viewer
│       └── lib/
│           ├── api.ts           # Typed fetch wrapper + admin token
│           └── types.ts         # TypeScript interface definitions
├── tests/                 # Unit + integration tests
├── scripts/               # Utility scripts (API checks, flatten, debug)
├── api_server.py          # Entrypoint: loads .env, starts FastAPI
├── run_engine.py          # Standalone CLI engine runner (no API)
├── run_backend.sh         # Deployment script (venv, deps, run)
├── smoke_test.py          # End-to-end verification (20s run)
├── requirements.txt       # Python dependencies
└── .env.sample            # Environment variable template
```

---

## API Endpoints

| Group | Endpoint | Method | Description |
|-------|----------|--------|-------------|
| **System** | `/health` | GET | Health check |
| | `/system/status` | GET | Engine running state |
| | `/system/start` | POST | Start engine (`mode: mock\|real`) |
| | `/system/stop` | POST | Stop engine |
| **Auth** | `/auth/check` | GET | Validate admin token |
| **Strategies** | `/strategies/available` | GET | List all registered strategies |
| | `/strategies/running` | GET | Running strategies + holdings |
| | `/strategies/start` | POST | Start a strategy by name |
| | `/strategies/stop` | POST | Stop a strategy by name |
| **Positions** | `/positions` | GET | Current holdings per strategy |
| | `/positions/close` | POST | Close a specific position |
| | `/positions/close_all` | POST | Close all positions |
| **Account** | `/account/balance` | GET | Wallet balance (cached) |
| | `/account/pending_count` | GET | Pending order count |
| | `/account/orders` | GET | In-memory order cache |
| | `/account/pnl` | GET | Equity & P&L snapshot |
| **Orders** | `/orders` | GET | Query SQLite order history |
| **Market** | `/pairs` | GET | All discovered trading pairs |
| **Logs** | `/logs/tail` | GET | Last N log lines |
| | `/logs/stream` | GET | SSE live log stream |

---

## Trading Strategies

### 1. StrategyMaliki — 48h Momentum Rotation

| Parameter | Value |
|-----------|-------|
| Lookback | 576 × 5m bars (48 hours) |
| Concentration | Top 1 asset |
| Rebalance | Every 288 ticks (24h) |
| Trailing stop | 8% below peak |
| Min hold | 24 hours |
| Min momentum | 3.0% |
| Capital | $20,000 |
| Universe | 42 coins (large cap + mid cap + meme) |

**Logic:**
1. Check BTC regime — if BTC is below its 48h moving average, stay in cash.
2. Rank all symbols by 48h return (momentum).
3. Enter the highest-momentum asset; exit if #1 changes (after 24h min hold).
4. Apply 8% trailing stop-loss after the hold period.

### 2. StrategyJH — 15m Support Bounce Scalper

| Parameter | Value |
|-----------|-------|
| Interval | 15 minutes |
| Pivot length | 5 bars |
| Risk/Reward | 2.0× |
| ATR length | 14 |
| Capital | $20,000 |
| Risk per trade | 1% |
| Universe | 8 pairs (APT, CRV, EIGEN, TAO, UNI, TRUMP, BONK, SHIB) |

**Logic:**
1. Identify support (pivot low over 5-bar window).
2. Wait for price to bounce near support ~2 times.
3. Enter on third touch; stop below support; target at 2× risk/reward.
4. Monitor exits every 5m (stop/target hit or timeout).

### 3. StratTestAlt — Heartbeat Test

- **Asset:** BTCUSDT only
- **Pattern:** Alternating BUY → SELL every minute
- **Purpose:** Plumbing verification and smoke testing

---

## Account PnL (dashboard)

`MainEngine.get_account_pnl()` compares cached USD/USDT wallet equity (from `GatewayEngine.get_cached_balance()`) to a fixed baseline (default **$50,000**) and powers `GET /account/pnl` for the UI. There is no drawdown / auto-stop engine.

---

## Data Flow

```
Binance (klines) ──► MarketEngine ──► bars + indicators (ATR, pivots)
                                          │
                                          ▼
Roostoo (REST) ◄──► GatewayEngine ──► order fills ──► StrategyEngine
       │                                                    │
       │                                                    ▼
       └── balance/orders ──► cached snapshots (control API / UI)
                                          │
                                          ▼
                                     LogStore ──► SSE ──► Dashboard
```

- **Market data** comes from Binance (public, no auth).
- **Order execution** goes through Roostoo (HMAC-SHA256 signed).
- **Order status** is polled every ~10 ticks from Roostoo.
- **Holdings** are computed from fill deltas, mark-to-market priced via MarketEngine.
- **Frontend** polls the control API every 3 seconds and streams logs via SSE.

---

## Environment Configuration

Key variables from `.env.sample`:

| Variable | Description |
|----------|-------------|
| `General_Portfolio_Testing_API_KEY` / `_SECRET` | Roostoo API credentials (testing) |
| `Competition_API_KEY` / `_SECRET` | Roostoo API credentials (competition) |
| `ENVIRONMENT` | `local` or `cloud` |
| `CONTROL_HOST` | API bind address (default `0.0.0.0`) |
| `CONTROL_PORT` | API port (default `8000`) |
| `CONTROL_CORS_ORIGINS` | Allowed CORS origins |
| `CONTROL_ADMIN_TOKEN` | Optional auth token |
| `ROOSTOO_MOCK_BASE_URL` | Mock exchange URL |
| `ROOSTOO_REAL_BASE_URL` | Live exchange URL |

---

## Testing

```bash
pytest tests/ -v
```

| Test File | Coverage |
|-----------|----------|
| `test_engine_main.py` | MainEngine lifecycle (add/get/start/stop strategy) |
| `test_engine_strategy.py` | Holdings accounting (apply fills, mark-to-market) |
| `test_engine_manager.py` | EngineManager start/stop, mode tracking |
| `test_strategies.py` | All three strategies (construction, history reqs, on_timer) |
| `test_utilities.py` | Event objects, order models, position data |
| `test_integration_strategy_positions.py` | End-to-end: fill → holdings → PnL |
| `test_integration_strategies.py` | Multi-strategy integration, order polling |

**Smoke test:** `python smoke_test.py` — creates engine, adds strategies, runs 20s, verifies state.

---

## Deployment

### Local Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env  # fill in credentials
python api_server.py mock          # backend on :8000
cd frontend && npm install && npm run dev  # frontend on :5173
```

### AWS EC2 (Production)

1. Connect via **Session Manager** (no SSH keys needed)
2. Create tmux session with 4 windows: api, curl, shell, ngrok
3. Activate venv: `source ~/botenv/bin/activate`
4. Pull latest: `git pull origin main`
5. Run backend: `python api_server.py mock` (window 0)
6. Expose via ngrok: `ngrok http 8000` (window 3)

See `README_DEPLOY.md` for full step-by-step instructions.

---

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `scripts/check_roostoo_api.py` | Test all Roostoo v3 endpoints |
| `scripts/flatten_account.py` | Emergency: cancel all pending, market-sell everything |
| `scripts/submit_pending_orders.py` | Manually submit pending order queue |
| `scripts/debug_order_parse.py` | Place order, query status, debug raw response |
| `run_backend.sh` | Kill port 8000, recreate venv, install deps, run server |
| `run_engine.py` | Standalone CLI engine (no API); runs until Ctrl+C |

---

## Key Design Patterns

1. **Event-driven** — single `EventEngine` with queue + timer thread; deterministic routing order
2. **Strategy template** — all strategies extend `StrategyTemplate` with `on_timer_logic()`, `on_order()`
3. **Intent system** — strategies emit intents (place/cancel orders, logs) instead of calling engines directly
4. **Cached snapshots** — control API returns cached state; UI never triggers exchange calls
5. **Per-strategy holdings** — fill deltas tracked per strategy; mark-to-market on every tick
6. **SQLite persistence** — filled orders written to SQLite; queryable even when engine is stopped
7. **Rotating logs** — 5 MB per file, 5 backups; in-memory bounded tail for SSE fanout

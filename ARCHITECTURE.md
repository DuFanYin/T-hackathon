# T-hackathon Architecture

High-level design of the trading engine, control plane, and dashboard.

---

## System overview

- **Trading core**: event‑driven engine that owns market data, strategies, positions, and risk.
- **Control plane**: HTTP API that exposes a small surface for starting/stopping the engine and inspecting state.
- **Dashboard**: React SPA that consumes the control API and presents a card‑based, read‑only/low‑touch UI.

The goal is a clear separation between **algorithmic logic** (core) and **operations UX** (control + dashboard).

---

## Backend architecture

### Engines (domain layer)

- **Main engine**
  - Knows which engines exist and how they are wired.
  - Owns the system lifecycle in a given environment mode (`mock` or `real`).
- **Event routing**
  - Central queue and timer that define the order in which engines see events.
  - Provides a single place where the “tick pipeline” is defined.
- **Market**
  - Holds the current view of symbols, prices, and simple aggregates.
  - Acts as the canonical source of market data for the rest of the system.
- **Strategies**
  - Registry of strategy instances keyed by name.
  - Responsible for driving strategy lifecycles and forwarding relevant events.
- **Positions**
  - Maintains per‑strategy holdings and PnL.
  - Reads from market data to value positions.
- **Risk**
  - Observes orders and timer activity.
  - Emits risk‑related events and signals without owning execution.

All engines are treated as peers coordinated by the main engine and the event router.

### Control API (service layer)

- **Engine manager**
  - Wraps the main engine in a small, mode‑aware controller.
  - Exposes “running vs stopped” status and start/stop operations.
- **HTTP surface**
  - Thin FastAPI app that translates HTTP requests to engine‑level operations.
  - Endpoints are grouped by concern: system, strategies, positions, symbols, logs.
- **Representation**
  - Uses simple JSON shapes for strategies, holdings, and symbols.
  - Treats the engine as the single source of truth for all derived values.

The control API is intentionally narrow so the engine can evolve without reshaping external contracts often.

---

## Frontend architecture

### Layout and navigation

- **Shell**
  - Two‑column layout: fixed sidebar + main content area.
  - Shared header bar in the main area that reflects the active tab.
- **Tabs**
  - `System` – focuses on global engine state and environment mode.
  - `Strategies` – focuses on individual strategy instances and their portfolio impact.
  - `Symbols` – focuses on market‑wide symbol snapshots.
  - `Logs` – focuses on temporal diagnostics and textual output.

Each tab is designed as a single, focused “panel” rather than a multi‑page app.

### Panels and interactions

- **System panel**
  - Single card that mirrors engine status and mode.
  - Small set of high‑impact actions for starting and stopping the system.
- **Strategies panel**
  - Top control row for selecting a strategy type and symbol, plus lifecycle actions.
  - Table that lists running strategies with a compact view of state and basic PnL.
- **Symbols panel**
  - Read‑only table of symbol snapshots.
  - Visual hints for short‑term price direction and 24h change.
- **Logs panel**
  - Tail view of the most recent log lines.
  - Controls for pulling a finite tail, clearing, and toggling a live stream.

All interactions route through the control API; the frontend does not access exchange endpoints directly.

---

## Data and control flow

### From market to dashboard

1. Exchange produces prices and other market data.
2. Gateway/market engines normalize this into internal symbol and bar state.
3. Positions and strategies consume that state and update their own views.
4. Control API exposes summarized snapshots for symbols, positions, and strategies.
5. Dashboard polls or streams those snapshots into tab‑specific components.

### From user intent to execution

1. User interacts with a dashboard control (e.g., “start system”, “add strategy”).
2. Frontend calls the corresponding control API endpoint.
3. Control API routes the request to the engine manager or main engine.
4. Engine updates internal state and triggers any necessary follow‑up events.
5. Updated state becomes visible again through status, strategies, positions, and logs.

The design keeps **user intent**, **control API**, and **engine behavior** as distinct steps.

---

## Deployment view

- **Engine + control API**
  - Runs as a long‑lived Python process.
  - Listens on a single HTTP port for control and monitoring traffic.
- **Dashboard**
  - Runs as a static web app (Vite dev server locally, any static host in production).
  - Talks to the control API over HTTP/S using the configured base URL.

This separation allows the engine to be deployed close to the exchange, while the UI can live wherever is convenient for operators.


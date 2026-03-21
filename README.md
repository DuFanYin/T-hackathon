# T-hackathon

Event-driven crypto trading engine with a lightweight **HTTP control API** and **React dashboard**.

---

## What’s here

- **Core engine** under `src/` (main, market, strategy, gateway, event).
- **HTTP control API** (`api_server.py` + `src/control/*`), powered by FastAPI.
- **Web dashboard** in `frontend/` (React + TypeScript + Vite) with a gray, card-based UI:
  - `System` tab – start/stop engine in `mock` or `real` mode and see health.
  - `Strategies` tab – add/init/start/stop/delete strategies and see PnL/positions.
  - `Symbols` tab – live market snapshots for all symbols.
  - `Logs` tab – tail and stream engine logs.

---

## Backend setup

1. **Install deps**

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. **Env config** (repo root `.env`)

   See `.env.sample`; typical keys:

   - `General_Portfolio_Testing_API_KEY`
   - `General_Portfolio_Testing_API_SECRET`
   - Optional `ROOSTOO_MOCK_BASE_URL` / `ROOSTOO_REAL_BASE_URL`
   - Optional `CONTROL_HOST` / `CONTROL_PORT` / `CONTROL_CORS_ORIGINS`

3. **Run control API**

   ```bash
   # mock (paper) mode
   python api_server.py mock

   # or real mode
   python api_server.py real
   ```

   This creates the engine, loads `strategies_config.json`, and exposes endpoints such as:

   - `GET /system/status`, `POST /system/start`, `POST /system/stop`
   - `GET /strategies/available`, `GET /strategies/running`
   - `POST /strategies/start|stop`
   - `GET /positions`, `GET /symbols`
   - `GET /logs/tail`, `GET /logs/stream` (SSE)

---

## Frontend setup

From `frontend/`:

```bash
cd frontend
npm install
npm run dev
```

By default the app assumes the backend is on `http://localhost:8000` (configurable via `VITE_API_BASE` in `frontend/.env`).

Tabs talk to the control API:

- `System` → `/system/*`, `/health`
- `Strategies` → `/strategies/*`, `/positions`, `/pairs`
- `Symbols` → `/symbols`
- `Logs` → `/logs/tail`, `/logs/stream`

---

## Running everything together

1. Start backend control API:

   ```bash
   python api_server.py mock
   ```

2. Start frontend dev server:

   ```bash
   cd frontend
   npm run dev
   ```

3. Open the URL from Vite (typically `http://localhost:5173`) and use the UI instead of CLI.

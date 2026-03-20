# T-hackathon — AWS EC2 deployment (trading bot + ngrok)

Step-by-step guide from a fresh **AWS Systems Manager Session Manager** shell to a running control API, ngrok tunnel, and started strategies.

## Environment (reference)

| Item | Value |
|------|--------|
| **Instance** | `i-0ee561b11745cc7b6`, `t3.medium`, **ap-southeast-2** |
| **OS** | Amazon Linux 2023 (`dnf`, not `apt`) |
| **Python** | 3.11 |
| **Virtual env** | `~/botenv` |
| **Repo** | `~/T-hackathon` |
| **Access** | **Session Manager** (no SSH key required) |

> Replace example values (ngrok URL, admin token) with your team’s real values if they differ.

---

## 1. Connect via Session Manager

1. Open **AWS Console** → **EC2** → **Instances** → select the instance.
2. **Connect** → **Session Manager** → **Connect**.
3. A browser shell opens; you are logged in as the default user (often `ssm-user` or `ec2-user`).

---

## 2. tmux layout (recommended)

Use **tmux** so the API and ngrok keep running after you disconnect.

### Attach to an existing session (if you already created one)

```bash
tmux attach -t bot
```

### Create a new session with 4 windows

```bash
tmux new -s bot
```

Suggested layout:

| Window | Name (optional) | Purpose |
|--------|-----------------|--------|
| **0** | `api` | Control API: `python3 api_server.py` |
| **1** | `curl` | `curl` tests against `localhost:8000` |
| **2** | `shell` | General bash, `git pull`, edits |
| **3** | `ngrok` | `ngrok http 8000` |

**Create extra windows** (from inside tmux): `Ctrl+B` then `c` (new window). Rename: `Ctrl+B` then `,`.

**Switch windows**: `Ctrl+B` then `0` / `1` / `2` / `3`.

**Detach** (leave everything running): `Ctrl+B` then `D`.

**Reattach later**:

```bash
tmux attach -t bot
```

### tmux quick reference

| Action | Keys |
|--------|------|
| Switch window | `Ctrl+B` then `0`–`9` |
| Detach | `Ctrl+B` then `D` |
| Scroll / copy mode | `Ctrl+B` then `[` — scroll with arrows; **`q`** to exit |
| List sessions | `tmux ls` |

---

## 3. Activate the virtual environment

Every new shell (or new tmux window) that runs Python should use:

```bash
source ~/botenv/bin/activate
```

Prompt should show `(botenv)`.

---

## 4. Pull latest code

```bash
cd ~/T-hackathon
git pull origin main
```

Resolve any merge conflicts if prompted, then reinstall deps if `requirements.txt` changed:

```bash
pip install -r requirements.txt
```

---

## 5. Clear stale environment variables (optional but recommended)

If you previously exported API keys in the shell, they can override `.env` and cause confusing behavior. In the shell **before** starting the API:

```bash
unset General_Portfolio_Testing_API_KEY General_Portfolio_Testing_API_SECRET
unset Competition_API_KEY Competition_API_SECRET
```

Keys for the running process should come from **`~/T-hackathon/.env`** (not committed to git). Edit with `nano` / `vim` if needed:

```bash
cd ~/T-hackathon
nano .env
```

Ensure at minimum:

- `CONTROL_ADMIN_TOKEN` — must match the `x-admin-token` you use in `curl`
- Roostoo keys as required for mock vs real (see `.env.sample`)

---

## 6. Start the API server

In **window 0** (or any dedicated window), with venv activated:

```bash
cd ~/T-hackathon
source ~/botenv/bin/activate
python3 api_server.py
```

You should see something like: `[API] Listening on http://0.0.0.0:8000`

- Default port: **8000** (override with `CONTROL_PORT` in `.env`).
- Leave this process running.

---

## 7. Start ngrok (public HTTPS URL)

In **window 3**, with venv **not** required for ngrok:

```bash
ngrok http 8000
```

**Notes:**

- **Auth**: `ngrok config add-authtoken …` is already done on this host (one-time).
- **Free tier**: only **one** tunnel at a time. If you see **“endpoint already online”** or a stuck tunnel:

  ```bash
  pkill ngrok
  ngrok http 8000
  ```

- **Public URL**: ngrok prints an `https://….ngrok-free.dev` URL (example used by the team: `https://marlyn-auntlike-verla.ngrok-free.dev`). **Copy the URL from your ngrok output** — it can change if you recreate the tunnel.

**Frontend (Vercel):** set the app’s API base URL to this HTTPS origin (and ensure `CONTROL_CORS_ORIGINS` in `.env` includes your Vercel origin — see `.env.sample`).

---

## 8. Start engine and strategies (`curl`)

Use **window 1** or any shell. Replace `1234` with your real **`CONTROL_ADMIN_TOKEN`** from `.env`.

**Admin header** (required when `CONTROL_ADMIN_TOKEN` is set):

```text
-H "x-admin-token: 1234"
```

### 8.1 Start the trading engine (mock/paper)

```bash
curl -s -X POST http://localhost:8000/system/start \
  -H "Content-Type: application/json" \
  -H "x-admin-token: 1234" \
  -d '{"mode": "mock"}'
```

Expected: JSON with `"running": true`, `"mode": "mock"`.

### 8.2 Start `strategy_maliki`

```bash
curl -s -X POST http://localhost:8000/strategies/start \
  -H "Content-Type: application/json" \
  -H "x-admin-token: 1234" \
  -d '{"name": "strategy_maliki"}'
```

### 8.3 Start `strategy_JH`

```bash
curl -s -X POST http://localhost:8000/strategies/start \
  -H "Content-Type: application/json" \
  -H "x-admin-token: 1234" \
  -d '{"name": "strategy_JH"}'
```

> Strategies are registered when `MainEngine` starts; `start` runs init + backfill as needed. If a name 404s, check `GET /strategies/available`.

---

## 9. Verify

Replace `1234` with your admin token.

```bash
# Engine status (no admin required for this endpoint)
curl -s http://localhost:8000/system/status

# Running strategies
curl -s -H "x-admin-token: 1234" http://localhost:8000/strategies/running

# Account balance (cached)
curl -s -H "x-admin-token: 1234" http://localhost:8000/account/balance

# Positions
curl -s -H "x-admin-token: 1234" http://localhost:8000/positions
```

**Through ngrok** (from your laptop or for the frontend):

```bash
curl -s https://YOUR-SUBDOMAIN.ngrok-free.dev/system/status
```

---

## 10. Share URL with teammate (Vercel frontend)

1. Copy the **HTTPS** URL from the ngrok terminal (e.g. `https://marlyn-auntlike-verla.ngrok-free.dev`).
2. Teammate sets **Vite** `VITE_API_BASE` (or equivalent) to that origin **without** trailing slash.
3. Ensure EC2 `.env` has `CONTROL_CORS_ORIGINS` including the Vercel app URL (comma-separated, no extra quotes).

---

## 11. Detach tmux (keep bot running)

1. `Ctrl+B` then `D` — session keeps running in the background.
2. Close the Session Manager tab safely; processes inside tmux continue until the instance stops or you stop them.

To stop strategies/engine later, use `POST /strategies/stop` and `POST /system/stop` with the same admin token (stop strategies first if required by the API).

---

## Switching to competition / “live” mode

1. **`.env` on EC2**
   - Set `ENVIRONMENT=cloud` if your gateway uses **Competition** API keys (see `src/engines/engine_gateway.py` and `.env.sample`).
   - Set `Competition_API_KEY` / `Competition_API_SECRET` (and/or testing keys) as required by Roostoo.

2. **Restart the API server** (stop with `Ctrl+C` in the API tmux window, then start again).

3. **Start engine in live mode**

   ```bash
   curl -s -X POST http://localhost:8000/system/start \
     -H "Content-Type: application/json" \
     -H "x-admin-token: 1234" \
     -d '{"mode": "real"}'
   ```

   Use **`"mode": "real"`** for live/competition trading (not `"mock"`).

4. **Restart strategies** as in section 8 if needed.

> Always confirm keys, mode, and risk limits before switching from mock to real.

---

## Monitoring commands (copy-paste)

Admin token required where shown (same as `CONTROL_ADMIN_TOKEN`).

```bash
export TOKEN=1234   # set to your real token

curl -s http://localhost:8000/system/status

curl -s -H "x-admin-token: $TOKEN" http://localhost:8000/strategies/running

curl -s -H "x-admin-token: $TOKEN" http://localhost:8000/account/balance

curl -s -H "x-admin-token: $TOKEN" http://localhost:8000/positions

curl -s -H "x-admin-token: $TOKEN" "http://localhost:8000/logs/tail?n=50"
```

---

## Troubleshooting

| Issue | What to try |
|--------|-------------|
| `401` on POST | `x-admin-token` must match `CONTROL_ADMIN_TOKEN` in `.env`. |
| `503` on `/health` | Engine not started; run `POST /system/start` first. |
| ngrok “already online” | `pkill ngrok` then `ngrok http 8000` again. |
| Wrong Python / packages | `source ~/botenv/bin/activate` and `pip install -r requirements.txt`. |
| CORS from Vercel | Add Vercel URL to `CONTROL_CORS_ORIGINS` in `.env` and restart API. |

---

## Related docs

- `README.md` — local dev overview  
- `DEPLOYMENT_AWS.md` — broader AWS / Vercel notes  
- `.env.sample` — variable reference  

#!/usr/bin/env bash
#
# Run backend: kill if running, build env if needed, then start.
# Usage: ./run_backend.sh [--reset]
#   --reset  Remove .venv and recreate (fresh install)
#

set -e
cd "$(dirname "$0")"

RESET_VENV=false
for arg in "$@"; do
  case "$arg" in
    --reset|-r) RESET_VENV=true ;;
  esac
done

# Load CONTROL_PORT from .env if present
if [ -f .env ]; then
  val=$(grep -E '^CONTROL_PORT=' .env 2>/dev/null | cut -d= -f2)
  [ -n "$val" ] && export CONTROL_PORT="$val"
fi
PORT="${CONTROL_PORT:-8000}"
VENV=".venv"

# 1. Kill backend if running on port
echo "[run_backend] Checking for process on port $PORT..."
if command -v lsof &>/dev/null; then
  PIDS=$(lsof -ti ":$PORT" 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "[run_backend] Killing process(es) on port $PORT: $PIDS"
    echo "$PIDS" | xargs kill 2>/dev/null || true
    sleep 2
    REMAIN=$(lsof -ti ":$PORT" 2>/dev/null || true)
    if [ -n "$REMAIN" ]; then
      echo "[run_backend] Force killing: $REMAIN"
      echo "$REMAIN" | xargs kill -9 2>/dev/null || true
      sleep 1
    fi
  else
    echo "[run_backend] No process on port $PORT"
  fi
elif command -v fuser &>/dev/null; then
  fuser -k "$PORT/tcp" 2>/dev/null || true
  sleep 2
else
  echo "[run_backend] WARN: lsof/fuser not found, skipping port kill"
fi

# 2. Check Python version (3.9+ required)
PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0")
if [ "$PYVER" = "0" ]; then
  echo "[run_backend] ERROR: python3 not found"
  exit 1
fi
echo "[run_backend] Python $PYVER"

# 3. Reset or build venv
if [ "$RESET_VENV" = true ]; then
  if [ -d "$VENV" ]; then
    echo "[run_backend] Resetting venv (removing $VENV)..."
    rm -rf "$VENV"
  fi
fi
if [ ! -d "$VENV" ]; then
  echo "[run_backend] Creating venv at $VENV..."
  python3 -m venv "$VENV"
fi

# 4. Activate and ensure deps
echo "[run_backend] Activating venv and installing deps..."
source "$VENV/bin/activate"
pip install -q -r requirements.txt

# 5. Run backend
echo "[run_backend] Starting api_server.py..."
exec python api_server.py

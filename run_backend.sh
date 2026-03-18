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

# 2. Use Python 3.12 (prefer python3.12, fallback to python3)
PYTHON=""
if command -v python3.12 &>/dev/null; then
  PYTHON="python3.12"
elif python3 -c 'import sys; exit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
  PYTHON="python3"
fi
if [ -z "$PYTHON" ]; then
  echo "[run_backend] ERROR: Python 3.12 required. Install: python3.12 or ensure python3 is 3.12+"
  exit 1
fi
PYVER=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")' 2>/dev/null)
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
  $PYTHON -m venv "$VENV"
fi

# 4. Activate and ensure deps
echo "[run_backend] Activating venv and installing deps..."
source "$VENV/bin/activate"
pip install -q -r requirements.txt

# 5. Run backend
echo "[run_backend] Starting api_server.py..."
exec python api_server.py

#!/usr/bin/env bash
#
# Run engine standalone (no API): add and start all strategies.

set -e
cd "$(dirname "$0")"

RESET_VENV=false
for arg in "$@"; do
  case "$arg" in
    --reset|-r|--upgrade-python) RESET_VENV=true ;;
  esac
done

VENV=".venv"

# 1. Force Python 3.12
if ! command -v python3.12 &>/dev/null; then
  echo "[run_engine] ERROR: python3.12 not found. Install: sudo dnf install python3.12"
  exit 1
fi
echo "[run_engine] Python $(python3.12 -c 'import sys; print(sys.version.split()[0])')"

# 2. Reset or build venv
if [ "$RESET_VENV" = true ] && [ -d "$VENV" ]; then
  echo "[run_engine] Resetting venv..."
  rm -rf "$VENV"
fi
if [ ! -d "$VENV" ]; then
  echo "[run_engine] Creating venv..."
  python3.12 -m venv "$VENV"
fi

# 3. Activate and install deps
echo "[run_engine] Activating venv..."
source "$VENV/bin/activate"
pip install -q -r requirements.txt

# 4. Run engine
exec python run_engine.py

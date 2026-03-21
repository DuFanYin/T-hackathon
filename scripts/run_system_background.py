#!/usr/bin/env python3
"""
Run system + both strategies in one process, suitable for background use.

Behavior:
- Creates MainEngine
- Starts strategy_maliki + strategy_JH
- Keeps process alive until SIGINT/SIGTERM

Example:
  nohup python scripts/run_system_background.py > system_bg.log 2>&1 &
"""

from __future__ import annotations

import os
import signal
import sys
import time

from dotenv import load_dotenv

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
load_dotenv(os.path.join(root_dir, ".env"))

from src.engines.engine_main import MainEngine

ENGINE_MODE = "live"
STRATEGIES = ("strategy_maliki", "strategy_JH")

_keep_running = True


def _handle_signal(signum, _frame) -> None:
    global _keep_running
    _keep_running = False
    print(f"[system-bg] received signal={signum}; shutting down...")


def main() -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    engine = MainEngine(env_mode=ENGINE_MODE)
    print(f"[system-bg] engine started (mode={ENGINE_MODE})")

    for name in STRATEGIES:
        try:
            engine.start_strategy(name)
            print(f"[system-bg] started strategy: {name}")
        except Exception as e:
            print(f"[system-bg] failed to start {name}: {e}")
            return 1

    print("[system-bg] running. Press Ctrl+C to stop.")

    try:
        while _keep_running:
            time.sleep(1)
    finally:
        # Keep shutdown simple and safe: stop event loop first.
        try:
            engine.event_engine.stop()
            print("[system-bg] event engine stopped")
        except Exception as e:
            print(f"[system-bg] stop warning: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


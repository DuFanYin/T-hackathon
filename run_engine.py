#!/usr/bin/env python3
"""
Command-line engine runner: start MainEngine, add and start all strategies.

No API server — engine runs standalone. Use Ctrl+C to stop.
Fixed to mock mode.

Usage:
  python run_engine.py
"""

from __future__ import annotations

import os
import signal
import sys
import time

from dotenv import load_dotenv


def main() -> int:
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    load_dotenv(os.path.join(root_dir, ".env"))

    from src.engines.engine_main import MainEngine
    from src.engines.engine_strategy import AVAILABLE_STRATEGIES

    print("[run_engine] Starting MainEngine (mode=mock)...")
    main_engine = MainEngine(env_mode="mock")

    # Add all strategies
    for name in sorted(AVAILABLE_STRATEGIES.keys()):
        try:
            main_engine.add_strategy(name)
            print(f"[run_engine] Added {name}")
        except Exception as e:
            print(f"[run_engine] WARN: add {name} failed: {e}")

    # Start all strategies
    for name in sorted(AVAILABLE_STRATEGIES.keys()):
        strat = main_engine.get_strategy(name)
        if strat is not None:
            try:
                main_engine.start_strategy(name)
                print(f"[run_engine] Started {name}")
            except Exception as e:
                print(f"[run_engine] WARN: start {name} failed: {e}")

    print("[run_engine] Engine running. Ctrl+C to stop.")

    def _shutdown(*_):
        print("\n[run_engine] Shutting down...")
        try:
            # Stop strategies first
            for name in sorted(AVAILABLE_STRATEGIES.keys()):
                strat = main_engine.get_strategy(name)
                if strat is not None:
                    try:
                        main_engine.stop_strategy(name)
                        print(f"[run_engine] Stopped {name}")
                    except Exception as e:
                        print(f"[run_engine] stop {name}: {e}")
        except Exception as e:
            print(f"[run_engine] stop strategies: {e}")
        try:
            main_engine.event_engine.stop()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Block until Ctrl+C
    while True:
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())

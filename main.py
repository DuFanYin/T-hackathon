#!/usr/bin/env python3
"""
Entry point: start trading system and auto-create strategies from JSON config.

Config file (default: strategies_config.json in repo root) is a JSON array:

[
  { "strategy": "Strat1Pine", "symbol": "BTCUSDT" },
  { "strategy": "Strat1Pine", "symbol": "ETHUSDT" }
]

For each entry, main.py will:
1. main.add_strategy(strategy_name, symbol)
2. main.init_strategy(f"{strategy_name}_{symbol}")
3. main.start_strategy(f"{strategy_name}_{symbol}")

Then it keeps running until Ctrl+C, and on exit stops strategies and disconnects.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Dict, List


def _load_config(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Strategy config JSON not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("Strategy config must be a JSON array of objects")
    return data


def main() -> int:
    # Ensure project root is on sys.path
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    from src.engines.engine_main import MainEngine

    # One CLI arg: mock|real
    env_mode = "mock"
    if len(sys.argv) >= 2:
        arg = str(sys.argv[1]).strip().lower()
        if arg in ("mock", "real"):
            env_mode = arg
        else:
            print("[MAIN] Usage: python main.py [mock|real]")
            return 2

    config_path = os.getenv("STRATEGY_CONFIG_PATH", os.path.join(root_dir, "strategies_config.json"))

    try:
        config = _load_config(config_path)
    except Exception as e:
        print(f"[MAIN] Failed to load config '{config_path}': {e}")
        return 1

    print(f"[MAIN] Starting system env_mode={env_mode} config={config_path}")

    try:
        main_engine = MainEngine(env_mode=env_mode)
    except Exception as e:
        print(f"[MAIN] Failed to create MainEngine: {e}")
        return 1

    started_names: List[str] = []

    # Create, init, and start strategies from config
    for entry in config:
        if not isinstance(entry, dict):
            continue
        strategy_name = str(entry.get("strategy", "")).strip()
        symbol = str(entry.get("symbol", "")).strip()
        if not strategy_name or not symbol:
            continue
        full_name = f"{strategy_name}_{symbol}"
        try:
            print(f"[MAIN] Adding strategy {strategy_name} on {symbol} (full name: {full_name})")
            main_engine.add_strategy(strategy_name, symbol)
            main_engine.init_strategy(full_name)
            main_engine.start_strategy(full_name)
            started_names.append(full_name)
        except Exception as e:
            print(f"[MAIN] Failed to add/start {strategy_name} on {symbol}: {e}")

    if not started_names:
        print("[MAIN] No strategies started from config. Exiting.")
        return 0

    print(f"[MAIN] Running. Active strategies: {started_names}")
    print("[MAIN] Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n[MAIN] Caught KeyboardInterrupt, stopping strategies...")

    # Graceful shutdown
    for name in started_names:
        try:
            print(f"[MAIN] Stopping {name}...")
            main_engine.stop_strategy(name)
        except Exception as e:
            print(f"[MAIN] Error stopping {name}: {e}")

    try:
        main_engine.disconnect()
    except Exception as e:
        print(f"[MAIN] Error during disconnect: {e}")

    print("[MAIN] Shutdown complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


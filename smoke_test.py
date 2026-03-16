#!/usr/bin/env python3
"""
End-to-end smoke test: MainEngine + strategy integration.

Uses a real trading pair name (e.g. BTCUSDT) for the strategy instance name.

Run: python smoke_test.py
"""

import os
import sys
import time

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    print("=== T-hackathon Smoke Test ===\n")
    pair = "BTCUSDT"

    # 1. Imports
    print("1. Importing MainEngine and Strat2Momentum...")
    try:
        from src.engines.engine_main import MainEngine
        from src.strategies.factory import Strat1Pine, Strat2Momentum
        from src.engines.engine_strategy import AVAILABLE_STRATEGIES
    except Exception as e:
        print(f"   FAIL: Import error: {e}")
        return 1
    print("   OK\n")

    # 2. Strategy registration
    print("2. Checking AVAILABLE_STRATEGIES...")
    if "Strat2Momentum" not in AVAILABLE_STRATEGIES:
        print("   FAIL: Strat2Momentum not in AVAILABLE_STRATEGIES")
        return 1
    print(f"   OK: {list(AVAILABLE_STRATEGIES.keys())}\n")

    # 3. Create MainEngine
    print("3. Creating MainEngine...")
    try:
        main = MainEngine()
    except Exception as e:
        print(f"   FAIL: {e}")
        return 1
    print("   OK\n")

    # 4. Add Strat2Momentum
    print(f"4. Adding Strat2Momentum ({pair})...")
    try:
        main.add_strategy("Strat2Momentum", pair)
    except Exception as e:
        print(f"   FAIL: {e}")
        return 1
    print("   OK\n")

    # 5. Get strategy and verify
    print("5. Verifying strategy instance...")
    strat = main.get_strategy(f"Strat2Momentum_{pair}")
    if strat is None:
        print("   FAIL: Strategy not found")
        return 1
    if not hasattr(strat, "on_timer_logic"):
        print("   FAIL: Strategy missing on_timer_logic")
        return 1
    print("   OK\n")

    # 6. Init and start strategy
    print("6. Initializing and starting strategy...")
    try:
        main.init_strategy(f"Strat2Momentum_{pair}")
        main.start_strategy(f"Strat2Momentum_{pair}")
    except Exception as e:
        print(f"   FAIL: {e}")
        return 1
    print("   OK\n")

    # 7. Run for ~20 seconds (timer ticks every 1s; Strat2 fetches from Binance every 30s)
    print("7. Running for 20 seconds (timer ticks, Binance fetch, reconciliation)...")
    print("   [LOG] output below:\n")
    time.sleep(20)

    # 8. Stop strategy and disconnect
    print("\n8. Stopping strategy and disconnecting...")
    try:
        main.stop_strategy(f"Strat2Momentum_{pair}")
        main.disconnect()
    except Exception as e:
        print(f"   FAIL: {e}")
        return 1
    print("   OK\n")

    print("=== Smoke test PASSED ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

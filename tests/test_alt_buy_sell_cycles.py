#!/usr/bin/env python3
"""
Integration test:
- Pull BTC data every 3 seconds (via gateway ticker -> market symbol cache)
- Place MARKET BUY/SELL alternately
- Repeat 3 cycles total
"""

from __future__ import annotations

import os
import sys
import time
import unittest

from dotenv import load_dotenv


class TestAltBuySellCycles(unittest.TestCase):
    def test_alt_buy_sell_3_cycles(self) -> None:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

        # Load .env so GatewayEngine sees Roostoo keys.
        load_dotenv(os.path.join(root_dir, ".env"))

        from src.engines.engine_main import MainEngine

        main = MainEngine(env_mode="mock")
        try:
            main.add_strategy("StratTestAlt", "BTCUSDT")
            name = "StratTestAlt_BTCUSDT"
            main.start_strategy(name)

            # Strategy triggers every 3 seconds; 3 cycles * 2 orders = 6 orders.
            # Wait until it reaches 6 attempts (or timeout).
            deadline = time.time() + 30.0
            attempts = 0
            while time.time() < deadline:
                strat = main.get_strategy(name)
                self.assertIsNotNone(strat)
                attempts = int(getattr(strat, "order_attempts", -1))
                if attempts >= 6:
                    break
                time.sleep(0.5)

            strat = main.get_strategy(name)
            self.assertIsNotNone(strat)
            print(f"[TEST] order_attempts={attempts}")
            self.assertEqual(attempts, 6)
        finally:
            main.disconnect()


if __name__ == "__main__":
    unittest.main()


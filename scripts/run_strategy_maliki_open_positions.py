#!/usr/bin/env python3
"""
Engine-direct manual test for `strategy_maliki`.

Creates `MainEngine` in mock mode, initializes `strategy_maliki`, then manually
opens a single position directly via `StrategyTemplate.open_position()`
(engine/direct: no FastAPI control layer, no IPC files, no CLI args).
"""

from __future__ import annotations

import os
import sys
import time

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(root_dir, ".env"))

from src.engines.engine_main import MainEngine

ENGINE_MODE: str = "mock"
STRATEGY_NAME: str = "strategy_maliki"

# Pick a symbol/qty that should be above Roostoo min-notional (in fallback table).
OPEN_SYMBOL: str = "BTCUSDT"
OPEN_QTY: float = 0.00025
ORDER_TYPE: str = "MARKET"  # MARKET avoids needing a price

WAIT_FOR_FILL_SECONDS: int = 60
POLL_INTERVAL_SECONDS: int = 2
PROMPT_BEFORE_OPEN: bool = True  # set False to open immediately
POST_RESULT_SLEEP_SECONDS: int = 10


def _read_position_qty_avg(main_engine: MainEngine, strategy_name: str, symbol: str) -> tuple[float, float]:
    """Return (quantity, avg_cost) for symbol in strategy holdings; (0, 0) if missing."""
    holding = main_engine.strategy_engine.get_holding(strategy_name)
    pos = holding.positions.get(symbol)
    if pos is None:
        return 0.0, 0.0
    qty = float(getattr(pos, "quantity", 0.0) or 0.0)
    avg = float(getattr(pos, "avg_cost", 0.0) or 0.0)
    return qty, avg


def _wait_for_position_after_order(
    main_engine: MainEngine, strategy_name: str, symbol: str
) -> tuple[bool, float, float]:
    """
    Poll StrategyEngine holdings until qty > 0 or timeout.
    Returns (found, quantity, avg_cost).
    """
    deadline = time.time() + WAIT_FOR_FILL_SECONDS
    while time.time() < deadline:
        qty, avg = _read_position_qty_avg(main_engine, strategy_name, symbol)
        if qty > 0:
            return True, qty, avg
        time.sleep(POLL_INTERVAL_SECONDS)
    qty, avg = _read_position_qty_avg(main_engine, strategy_name, symbol)
    return qty > 0, qty, avg


def main() -> int:
    main_engine = MainEngine(env_mode=ENGINE_MODE)

    strat = main_engine.get_strategy(STRATEGY_NAME)
    if strat is None:
        raise SystemExit(f"Strategy not found: {STRATEGY_NAME}")

    strat.on_init()
    main_engine.write_log(f"[{STRATEGY_NAME}] initialized; ready to open {OPEN_SYMBOL}", level="INFO", source="System")

    if PROMPT_BEFORE_OPEN:
        input(f"Press Enter to open {ORDER_TYPE} {OPEN_SYMBOL} qty={OPEN_QTY} (mock mode) ...")

    oid = strat.open_position(symbol=OPEN_SYMBOL, quantity=OPEN_QTY, price=None, order_type=ORDER_TYPE)
    main_engine.write_log(
        f"[{STRATEGY_NAME}] open_position sent | order_id={oid!r} symbol={OPEN_SYMBOL} qty={OPEN_QTY} type={ORDER_TYPE}",
        level="INFO",
        source="System",
    )
    print(f"[{STRATEGY_NAME}] open_position order_id={oid!r}")

    ok, qty, avg = _wait_for_position_after_order(main_engine, STRATEGY_NAME, OPEN_SYMBOL)
    main_engine.write_log(
        f"[{STRATEGY_NAME}] position check after order | symbol={OPEN_SYMBOL} "
        f"exists={ok} qty={qty} avg_cost={avg}",
        level="INFO" if ok else "WARN",
        source="System",
    )
    print(
        f"[{STRATEGY_NAME}] POSITION AFTER ORDER: symbol={OPEN_SYMBOL} "
        f"exists={ok} qty={qty} avg_cost={avg}"
    )

    print(f"[{STRATEGY_NAME}] sleeping {POST_RESULT_SLEEP_SECONDS}s then re-check position...")
    time.sleep(POST_RESULT_SLEEP_SECONDS)

    qty2, avg2 = _read_position_qty_avg(main_engine, STRATEGY_NAME, OPEN_SYMBOL)
    still = qty2 > 0
    main_engine.write_log(
        f"[{STRATEGY_NAME}] position re-check after sleep | symbol={OPEN_SYMBOL} "
        f"exists={still} qty={qty2} avg_cost={avg2}",
        level="INFO" if still else "WARN",
        source="System",
    )
    print(
        f"[{STRATEGY_NAME}] POSITION AFTER SLEEP: symbol={OPEN_SYMBOL} "
        f"exists={still} qty={qty2} avg_cost={avg2}"
    )

    success = ok and still
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())


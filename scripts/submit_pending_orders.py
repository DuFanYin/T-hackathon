#!/usr/bin/env python3
"""
Submit 3 limit orders that will stay pending (price below market for BUY).

Usage: python scripts/submit_pending_orders.py
"""

import os
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(root_dir, ".env"))

from src.engines.engine_gateway import GatewayEngine


def _main_mock():
    """Mock main_engine matching engine usage."""
    from unittest.mock import MagicMock
    m = MagicMock()
    m.write_log = lambda msg, level="INFO", source="System": print(f"[{level}] {msg}")
    m.log_store = None
    m.order_store = None
    return m


def _get_last_price(gw: GatewayEngine, symbol: str) -> float:
    """Get last price from ticker. Fallback to a default if unavailable."""
    ticker = gw.get_ticker(symbol=symbol)
    pair = gw._to_roostoo_pair(symbol)
    last = 95000.0 if "BTC" in symbol else 3500.0
    if ticker and isinstance(ticker, dict):
        data = ticker.get("Data") or ticker.get("TradePairs") or ticker.get("Ticker") or {}
        pair_data = data.get(pair) if isinstance(data, dict) else {}
        if isinstance(pair_data, dict) and pair_data.get("LastPrice") is not None:
            last = float(pair_data["LastPrice"])
        else:
            for v in (data.values() if isinstance(data, dict) else []):
                if isinstance(v, dict) and v.get("LastPrice") is not None:
                    last = float(v["LastPrice"])
                    break
    return last


def main() -> int:
    print("=== Submit 3 pending limit orders ===\n")
    gw = GatewayEngine(main_engine=_main_mock(), env_mode="mock")

    symbol = "BTCUSDT"
    last = _get_last_price(gw, symbol)
    print(f"Symbol: {symbol}, last price: {last:.2f}\n")

    # 3 limit BUY orders at 30%, 25%, 20% below market — all stay pending
    orders = [
        ("BUY", 0.0001, 0.70),   # 30% below
        ("BUY", 0.0001, 0.75),   # 25% below
        ("BUY", 0.0001, 0.80),   # 20% below
    ]

    order_ids = []
    for i, (side, qty, pct) in enumerate(orders, 1):
        limit_price = round(last * pct, 2)
        print(f"Order {i}: LIMIT {side} {qty} @ {limit_price} ({pct*100:.0f}% of market)...")
        r = gw.place_order(symbol, side, qty, price=limit_price, order_type="LIMIT")
        if r is None:
            print("  ERROR: failed\n")
            continue
        did = r.get("order_id") or r.get("orderId")
        if isinstance(r.get("OrderDetail"), dict):
            did = r["OrderDetail"].get("OrderID") or did
        oid = str(did) if did else None
        if oid:
            order_ids.append(oid)
            print(f"  OK: order_id={oid}\n")
        else:
            print("  OK (no order_id)\n")

    if order_ids:
        gw._refresh_account_cache(force=True)
        pc = gw.get_pending_count()
        print(f"pending (from query_order): {pc}")
        print(f"Submitted {len(order_ids)} orders: {order_ids}")
        print("\nTo cancel: python -c \"from src.engines.engine_gateway import GatewayEngine; ...\" or use cancel_order(symbol='BTCUSDT')")

    print("\n=== Done ===")
    return 0 if order_ids else 1


if __name__ == "__main__":
    sys.exit(main())

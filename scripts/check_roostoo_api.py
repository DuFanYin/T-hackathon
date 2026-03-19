#!/usr/bin/env python3
"""
Query all Roostoo v3 API endpoints. Log errors, no test framework.

Usage: python scripts/check_roostoo_api.py
"""

import os
import sys

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(root_dir, ".env"))

from src.engines.engine_gateway import GatewayEngine


def _main_mock():
    """Mock main_engine matching engine usage (log_store, order_store)."""
    from unittest.mock import MagicMock
    m = MagicMock()
    m.write_log = lambda msg, level="INFO", source="System": print(f"[{level}] {msg}")
    m.log_store = None
    m.order_store = None  # gateway skips persist when None
    return m


def main() -> int:
    print("=== Roostoo API check (mock mode) ===\n")
    gw = GatewayEngine(main_engine=_main_mock(), env_mode="mock")

    errors = 0

    # GET /v3/serverTime (no auth)
    print("GET /v3/serverTime...")
    r = gw.get_server_time()
    if r is None:
        print("  ERROR: failed\n")
        errors += 1
    else:
        print(f"  OK: {r}\n")

    # GET /v3/exchangeInfo (no auth)
    print("GET /v3/exchangeInfo...")
    r = gw.get_exchange_info()
    if r is None:
        print("  ERROR: failed\n")
        errors += 1
    else:
        pairs = list((r.get("TradePairs") or {}).keys())[:5]
        print(f"  OK: {len(r.get('TradePairs') or {})} pairs, e.g. {pairs}\n")

    # GET /v3/ticker (no auth)
    print("GET /v3/ticker...")
    r = gw.get_ticker(symbol=None)
    if r is None:
        print("  ERROR: failed\n")
        errors += 1
    else:
        print(f"  OK: {type(r).__name__}\n")

    print("GET /v3/ticker?pair=BTC/USD...")
    r = gw.get_ticker(symbol="BTCUSDT")
    if r is None:
        print("  ERROR: failed\n")
        errors += 1
    else:
        print(f"  OK\n")

    # GET /v3/balance (signed)
    print("GET /v3/balance (signed)...")
    r = gw._fetch_balance()
    if r is None:
        print("  ERROR: failed (check API keys)\n")
        errors += 1
    else:
        print(f"  OK: {type(r).__name__}\n")

    # POST /v3/query_order (signed, pending_only=TRUE) — replaces pending_count
    print("POST /v3/query_order (signed, pending_only=TRUE)...")
    r = gw.query_order(pending_only=True, limit=10)
    if r is None:
        print("  ERROR: failed (check API keys)\n")
        errors += 1
    else:
        matched = r.get("OrderMatched") if isinstance(r, dict) else None
        n = len(matched) if isinstance(matched, list) else 0
        print(f"  OK: {n} pending order(s)\n")

    # POST /v3/query_order (signed)
    print("POST /v3/query_order (signed, no order_id)...")
    r = gw.query_order(pending_only=False, limit=1)
    if r is None:
        print("  ERROR: failed\n")
        errors += 1
    else:
        print(f"  OK: {type(r).__name__}\n")

    # POST /v3/place_order (signed) - MARKET
    print("POST /v3/place_order (signed, MARKET BUY 0.0001 BTC)...")
    r = gw.place_order("BTCUSDT", "BUY", 0.0001, price=None, order_type="MARKET")
    if r is None:
        print("  ERROR: failed\n")
        errors += 1
    else:
        did = r.get("order_id") or r.get("orderId")
        if isinstance(r.get("OrderDetail"), dict):
            did = r["OrderDetail"].get("OrderID") or did
        print(f"  OK: order_id={did}\n" if did else "  OK (no order_id)\n")

    # POST /v3/place_order (signed) - LIMIT (price within ±30% of market)
    ticker = gw.get_ticker(symbol="BTCUSDT")
    last = 95000.0
    if ticker and isinstance(ticker, dict):
        data = ticker.get("Data") or ticker.get("TradePairs") or ticker.get("Ticker") or {}
        pair_data = data.get("BTC/USD") if isinstance(data, dict) else {}
        if isinstance(pair_data, dict) and pair_data.get("LastPrice") is not None:
            last = float(pair_data["LastPrice"])
        else:
            for v in (data.values() if isinstance(data, dict) else []):
                if isinstance(v, dict) and v.get("LastPrice") is not None:
                    last = float(v["LastPrice"])
                    break
    limit_price = round(last * 0.70, 2)  # 30% below market (Roostoo floor), stays pending
    print(f"POST /v3/place_order (signed, LIMIT BUY 0.0001 BTC @ {limit_price})...")
    r = gw.place_order("BTCUSDT", "BUY", 0.0001, price=limit_price, order_type="LIMIT")
    limit_order_id = None
    if r is None:
        print("  ERROR: failed\n")
        errors += 1
    else:
        did = r.get("order_id") or r.get("orderId")
        if isinstance(r.get("OrderDetail"), dict):
            did = r["OrderDetail"].get("OrderID") or did
        limit_order_id = str(did) if did else None
        print(f"  OK: order_id={limit_order_id}\n" if limit_order_id else "  OK (no order_id)\n")

    # Diagnose: query_order pending + query_order by id before cancel
    if limit_order_id:
        qo = gw.query_order(pending_only=True, limit=10)
        n = len(qo.get("OrderMatched") or []) if isinstance(qo, dict) else 0
        print(f"  pending orders after limit: {n}\n")
        qo = gw.query_order(order_id=limit_order_id)
        if isinstance(qo, dict):
            detail = qo.get("OrderDetail")
            if not detail and isinstance(qo.get("OrderMatched"), list) and qo["OrderMatched"]:
                for m in qo["OrderMatched"]:
                    if str(m.get("OrderID")) == limit_order_id:
                        detail = m
                        break
            status = (detail or {}).get("Status", "?")
            print(f"  query_order({limit_order_id}): Status={status}\n")

    # POST /v3/cancel_order (signed) - Roostoo demo uses pair (not order_id) to cancel pending orders
    print("POST /v3/cancel_order (signed, pair=BTC/USD)...")
    r = gw.cancel_order(symbol="BTCUSDT")
    if r is None:
        print("  ERROR: failed\n")
        errors += 1
    else:
        canceled = r.get("CanceledList")
        print(f"  OK: CanceledList={canceled}\n")

    print("=== Done ===")
    if errors:
        print(f"Errors: {errors}")
        return 1
    print("All OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

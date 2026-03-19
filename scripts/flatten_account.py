#!/usr/bin/env python3
"""
Cancel all pending orders and market-sell all non-USD positions.

This script talks directly to Roostoo via `GatewayEngine` (signed endpoints).
It loads API keys from `.env` (same as other scripts).

Usage:
  python scripts/flatten_account.py

Notes:
- Pending orders are discovered via `query_order(pending_only=True)`.
- Cancels are attempted by order_id when available (fallback to symbol/pair cancel).
- Positions are derived from wallet "Free" amounts; any non-zero asset (except USD/USDT)
  is sold via a MARKET SELL against USD (symbol format: <ASSET>USDT).
"""

import os
import sys
from typing import Any

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(root_dir, ".env"))

from src.engines.engine_gateway import GatewayEngine


def _main_mock():
    """Mock main_engine matching engine usage (log_store, order_store)."""
    from unittest.mock import MagicMock

    m = MagicMock()
    m.write_log = lambda msg, level="INFO", source="System": print(f"[{level}] {source}: {msg}")
    m.log_store = None
    m.order_store = None
    return m


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _extract_wallet(balance: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(balance, dict):
        return {}
    w = balance.get("Wallet")
    if isinstance(w, dict):
        return w
    sw = balance.get("SpotWallet")
    if isinstance(sw, dict):
        return sw
    return {}


def main() -> int:
    env_mode = (os.getenv("ROOSTOO_ENV") or os.getenv("ENV_MODE") or "mock").strip().lower()
    if env_mode not in ("mock", "real"):
        env_mode = "mock"

    print(f"=== Flatten account ===")
    print(f"env_mode={env_mode}")

    gw = GatewayEngine(main_engine=_main_mock(), env_mode=env_mode)

    # 1) Cancel all pending orders
    print("\n--- Cancel pending orders ---")
    qo = gw.query_order(pending_only=True, limit=200)
    matched = qo.get("OrderMatched") if isinstance(qo, dict) else None
    orders = matched if isinstance(matched, list) else []
    print(f"pending orders found: {len(orders)}")

    canceled = 0
    cancel_errors = 0
    for item in orders:
        if not isinstance(item, dict):
            continue
        oid = item.get("OrderID") or item.get("order_id") or item.get("orderId")
        pair = item.get("Pair") or item.get("pair")

        # Prefer cancel by order_id, fallback to cancel by symbol if we can map the pair.
        resp = None
        if oid is not None and str(oid).strip():
            resp = gw.cancel_order(order_id=str(oid).strip())
        elif isinstance(pair, str) and "/" in pair:
            base, quote = pair.split("/", 1)
            if quote.upper() == "USD":
                resp = gw.cancel_order(symbol=f"{base.upper()}USDT")

        if resp is None:
            cancel_errors += 1
            print(f"  cancel FAILED: order_id={oid!r} pair={pair!r}")
            continue

        canceled += 1
        print(f"  cancel OK: order_id={oid!r} pair={pair!r}")

    # 2) Market-sell all positions (wallet free amounts)
    print("\n--- Sell all positions ---")
    bal = gw._request_get("/v3/balance", params={"timestamp": gw._ts_ms()}, signed=True)
    wallet = _extract_wallet(bal)

    to_sell: list[tuple[str, float]] = []
    for asset, entry in wallet.items():
        if not isinstance(asset, str):
            continue
        sym = asset.strip().upper()
        if sym in ("USD", "USDT"):
            continue
        if not isinstance(entry, dict):
            continue
        qty = _safe_float(entry.get("Free", 0.0))
        if qty > 0:
            to_sell.append((sym, qty))

    print(f"assets to sell: {len(to_sell)}")
    sold = 0
    sell_errors = 0
    for asset, qty in sorted(to_sell):
        symbol = f"{asset}USDT"
        print(f"  MARKET SELL {symbol} qty={qty} ...")
        resp = gw.place_order(symbol, "SELL", qty, price=None, order_type="MARKET")
        if resp is None:
            sell_errors += 1
            print(f"    ERROR: place_order failed")
            continue
        sold += 1
        did = resp.get("order_id") or resp.get("orderId")
        if isinstance(resp.get("OrderDetail"), dict):
            did = resp["OrderDetail"].get("OrderID") or did
        print(f"    OK: order_id={did!r}")

    print("\n=== Done ===")
    print(f"canceled_ok={canceled} cancel_errors={cancel_errors}")
    print(f"sold_ok={sold} sell_errors={sell_errors}")

    return 0 if cancel_errors == 0 and sell_errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())


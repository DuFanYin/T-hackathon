#!/usr/bin/env python3
"""
Debug script: place a MARKET order, query it, and print raw fields.

Goal: Verify how Roostoo returns fill fields (FilledQuantity, FilledAverPrice, etc.)
so we can parse OrderData correctly.

Usage:
  python3 scripts/debug_order_parse.py

Environment:
  - Loads `.env` (same as other scripts)
  - Uses ROOSTOO_ENV or ENV_MODE to pick "mock" / "real" (default: mock)
"""

from __future__ import annotations

import os
import sys
from typing import Any

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from dotenv import load_dotenv

load_dotenv(os.path.join(root_dir, ".env"))

from src.engines.engine_gateway import GatewayEngine
from src.utilities.object import OrderData


def _main_mock():
    from unittest.mock import MagicMock

    m = MagicMock()
    m.write_log = lambda msg, level="INFO", source="System": print(f"[{level}] {source}: {msg}")
    m.log_store = None
    m.order_store = None
    return m


def _env_mode() -> str:
    v = (os.getenv("ROOSTOO_ENV") or os.getenv("ENV_MODE") or "mock").strip().lower()
    return v if v in ("mock", "real") else "mock"


def _pick_order_id(resp: dict[str, Any] | None) -> str | None:
    if not isinstance(resp, dict):
        return None
    oid = resp.get("order_id") or resp.get("orderId")
    if oid is None and isinstance(resp.get("OrderDetail"), dict):
        oid = resp["OrderDetail"].get("OrderID")
    return str(oid) if oid is not None and str(oid).strip() else None


def _pretty_kv(d: dict[str, Any], keys: list[str]) -> str:
    parts: list[str] = []
    for k in keys:
        if k in d:
            parts.append(f"{k}={d.get(k)!r}")
    return ", ".join(parts)


def _pair_to_symbol(pair: str) -> str:
    p = (pair or "").strip()
    if "/" not in p:
        return ""
    base, quote = p.split("/", 1)
    base = base.strip().upper()
    quote = quote.strip().upper()
    if not base or not quote:
        return ""
    # Internal convention used by the codebase: BTCUSDT for BTC/USD.
    return f"{base}USDT" if quote == "USD" else f"{base}{quote}"


def parse_order_detail_to_orderdata(detail: dict[str, Any], *, strategy_name: str = "DebugParse") -> OrderData | None:
    oid = str(detail.get("OrderID", "") or "").strip()
    if not oid:
        return None

    pair = str(detail.get("Pair", "") or "")
    symbol = _pair_to_symbol(pair)

    fq_raw = (
        detail.get("FilledQuantity")
        if detail.get("FilledQuantity") is not None
        else detail.get("FilledQty")
        if detail.get("FilledQty") is not None
        else detail.get("filled_quantity")
        if detail.get("filled_quantity") is not None
        else 0
    )
    favg_raw = (
        detail.get("FilledAverPrice")
        if detail.get("FilledAverPrice") is not None
        else detail.get("FilledAvgPrice")
        if detail.get("FilledAvgPrice") is not None
        else detail.get("FilledAveragePrice")
        if detail.get("FilledAveragePrice") is not None
        else detail.get("filled_avg_price")
        if detail.get("filled_avg_price") is not None
        else 0
    )

    return OrderData(
        order_id=oid,
        symbol=symbol,
        side=str(detail.get("Side", "") or ""),
        quantity=float(detail.get("Quantity", 0) or 0),
        price=float(detail.get("Price", 0) or 0),
        status=str(detail.get("Status", "") or "PENDING"),
        order_type=str(detail.get("Type", "") or "LIMIT"),
        filled_quantity=float(fq_raw or 0),
        filled_avg_price=float(favg_raw or 0),
        role=str(detail.get("Role", "") or "") or None,
        stop_type=str(detail.get("StopType", "") or "") or None,
        create_ts=detail.get("CreateTimestamp"),
        finish_ts=detail.get("FinishTimestamp"),
        strategy_name=strategy_name,
    )


def main() -> int:
    mode = _env_mode()
    symbol = (os.getenv("DEBUG_SYMBOL") or "BTCUSDT").strip().upper()
    qty = float(os.getenv("DEBUG_QTY") or "0.0001")
    side = (os.getenv("DEBUG_SIDE") or "BUY").strip().upper()

    print("=== Debug order parse ===")
    print(f"env_mode={mode} symbol={symbol} side={side} qty={qty}")

    gw = GatewayEngine(main_engine=_main_mock(), env_mode=mode)

    print("\n--- place_order (MARKET) ---")
    resp = gw.place_order(symbol, side, qty, price=None, order_type="MARKET")
    if not isinstance(resp, dict):
        print("ERROR: place_order returned non-dict/None (check API keys and env)")
        return 2

    oid = _pick_order_id(resp)
    print(f"order_id={oid!r}")
    if isinstance(resp.get("OrderDetail"), dict):
        od = resp["OrderDetail"]
        print("OrderDetail keys:", sorted(list(od.keys()))[:80])
        print("OrderDetail important:", _pretty_kv(od, [
            "OrderID", "Pair", "Side", "Type", "Status",
            "Quantity", "Price",
            "FilledQuantity", "FilledQty",
            "FilledAverPrice", "FilledAvgPrice", "FilledAveragePrice",
            "CreateTimestamp", "FinishTimestamp",
        ]))

    if not oid:
        print("WARN: No order_id found; cannot query_order by id.")
        return 1

    print("\n--- query_order(order_id=...) ---")
    q = gw.query_order(order_id=oid)
    if not isinstance(q, dict):
        print("ERROR: query_order returned non-dict/None")
        return 2

    detail = q.get("OrderDetail")
    if not isinstance(detail, dict):
        matched = q.get("OrderMatched")
        if isinstance(matched, list) and matched and isinstance(matched[0], dict):
            detail = matched[0]

    if not isinstance(detail, dict):
        print("ERROR: no OrderDetail/OrderMatched dict in query response")
        print("query keys:", sorted(list(q.keys())))
        return 2

    print("query detail keys:", sorted(list(detail.keys()))[:80])
    print("query detail important:", _pretty_kv(detail, [
        "OrderID", "Pair", "Side", "Type", "Status",
        "Quantity", "Price",
        "FilledQuantity", "FilledQty",
        "FilledAverPrice", "FilledAvgPrice", "FilledAveragePrice",
        "CreateTimestamp", "FinishTimestamp",
    ]))

    print("\n--- parsed OrderData ---")
    parsed = parse_order_detail_to_orderdata(detail, strategy_name="DebugParse")
    if parsed is None:
        print("ERROR: could not parse OrderData (missing OrderID?)")
        return 2

    print(
        f"parsed: status={parsed.status!r} side={parsed.side!r} symbol={parsed.symbol!r} "
        f"filled_quantity={parsed.filled_quantity} filled_avg_price={parsed.filled_avg_price}"
    )

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


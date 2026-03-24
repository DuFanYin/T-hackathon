#!/usr/bin/env python3
"""
Show account balances and holdings using direct signed Roostoo API calls.

Usage:
  python3 scripts/show_account_balance_and_holding.py
  python3 scripts/show_account_balance_and_holding.py --general
  python3 scripts/show_account_balance_and_holding.py --base-url https://mock-api.roostoo.com

Notes:
- Uses API keys from `.env`:
  - Competition_API_KEY / Competition_API_SECRET (default)
  - or General_Portfolio_Testing_API_KEY / General_Portfolio_Testing_API_SECRET with --general
- Calls `/v3/balance` and `/v3/query_order` directly via requests.
"""

from __future__ import annotations

import os
import sys
import hmac
import hashlib
import time
from typing import Any

from dotenv import load_dotenv
import requests

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
load_dotenv(os.path.join(root_dir, ".env"))

def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _extract_wallet(balance: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(balance, dict):
        return {}
    wallet = balance.get("Wallet")
    if isinstance(wallet, dict):
        return wallet
    spot_wallet = balance.get("SpotWallet")
    if isinstance(spot_wallet, dict):
        return spot_wallet
    return {}


def _canonical_body(params: dict[str, Any]) -> str:
    return "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))


def _headers(api_key: str, secret: str, params: dict[str, Any]) -> dict[str, str]:
    body = _canonical_body(params)
    sig = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "RST-API-KEY": api_key,
        "MSG-SIGNATURE": sig,
        "api-key": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _request_get_signed(base_url: str, path: str, params: dict[str, Any], api_key: str, secret: str) -> dict[str, Any] | None:
    url = f"{base_url}{path}"
    body = _canonical_body(params)
    full_url = f"{url}?{body}" if body else url
    hdr = _headers(api_key=api_key, secret=secret, params=params)
    resp = requests.get(full_url, headers=hdr, timeout=5.0)
    if resp.status_code != 200:
        print(f"ERROR: GET {path} status={resp.status_code} body={resp.text[:300]}")
        return None
    try:
        data = resp.json()
    except Exception as e:
        print(f"ERROR: GET {path} JSON parse failed: {type(e).__name__}: {e}")
        return None
    if not isinstance(data, dict):
        print(f"ERROR: GET {path} expected dict response, got {type(data).__name__}")
        return None
    return data


def _request_post_signed(base_url: str, path: str, params: dict[str, Any], api_key: str, secret: str) -> dict[str, Any] | None:
    url = f"{base_url}{path}"
    body = _canonical_body(params)
    hdr = _headers(api_key=api_key, secret=secret, params=params)
    resp = requests.post(url, data=body, headers=hdr, timeout=5.0)
    if resp.status_code != 200:
        print(f"ERROR: POST {path} status={resp.status_code} body={resp.text[:300]}")
        return None
    try:
        data = resp.json()
    except Exception as e:
        print(f"ERROR: POST {path} JSON parse failed: {type(e).__name__}: {e}")
        return None
    if not isinstance(data, dict):
        print(f"ERROR: POST {path} expected dict response, got {type(data).__name__}")
        return None
    return data


def main() -> int:
    use_competition = "--general" not in sys.argv
    base_url = os.getenv("ROOSTOO_REAL_BASE_URL", "https://mock-api.roostoo.com")
    if "--base-url" in sys.argv:
        idx = sys.argv.index("--base-url")
        if idx + 1 < len(sys.argv):
            base_url = sys.argv[idx + 1].strip()

    key_label = "Competition" if use_competition else "General Portfolio Testing"
    api_key = os.getenv("Competition_API_KEY" if use_competition else "General_Portfolio_Testing_API_KEY", "")
    api_secret = os.getenv("Competition_API_SECRET" if use_competition else "General_Portfolio_Testing_API_SECRET", "")

    print("=== Account balance + holdings ===")
    print(f"mode=real | key_set={key_label} | base_url={base_url}")

    if not api_key or not api_secret:
        print("ERROR: API key/secret missing in .env.")
        return 1

    ts = int(time.time() * 1000)
    bal = _request_get_signed(
        base_url=base_url,
        path="/v3/balance",
        params={"timestamp": ts},
        api_key=api_key,
        secret=api_secret,
    )
    if not isinstance(bal, dict):
        print("ERROR: failed to fetch /v3/balance.")
        return 1

    wallet = _extract_wallet(bal)
    if not wallet:
        print("WARN: Wallet data missing in balance response.")
        print(f"raw keys: {sorted(list(bal.keys()))}")
        return 1

    print("\n--- Wallet balances ---")
    rows: list[tuple[str, float, float, float]] = []
    total_free_usdt = 0.0
    for asset, entry in wallet.items():
        if not isinstance(asset, str) or not isinstance(entry, dict):
            continue
        free = _safe_float(entry.get("Free", 0.0))
        locked = _safe_float(entry.get("Locked", 0.0))
        total = free + locked
        if total <= 0.0:
            continue
        rows.append((asset.upper(), free, locked, total))
        if asset.upper() in ("USD", "USDT"):
            total_free_usdt += free

    rows.sort(key=lambda x: x[0])
    if not rows:
        print("(no non-zero assets)")
    else:
        print(f"{'ASSET':<10} {'FREE':>18} {'LOCKED':>18} {'TOTAL':>18}")
        for asset, free, locked, total in rows:
            print(f"{asset:<10} {free:>18.8f} {locked:>18.8f} {total:>18.8f}")

    print("\n--- Holdings (non-USD assets, total > 0) ---")
    holdings = [(a, t) for (a, _f, _l, t) in rows if a not in ("USD", "USDT") and t > 0.0]
    if not holdings:
        print("(no open holdings)")
    else:
        for asset, total in holdings:
            print(f"{asset:<10} qty={total:.8f}")

    print("\n--- Pending orders ---")
    qo = _request_post_signed(
        base_url=base_url,
        path="/v3/query_order",
        params={"timestamp": int(time.time() * 1000), "pending_only": "TRUE", "limit": 200},
        api_key=api_key,
        secret=api_secret,
    )
    matched = qo.get("OrderMatched") if isinstance(qo, dict) else None
    n_pending = len(matched) if isinstance(matched, list) else 0
    print(f"pending_orders={n_pending}")

    print("\n--- Quick summary ---")
    print(f"free_usdt={total_free_usdt:.8f}")
    print(f"holding_assets={len(holdings)}")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

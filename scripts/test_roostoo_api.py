#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any


from dotenv import load_dotenv


def _ts_ms() -> int:
    return int(time.time() * 1000)


def _sign(secret: str, params: dict[str, Any]) -> str:
    query_string = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
    return hmac.new(secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()


def _http_get_json(url: str, params: dict[str, Any], headers: dict[str, str]) -> Any:
    qs = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{qs}", headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {e.reason}{' - ' + body if body else ''}") from e


def _http_post_form_json(url: str, data: dict[str, Any], headers: dict[str, str]) -> Any:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, headers=headers, data=encoded, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {e.reason}{' - ' + body if body else ''}") from e


def main() -> int:
    load_dotenv()

    env_mode = (os.getenv("ENV_MODE", "mock") or "mock").strip().lower()
    base_url = (
        os.getenv("ROOSTOO_REAL_BASE_URL") if env_mode == "real" else os.getenv("ROOSTOO_MOCK_BASE_URL")
    ) or ("https://api.roostoo.com" if env_mode == "real" else "https://mock-api.roostoo.com")
    base_url = base_url.rstrip("/")

    # Try explicit vars first, else fall back to the ones used by the app.
    api_key = os.getenv("ROOSTOO_API_KEY", "").strip()
    api_secret = os.getenv("ROOSTOO_API_SECRET", "").strip()
    if not api_key or not api_secret:
        use_comp = (os.getenv("ROOSTOO_USE_COMPETITION_KEYS", "") or "").strip().lower() in ("1", "true", "yes")
        if use_comp:
            api_key = os.getenv("Competition_API_KEY", "").strip()
            api_secret = os.getenv("Competition_API_SECRET", "").strip()
        else:
            api_key = os.getenv("General_Portfolio_Testing_API_KEY", "").strip()
            api_secret = os.getenv("General_Portfolio_Testing_API_SECRET", "").strip()

    if not api_key or not api_secret:
        print("Missing API credentials in env (.env).")
        print("Set ROOSTOO_API_KEY and ROOSTOO_API_SECRET, or the app's *_API_KEY/_SECRET variables.")
        return 2

    def signed_headers(params: dict[str, Any]) -> dict[str, str]:
        sig = _sign(api_secret, params)
        return {
            "RST-API-KEY": api_key,
            "MSG-SIGNATURE": sig,
            "Content-Type": "application/x-www-form-urlencoded",
        }

    # 1) balance
    p1 = {"timestamp": _ts_ms()}
    balance = _http_get_json(f"{base_url}/v3/balance", p1, signed_headers(p1))

    # 2) pending_count
    p2 = {"timestamp": _ts_ms()}
    pending = _http_get_json(f"{base_url}/v3/pending_count", p2, signed_headers(p2))

    # 3) query_order (pending only, most useful for "account overview")
    p3 = {"timestamp": _ts_ms(), "pending_only": "TRUE", "limit": 200}
    orders = _http_post_form_json(f"{base_url}/v3/query_order", p3, signed_headers(p3))

    print("=== /v3/balance ===")
    print(json.dumps(balance, indent=2, ensure_ascii=False))
    print("\n=== /v3/pending_count ===")
    print(json.dumps(pending, indent=2, ensure_ascii=False))
    print("\n=== /v3/query_order (pending_only=TRUE) ===")
    print(json.dumps(orders, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


"""
Gateway engine for Roostoo mock exchange.

- Stateless REST: no persistent connections, every call is signed.
- Orders: send/cancel via `/v3/place_order` and `/v3/cancel_order` using HMAC-SHA256 signatures.
- Bar data is owned by MarketEngine (Binance klines); gateway does not emit bars.

API usage aligned with scripts/check_roostoo_api.py (canonical successful example):
- place_order(symbol, side, quantity, price=None, order_type): MARKET uses price=None
- cancel_order(order_id=None, symbol=None): pair (symbol) or order_id
- query_order(order_id=None, symbol=None, pending_only=None, limit=None)

API keys from env: General_Portfolio_Testing_API_KEY/SECRET or Competition_API_KEY/SECRET.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from typing import Any, Dict, Optional

import requests

from src.utilities.base_engine import BaseEngine
from src.utilities.object import OrderData, TradingPair

# Statuses that mean the order is finished (no more polling)
_FINISHED_STATUSES = frozenset({"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"})


class GatewayEngine(BaseEngine):
    """Roostoo vendor adapter: send_order/cancel_order; on_timer() polls order status and refreshes account cache."""

    DEFAULT_MOCK_BASE_URL = "https://mock-api.roostoo.com"
    DEFAULT_REAL_BASE_URL = "https://api.roostoo.com"

    def __init__(
        self,
        main_engine=None,
        engine_name: str = "Gateway",
        trading_pairs: Optional[list[str]] = None,
        env_mode: str = "mock",
        use_competition_keys: bool = False,
    ) -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        # Optional override from main; if empty, this engine will discover tradeable pairs
        # from Roostoo `/v3/exchangeInfo` on first use.
        self.trading_pairs: list[str] = list(trading_pairs) if trading_pairs else []
        # Filled from exchangeInfo on startup (same dict object as MainEngine.trading_pairs_by_symbol).
        self.trading_pairs_by_symbol: dict[str, TradingPair] = {}
        self.use_competition_keys: bool = use_competition_keys
        self.env_mode: str = env_mode.strip().lower() if env_mode else "mock"

        # Base URL selection:
        # - mock: https://mock-api.roostoo.com  (documented in third_party)
        # - real: override via ROOSTOO_REAL_BASE_URL, else fallback to DEFAULT_REAL_BASE_URL
        if self.env_mode == "real":
            self.base_url = os.getenv("ROOSTOO_REAL_BASE_URL", self.DEFAULT_REAL_BASE_URL)
        else:
            self.base_url = os.getenv("ROOSTOO_MOCK_BASE_URL", self.DEFAULT_MOCK_BASE_URL)

        if use_competition_keys:
            self._api_key = os.getenv("Competition_API_KEY", "")
            self._secret = os.getenv("Competition_API_SECRET", "")
        else:
            self._api_key = os.getenv("General_Portfolio_Testing_API_KEY", "")
            self._secret = os.getenv("General_Portfolio_Testing_API_SECRET", "")

        # Log if signed endpoints may fail (401) due to missing credentials
        if not self._api_key or not self._secret:
            key_src = "Competition_API_KEY/SECRET" if use_competition_keys else "General_Portfolio_Testing_API_KEY/SECRET"
            self.log(
                f"WARN: Gateway API keys empty or missing | env={key_src} | "
                f"signed endpoints (/v3/balance, /v3/place_order, etc.) will fail with 401",
                level="WARN",
                source="Gateway",
            )

        # order_id -> OrderData: canonical order store; created on placement, updated by query_order
        self._order_map: dict[str, OrderData] = {}
        # strategy_name -> set of order_ids not yet finished (for polling and pending_by_strategy)
        self._strategy_pending: dict[str, set[str]] = {}

        # ---------------- cached account state (refreshed by engine timer, NOT by UI) ----------------
        self._cached_balance: dict[str, Any] | None = None
        self._cached_balance_ts: float | None = None
        self._last_order_query_ts: float | None = None  # when we last ran query_order (for UI)
        self._timer_seconds: int = 0  # counter: increments each timer tick, reset on refresh

    # ---------------- order id / attribution (shared with EventEngine) ----------------

    @staticmethod
    def extract_order_id_from_place_response(resp: dict[str, Any] | None) -> str | None:
        """
        Roostoo Public API: POST /v3/place_order returns ``Success``, ``ErrMsg``, and ``OrderDetail``
        with ``OrderID`` (see ``third_party/Roostoo-API-Documents/README.md`` — New order (Trade)).
        """
        if not isinstance(resp, dict):
            return None
        od = resp.get("OrderDetail")
        if not isinstance(od, dict):
            return None
        oid = od.get("OrderID")
        if oid is None:
            return None
        s = str(oid).strip()
        return s if s else None

    def _pending_discard_oid_everywhere(self, oid: str) -> None:
        """Ensure each order_id appears in at most one strategy pending bucket."""
        for ids in self._strategy_pending.values():
            ids.discard(oid)

    # ---------------- helpers ----------------

    @staticmethod
    def _canonical_body(params: Dict[str, Any]) -> str:
        """Build canonical form for signing (Roostoo: sortParamsByKey, k=v joined by &)."""
        return "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))

    def _headers(self, params: Dict[str, Any]) -> Dict[str, str]:
        body = self._canonical_body(params)
        secret_bytes = self._secret.encode("utf-8")
        sig = hmac.new(secret_bytes, body.encode("utf-8"), hashlib.sha256).hexdigest()
        return {
            "RST-API-KEY": self._api_key,
            "MSG-SIGNATURE": sig,
            "api-key": self._api_key,
        }

    @staticmethod
    def _ts_ms() -> int:
        """13-digit millisecond timestamp."""
        return int(time.time() * 1000)

    def _http_status_hint(self, status_code: int, signed: bool) -> str:
        """Return a short hint for common HTTP status codes."""
        hints = {
            400: "Bad request — check params/body format",
            401: "Unauthorized — signature error or invalid API key/secret; verify env vars",
            403: "Forbidden — API key lacks permission",
            404: "Not found — endpoint or resource missing",
            429: "Rate limited — throttle requests",
            500: "Server error — Roostoo API issue, retry later",
            502: "Bad gateway — upstream unavailable",
            503: "Service unavailable — API overloaded",
        }
        hint = hints.get(status_code, "")
        auth_note = " (signed)" if signed else " (public)"
        return f"{hint}{auth_note}" if hint else auth_note

    def _request_get(self, path: str, params: Dict[str, Any], signed: bool) -> Dict[str, Any] | None:
        try:
            headers = self._headers(params) if signed else None
            url = f"{self.base_url}{path}"
            # Use canonical body for GET so query string matches signature (EC2 vs local)
            if signed and params:
                url = f"{url}?{self._canonical_body(params)}"
                resp = requests.get(url, headers=headers, timeout=3.0)
            else:
                resp = requests.get(url, params=params, headers=headers, timeout=3.0)
            if resp.status_code != 200:
                hint = self._http_status_hint(resp.status_code, signed)
                self.log(
                    f"ERROR: GET {path} failed | status={resp.status_code} | {hint} | "
                    f"url={url} | body={resp.text[:500]}",
                    level="ERROR",
                    source="Gateway",
                )
                return None
            try:
                body = resp.json()
            except Exception as e:
                self.log(
                    f"ERROR: GET {path} JSON parse failed | exception={type(e).__name__}: {e} | "
                    f"body_len={len(resp.text)} body_preview={resp.text[:200]!r}",
                    level="ERROR",
                    source="Gateway",
                )
                return None
            if not isinstance(body, dict):
                self.log(
                    f"WARN: GET {path} unexpected response type | expected=dict got={type(body).__name__} | "
                    f"body_preview={str(body)[:200]!r}",
                    level="WARN",
                    source="Gateway",
                )
                return None
            return body
        except requests.exceptions.Timeout as e:
            self.log(
                f"ERROR: GET {path} timeout | url={url} | {e}",
                level="ERROR",
                source="Gateway",
            )
            return None
        except requests.exceptions.ConnectionError as e:
            self.log(
                f"ERROR: GET {path} connection failed | url={url} | {e}",
                level="ERROR",
                source="Gateway",
            )
            return None
        except Exception as e:
            self.log(
                f"ERROR: GET {path} exception | {type(e).__name__}: {e}",
                level="ERROR",
                source="Gateway",
            )
            return None

    def _request_post(self, path: str, data: Dict[str, Any], signed: bool) -> Dict[str, Any] | None:
        try:
            # Use canonical body so request body matches signature (EC2 vs local)
            body = self._canonical_body(data) if data else ""
            headers = self._headers(data) if signed else None
            if headers and "Content-Type" not in headers:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            url = f"{self.base_url}{path}"
            resp = requests.post(url, data=body, headers=headers, timeout=3.0)
            if resp.status_code != 200:
                hint = self._http_status_hint(resp.status_code, signed)
                self.log(
                    f"ERROR: POST {path} failed | status={resp.status_code} | {hint} | "
                    f"url={url} | body={resp.text[:500]}",
                    level="ERROR",
                    source="Gateway",
                )
                return None
            try:
                body = resp.json()
            except Exception as e:
                self.log(
                    f"ERROR: POST {path} JSON parse failed | exception={type(e).__name__}: {e} | "
                    f"body_len={len(resp.text)} body_preview={resp.text[:200]!r}",
                    level="ERROR",
                    source="Gateway",
                )
                return None
            if not isinstance(body, dict):
                self.log(
                    f"WARN: POST {path} unexpected response type | expected=dict got={type(body).__name__} | "
                    f"body_preview={str(body)[:200]!r}",
                    level="WARN",
                    source="Gateway",
                )
                return None
            return body
        except requests.exceptions.Timeout as e:
            self.log(
                f"ERROR: POST {path} timeout | url={url} | {e}",
                level="ERROR",
                source="Gateway",
            )
            return None
        except requests.exceptions.ConnectionError as e:
            self.log(
                f"ERROR: POST {path} connection failed | url={url} | {e}",
                level="ERROR",
                source="Gateway",
            )
            return None
        except Exception as e:
            self.log(
                f"ERROR: POST {path} exception | {type(e).__name__}: {e}",
                level="ERROR",
                source="Gateway",
            )
            return None

    @staticmethod
    def _to_roostoo_pair(symbol: str) -> str:
        """Convert internal symbol (e.g. BTCUSDT) to Roostoo pair (e.g. BTC/USD)."""
        if symbol.endswith("USDT"):
            base = symbol[:-4]
            return f"{base}/USD"
        return symbol

    @staticmethod
    def _from_roostoo_pair(pair: str) -> str:
        """Convert Roostoo pair (e.g. BTC/USD) to internal symbol (e.g. BTCUSDT)."""
        if "/" in pair:
            base, quote = pair.split("/", 1)
            if quote == "USD":
                return f"{base}USDT"
            return f"{base}{quote}"
        return pair

    # ---------------- Roostoo Public API (v3) ----------------

    def get_server_time(self) -> Dict[str, Any] | None:
        """GET /v3/serverTime (no auth)."""
        return self._request_get("/v3/serverTime", params={}, signed=False)

    def get_exchange_info(self) -> Dict[str, Any] | None:
        """GET /v3/exchangeInfo (no auth). Adds explicit error logging on failure."""
        self.log("system init: GET /v3/exchangeInfo (discovering trading pairs)", level="INFO", source="Gateway")
        body = self._request_get("/v3/exchangeInfo", params={}, signed=False)
        if body is None:
            self.log(
                "ERROR: /v3/exchangeInfo returned None | possible causes: network failure, timeout, "
                "invalid JSON, or non-200 status — check logs above for details",
                level="ERROR",
                source="Gateway",
            )
            return None
        if not isinstance(body, dict):
            self.log(
                f"WARN: /v3/exchangeInfo unexpected body type | expected=dict got={type(body).__name__} | "
                f"cannot discover trading pairs",
                level="WARN",
                source="Gateway",
            )
            return None
        if body.get("Success") is False:
            err_code = body.get("ErrorCode", body.get("Code", ""))
            err_msg = body.get("ErrorMessage", body.get("Message", str(body)))
            self.log(
                f"WARN: /v3/exchangeInfo API error | Success=False | ErrorCode={err_code} | "
                f"ErrorMessage={err_msg} | full_body={body}",
                level="WARN",
                source="Gateway",
            )
        return body

    def get_ticker(self, symbol: str | None = None) -> Dict[str, Any] | None:
        """
        GET /v3/ticker (RCL_TSCheck).

        If symbol is provided, sends `pair=<COIN/USD>` and returns the raw response body.
        """
        params: Dict[str, Any] = {"timestamp": self._ts_ms()}
        if symbol:
            params["pair"] = self._to_roostoo_pair(symbol)
        return self._request_get("/v3/ticker", params=params, signed=False)

    @staticmethod
    def _round_to_precision(value: float, decimals: int) -> float:
        """Round value to the given number of decimal places (half-up)."""
        if decimals < 0:
            return value
        factor = 10.0 ** decimals
        import math
        return math.floor(value * factor + 0.5) / factor

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        order_type: str | None = None,
    ) -> Dict[str, Any] | None:
        """POST /v3/place_order (SIGNED). Returns raw API response dict or None.

        Safety net: looks up TradingPair precision and rounds qty/price via
        quantize_quantity / quantize_price before sending. Rejects orders for
        unknown pairs (they would fail with step-size errors anyway).
        """
        sym = str(symbol).strip().upper()
        pair = self._to_roostoo_pair(sym)
        inferred = "MARKET" if price is None else "LIMIT"
        ot = (order_type or inferred).upper()

        tp = self.trading_pairs_by_symbol.get(sym)
        # If we have no discovered precision data at all, allow the request to go
        # through *without rounding* (useful for early startup / mock unit tests).
        # If we have discovered some precision data but not for this pair, reject to
        # prevent likely step-size errors from the exchange.
        if tp is None:
            if not self.trading_pairs_by_symbol:
                rounded_qty = float(quantity)
                if rounded_qty <= 0:
                    return {
                        "Success": False,
                        "ErrorCode": "QTY_ROUNDS_TO_ZERO",
                        "ErrorMessage": f"qty {quantity} is not positive",
                    }
                rounded_price = float(price) if price is not None else None
            else:
                self.log(
                    f"REJECTED: place_order for unknown pair {sym} | "
                    "no TradingPair precision data — order would be sent unrounded. "
                    "Check /v3/exchangeInfo discovery or fallback table.",
                    level="ERROR",
                    source="Gateway",
                )
                return {
                    "Success": False,
                    "ErrorCode": "NO_PRECISION_DATA",
                    "ErrorMessage": f"No TradingPair for {sym}; order rejected to prevent step-size error",
                }
        else:
            rounded_qty = tp.quantize_quantity(float(quantity))
            if rounded_qty <= 0:
                self.log(
                    f"REJECTED: place_order {sym} qty={quantity} rounds to {rounded_qty} "
                    f"(amount_precision={tp.amount_precision}) — would be zero/negative",
                    level="ERROR",
                    source="Gateway",
                )
                return {
                    "Success": False,
                    "ErrorCode": "QTY_ROUNDS_TO_ZERO",
                    "ErrorMessage": f"qty {quantity} rounds to {rounded_qty} at precision {tp.amount_precision}",
                }

            rounded_price = float(price) if price is not None else None
            if ot == "LIMIT" and rounded_price is not None and rounded_price > 0:
                rounded_price = tp.quantize_price(rounded_price)

        payload: Dict[str, Any] = {
            "timestamp": self._ts_ms(),
            "pair": pair,
            "side": side,
            "quantity": rounded_qty,
            "type": ot,
        }
        if ot == "LIMIT":
            payload["price"] = float(rounded_price if rounded_price is not None else 0.0)

        if rounded_qty != float(quantity) or (
            ot == "LIMIT" and price is not None and rounded_price is not None and float(price) != rounded_price
        ):
            self.log(
                f"precision: {sym} qty {quantity}→{rounded_qty} (amt_prec={tp.amount_precision})"
                + (
                    f" price {price}→{rounded_price} (px_prec={tp.price_precision})"
                    if ot == "LIMIT"
                    else ""
                ),
                level="DEBUG",
                source="Gateway",
            )

        resp = self._request_post("/v3/place_order", data=payload, signed=True)
        if isinstance(resp, dict) and resp.get("Success") is False:
            err_code = resp.get("ErrorCode", resp.get("Code", ""))
            err_msg = resp.get("ErrorMessage", resp.get("Message", str(resp)[:300]))
            self.log(
                f"ERROR: place_order failed | pair={pair} side={side} qty={rounded_qty} type={ot} | "
                f"Success=False ErrorCode={err_code} ErrorMessage={err_msg}",
                level="ERROR",
                source="Gateway",
            )
        return resp

    def cancel_order(self, order_id: str | None = None, symbol: str | None = None) -> Dict[str, Any] | None:
        """POST /v3/cancel_order (SIGNED). Returns raw API response dict or None."""
        payload: Dict[str, Any] = {"timestamp": self._ts_ms()}
        if order_id is not None:
            payload["order_id"] = order_id
        if symbol:
            payload["pair"] = self._to_roostoo_pair(symbol)
        resp = self._request_post("/v3/cancel_order", data=payload, signed=True)
        if isinstance(resp, dict) and resp.get("Success") is False:
            err_code = resp.get("ErrorCode", resp.get("Code", ""))
            err_msg = resp.get("ErrorMessage", resp.get("Message", str(resp)[:300]))
            self.log(
                f"ERROR: cancel_order failed | order_id={order_id} symbol={symbol} | "
                f"Success=False ErrorCode={err_code} ErrorMessage={err_msg}",
                level="ERROR",
                source="Gateway",
            )
        return resp

    def query_order(
        self,
        order_id: str | None = None,
        symbol: str | None = None,
        pending_only: bool | None = None,
        offset: int | None = None,
        limit: int | None = None,
    ) -> Dict[str, Any] | None:
        """POST /v3/query_order (SIGNED). Returns raw API response dict or None."""
        payload: Dict[str, Any] = {"timestamp": self._ts_ms()}
        if order_id is not None:
            payload["order_id"] = order_id
        else:
            if symbol:
                payload["pair"] = self._to_roostoo_pair(symbol)
            if pending_only is not None:
                payload["pending_only"] = "TRUE" if pending_only else "FALSE"
            if offset is not None:
                payload["offset"] = int(offset)
            if limit is not None:
                payload["limit"] = int(limit)
        return self._request_post("/v3/query_order", data=payload, signed=True)

    def on_timer(self) -> None:
        """Poll orders + refresh cached account state every 10 timer ticks."""
        self._timer_seconds += 1
        if self._timer_seconds < 10:
            return
        self._timer_seconds = 0

        self._poll_orders_and_emit()
        self._refresh_account_cache()

    # ---------------- cached account snapshot (for control UI) ----------------

    def _refresh_account_cache(self) -> None:
        """
        Refresh cached balance and pending orders (from query_order).
        Called every 10 ticks from on_timer.
        """
        now = time.time()
        try:
            self.log("query: /v3/balance (cache refresh)", level="DEBUG", source="Gateway")
            bal = self._request_get("/v3/balance", params={"timestamp": self._ts_ms()}, signed=True)
            if isinstance(bal, dict):
                # Roostoo can return SpotWallet instead of Wallet.
                # Normalize so the control UI has a consistent field.
                if "Wallet" not in bal and isinstance(bal.get("SpotWallet"), dict):
                    bal["Wallet"] = bal.get("SpotWallet")
                self._cached_balance = bal
                self._cached_balance_ts = now
        except Exception as e:
            self.log(
                f"ERROR: /v3/balance cache refresh failed | exception={type(e).__name__}: {e} | "
                f"account UI will show stale or empty balance",
                level="ERROR",
                source="Gateway",
            )

        try:
            self.log("query: /v3/query_order pending_only (cache refresh)", level="DEBUG", source="Gateway")
            qo = self.query_order(pending_only=True, limit=200)
            if isinstance(qo, dict):
                self._last_order_query_ts = now
                # Maintain _order_map: merge OrderMatched into our order store (pending count derived from _strategy_pending)
                matched = qo.get("OrderMatched")
                if isinstance(matched, list):
                    for item in matched:
                        if isinstance(item, dict):
                            self._merge_order_from_api(item, strategy_name=None)
        except Exception as e:
            self.log(
                f"ERROR: query_order pending cache refresh failed | exception={type(e).__name__}: {e} | "
                f"account UI will show stale or empty pending orders",
                level="ERROR",
                source="Gateway",
            )

    def get_balance(self) -> dict[str, Any] | None:
        """Return cached balance (no API call). Refreshed by on_timer / _refresh_account_cache."""
        return self._cached_balance

    def get_cached_balance(self) -> dict[str, Any] | None:
        """Alias for get_balance()."""
        return self.get_balance()

    def get_pending_count(self) -> dict[str, Any]:
        """Return pending count derived from _order_map / _strategy_pending (no API call)."""
        pairs: dict[str, int] = {}
        for strat, ids in self._strategy_pending.items():
            for oid in ids:
                data = self._order_map.get(oid)
                if data is None:
                    continue
                pair = self._to_roostoo_pair(data.symbol) if data.symbol else ""
                if pair:
                    pairs[pair] = pairs.get(pair, 0) + 1
        return {
            "Success": True,
            "ErrMsg": "",
            "TotalPending": sum(pairs.values()),
            "OrderPairs": pairs,
        }

    def get_cached_pending_count(self) -> dict[str, Any]:
        """Alias for get_pending_count()."""
        return self.get_pending_count()

    def pending_count(self) -> dict[str, Any]:
        """Alias for get_pending_count() (backward compat)."""
        return self.get_pending_count()

    def _merge_order_from_api(self, item: dict[str, Any], strategy_name: str | None = None) -> OrderData | None:
        """
        Map one Roostoo ``OrderDetail`` or ``OrderMatched[]`` element into ``OrderData``.

        Field names follow ``third_party/Roostoo-API-Documents/README.md`` (Query order / New order).
        """
        oid_raw = item.get("OrderID")
        if oid_raw is None:
            return None
        oid = str(oid_raw).strip()
        if not oid:
            return None
        # Attribution: explicit strategy wins; else keep existing map entry; else unknown \"?\".
        if strategy_name is not None and str(strategy_name).strip():
            strat = str(strategy_name).strip()
        elif oid in self._order_map:
            prev = self._order_map[oid].strategy_name
            strat = prev if prev and str(prev).strip() else "?"
        else:
            strat = "?"
        pair = str(item.get("Pair") or "")
        if "/" in pair:
            base, quote = pair.split("/", 1)
            symbol = f"{base}USDT" if quote == "USD" else f"{base}{quote}"
        else:
            symbol = ""

        fq_raw = item.get("FilledQuantity")
        favg_raw = item.get("FilledAverPrice")

        data = OrderData(
            order_id=oid,
            symbol=symbol,
            side=str(item.get("Side") or ""),
            quantity=float(item.get("Quantity") or 0),
            price=float(item.get("Price") or 0),
            status=str(item.get("Status") or "PENDING"),
            order_type=str(item.get("Type") or "LIMIT"),
            filled_quantity=float(fq_raw if fq_raw is not None else 0),
            filled_avg_price=float(favg_raw if favg_raw is not None else 0),
            role=str(item.get("Role") or "") or None,
            stop_type=str(item.get("StopType") or "") or None,
            create_ts=item.get("CreateTimestamp"),
            finish_ts=item.get("FinishTimestamp"),
            strategy_name=strat or None,
        )
        self._order_map[oid] = data
        status = (data.status or "").upper()
        self._pending_discard_oid_everywhere(oid)
        if status not in _FINISHED_STATUSES:
            if strat not in self._strategy_pending:
                self._strategy_pending[strat] = set()
            self._strategy_pending[strat].add(oid)
        return data

    def get_cached_orders_snapshot(self) -> dict[str, Any]:
        """
        Snapshot of order-related cached state without hitting the exchange.
        tracks: from _order_map (OrderData), maintained by placement + query_order.
        Order table shows status; no separate pending display needed.
        """
        tracks = []
        for d in self._order_map.values():
            pair = self._to_roostoo_pair(d.symbol) if d.symbol else ""
            tracks.append({
                "order_id": d.order_id,
                "strategy_name": d.strategy_name or "?",
                "symbol": d.symbol,
                "pair": pair,
                "side": d.side,
                "type": getattr(d, "order_type", "") or "",
                "status": d.status,
                "price": d.price,
                "quantity": d.quantity,
                "filled_quantity": d.filled_quantity,
                "filled_avg_price": d.filled_avg_price,
                "create_timestamp": d.create_ts,
                "finish_timestamp": d.finish_ts,
                "role": d.role or "",
                "stop_type": d.stop_type or "",
            })
        return {
            "tracks": tracks,
            "cached_balance_ts": self._cached_balance_ts,
            "last_order_query_ts": self._last_order_query_ts,
        }

    # ---------------- order polling -> events ----------------

    def register_order(
        self,
        strategy_name: str,
        order_id: str,
        symbol: str,
        side: str,
        quantity: float = 0.0,
        price: float = 0.0,
        order_type: str = "LIMIT",
        api_detail: dict[str, Any] | None = None,
    ) -> None:
        """
        Create OrderData from placement and save into strategy order map.
        Subsequent query_order calls will maintain this map with updated data.
        """
        if not order_id:
            return
        oid = str(order_id)
        strat = strategy_name or "default"
        if not api_detail:
            # Roostoo Public API (README.md) returns OrderDetail inside place_order response.
            # If it's missing, we cannot reliably build the canonical OrderData mapping.
            self.log(
                f"WARN: register_order skipped | api_detail is None | oid={oid} symbol={symbol} strategy={strat}",
                level="WARN",
                source="Gateway",
            )
            return

        merged = self._merge_order_from_api(api_detail, strategy_name=strat)
        if merged is None:
            self.log(
                f"WARN: register_order | api_detail present but could not parse OrderID | oid={oid} strategy={strat}",
                level="WARN",
                source="Gateway",
            )
            return

        # Emit immediately so StrategyEngine holdings reflect reality.
        # For MARKET taker orders, they may never enter the polling loop.
        try:
            merged_status = (merged.status or "").upper()
            self.log(
                f"[Gateway] register_order: strategy={strat} order_id={oid} symbol={merged.symbol} side={merged.side} "
                f"type={merged.order_type} status={merged_status} qty={float(merged.quantity or 0.0)} "
                f"filled_qty={float(merged.filled_quantity or 0.0)} filled_avg={float(merged.filled_avg_price or 0.0)}",
                level="INFO",
                source="Gateway",
            )
        except Exception:
            pass
        if self.main_engine is not None:
            try:
                if hasattr(self.main_engine, "strategy_engine"):
                    self.main_engine.strategy_engine.on_order(merged)
                if hasattr(self.main_engine, "risk_engine"):
                    self.main_engine.risk_engine.on_order(merged)
            except Exception:
                pass

    def get_pending_orders_by_symbol(self, strategy_name: str) -> dict[str, list[str]]:
        """
        Return pending order ids grouped by symbol for a strategy.
        Result: {symbol: [order_id, ...], ...} — strategies can use this instead of tracking locally.
        """
        strat = strategy_name or "default"
        pending = self._strategy_pending.get(strat, set())
        by_symbol: dict[str, list[str]] = {}
        for oid in pending:
            data = self._order_map.get(oid)
            if data is None:
                continue
            sym = data.symbol
            if sym not in by_symbol:
                by_symbol[sym] = []
            by_symbol[sym].append(oid)
        for sym in by_symbol:
            by_symbol[sym] = sorted(by_symbol[sym])
        return by_symbol

    def _poll_orders_and_emit(self) -> None:
        """
        Poll /v3/query_order for orders in _order_map that are not yet finished.
        Update _order_map with latest data; emit on_order when changed.
        """
        me = self.main_engine
        to_poll = [oid for oid in self._order_map if any(oid in ids for ids in self._strategy_pending.values())]
        if not to_poll or me is None:
            return

        self.log(f"query: /v3/query_order batch size={len(to_poll)}", level="DEBUG", source="Gateway")

        finished: list[str] = []
        for oid in to_poll:
            data = self._order_map.get(oid)
            if data is None:
                continue
            body = self.query_order(order_id=oid)
            if not isinstance(body, dict):
                self.log(
                    f"WARN: order poll order_id={oid} symbol={data.symbol} returned non-dict | "
                    f"strategy={data.strategy_name or '?'} | check _request_post logs for API error",
                    level="WARN",
                    source="Gateway",
                )
                continue
            if body.get("Success") is False:
                err_code = body.get("ErrorCode", body.get("Code", ""))
                err_msg = body.get("ErrorMessage", body.get("Message", str(body)[:200]))
                self.log(
                    f"WARN: order poll order_id={oid} symbol={data.symbol} Success=False | "
                    f"ErrorCode={err_code} ErrorMessage={err_msg} | strategy={data.strategy_name or '?'}",
                    level="WARN",
                    source="Gateway",
                )
                continue
            detail = body.get("OrderDetail")
            if not isinstance(detail, dict):
                matched = body.get("OrderMatched")
                if isinstance(matched, list) and matched and isinstance(matched[0], dict):
                    detail = matched[0]
            if not isinstance(detail, dict):
                continue

            prev_filled = data.filled_quantity
            prev_status = data.status
            updated = self._merge_order_from_api(detail, strategy_name=data.strategy_name or "?")
            if updated is None:
                continue
            status = (updated.status or "").upper()
            changed = (updated.filled_quantity != prev_filled) or (status != (prev_status or "").upper())
            if changed:
                try:
                    delta_filled = float(updated.filled_quantity or 0.0) - float(prev_filled or 0.0)
                    self.log(
                        f"[Gateway] poll_update: order_id={oid} strategy={updated.strategy_name or '?'} "
                        f"symbol={updated.symbol} side={updated.side} status {str(prev_status).upper()}→{status} "
                        f"filled_qty {float(prev_filled or 0.0):.8f}→{float(updated.filled_quantity or 0.0):.8f} "
                        f"(delta={delta_filled:.8f})",
                        level="DEBUG",
                        source="Gateway",
                    )
                except Exception:
                    pass
                # Only persist to SQLite when order is FILLED (not PENDING, PARTIALLY_FILLED, etc.)
                if status == "FILLED" and hasattr(me, "order_store") and me.order_store is not None:
                    try:
                        now = time.time()
                        raw_json = None
                        if detail:
                            try:
                                raw_json = json.dumps(detail, ensure_ascii=False)
                            except Exception:
                                pass
                        conn = sqlite3.connect(me.order_store.db_path)
                        try:
                            conn.execute(
                                """
                                INSERT INTO orders (
                                  order_id, strategy_name, symbol, side, status,
                                  quantity, price, filled_quantity, filled_avg_price,
                                  updated_ts, raw_json
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(order_id) DO UPDATE SET
                                  strategy_name=excluded.strategy_name,
                                  symbol=excluded.symbol,
                                  side=excluded.side,
                                  status=excluded.status,
                                  quantity=excluded.quantity,
                                  price=excluded.price,
                                  filled_quantity=excluded.filled_quantity,
                                  filled_avg_price=excluded.filled_avg_price,
                                  updated_ts=excluded.updated_ts,
                                  raw_json=COALESCE(excluded.raw_json, orders.raw_json);
                                """,
                                (
                                    str(updated.order_id),
                                    str(getattr(updated, "strategy_name", "") or ""),
                                    str(updated.symbol),
                                    str(updated.side),
                                    str(updated.status),
                                    float(updated.quantity or 0.0),
                                    float(updated.price or 0.0),
                                    float(updated.filled_quantity or 0.0),
                                    float(updated.filled_avg_price or 0.0),
                                    float(now),
                                    raw_json,
                                ),
                            )
                            conn.commit()
                        finally:
                            conn.close()
                    except Exception:
                        pass
                if hasattr(me, "strategy_engine"):
                    me.strategy_engine.on_order(updated)
                if hasattr(me, "risk_engine"):
                    me.risk_engine.on_order(updated)

            if status in _FINISHED_STATUSES:
                finished.append(oid)

        for oid in finished:
            d = self._order_map.get(oid)
            if d is not None:
                strat = d.strategy_name or "default"
                if strat in self._strategy_pending:
                    self._strategy_pending[strat].discard(oid)
                if "?" in self._strategy_pending:
                    self._strategy_pending["?"].discard(oid)



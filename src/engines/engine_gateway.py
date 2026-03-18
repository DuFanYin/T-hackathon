"""
Gateway engine for Roostoo mock exchange.

- Stateless REST: no persistent connections, every call is signed.
- Market data: on each timer tick, pull ticker for each trading pair and emit `EVENT_BAR` with `BarData`.
- Orders: send/cancel via `/v3/place_order` and `/v3/cancel_order` using HMAC-SHA256 signatures.

API keys are read from environment:
- General_Portfolio_Testing_API_KEY / General_Portfolio_Testing_API_SECRET
- Competition_API_KEY / Competition_API_SECRET

By default this engine uses the general testing credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any, Dict, Optional

import requests

from src.utilities.base_engine import BaseEngine
from src.utilities.events import EVENT_BAR, EVENT_ORDER
from src.utilities.interval import Interval
from src.utilities.object import BarData, OrderData

from dataclasses import dataclass


class GatewayEngine(BaseEngine):
    """Roostoo vendor adapter: send_order/cancel_order; on_timer() fetches tickers and emits EVENT_BAR per trading pair."""

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

        # order_id -> tracking info for polling query_order and emitting EVENT_ORDER
        self._order_tracks: dict[str, _OrderTrack] = {}
        # strategy_name -> set of currently pending order_ids (for quick lookup/inspection)
        self._strategy_pending: dict[str, set[str]] = {}

        # ---------------- cached account state (refreshed by engine timer, NOT by UI) ----------------
        self._cached_balance: dict[str, Any] | None = None
        self._cached_pending_count: dict[str, Any] | None = None
        self._cached_balance_ts: float | None = None
        self._cached_pending_count_ts: float | None = None
        self._account_cache_interval_sec: float = 10.0

    # ---------------- helpers ----------------

    def _headers(self, params: Dict[str, Any]) -> Dict[str, str]:
        query_string = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
        secret_bytes = self._secret.encode("utf-8")
        sig = hmac.new(secret_bytes, query_string.encode("utf-8"), hashlib.sha256).hexdigest()
        # Some environments expect both legacy RST-API-KEY and generic api-key headers.
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
            headers = self._headers(data) if signed else None
            url = f"{self.base_url}{path}"
            resp = requests.post(url, data=data, headers=headers, timeout=3.0)
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

    def get_balance(self) -> Dict[str, Any] | None:
        """GET /v3/balance (SIGNED)."""
        params: Dict[str, Any] = {"timestamp": self._ts_ms()}
        return self._request_get("/v3/balance", params=params, signed=True)

    def pending_count(self) -> Dict[str, Any] | None:
        """GET /v3/pending_count (SIGNED)."""
        params: Dict[str, Any] = {"timestamp": self._ts_ms()}
        return self._request_get("/v3/pending_count", params=params, signed=True)

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float | None = None,
        order_type: str | None = None,
    ) -> Dict[str, Any] | None:
        """POST /v3/place_order (SIGNED). Returns raw API response dict or None."""
        pair = self._to_roostoo_pair(symbol)
        payload: Dict[str, Any] = {
            "timestamp": self._ts_ms(),
            "pair": pair,
            "side": side,
            "quantity": quantity,
        }

        inferred = "MARKET" if price is None else "LIMIT"
        payload["type"] = (order_type or inferred).upper()
        if payload["type"] == "LIMIT":
            payload["price"] = float(price if price is not None else 0.0)

        resp = self._request_post("/v3/place_order", data=payload, signed=True)
        if isinstance(resp, dict) and resp.get("Success") is False:
            err_code = resp.get("ErrorCode", resp.get("Code", ""))
            err_msg = resp.get("ErrorMessage", resp.get("Message", str(resp)[:300]))
            self.log(
                f"ERROR: place_order failed | pair={pair} side={side} qty={quantity} type={payload['type']} | "
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
        """Poll orders + refresh cached account state; market data is owned by MarketEngine.on_timer()."""
        self._poll_orders_and_emit()
        self._refresh_account_cache(force=False)

    # ---------------- cached account snapshot (for control UI) ----------------

    def _refresh_account_cache(self, *, force: bool) -> None:
        """
        Refresh cached balance/pending_count on a throttle.

        Important: control-plane UI reads cached values only; it must not drive exchange calls.
        """
        now = time.time()
        last = min(
            (t for t in (self._cached_balance_ts, self._cached_pending_count_ts) if t is not None),
            default=0.0,
        )
        if (not force) and (now - last < self._account_cache_interval_sec):
            return

        try:
            self.log("query: /v3/balance (cache refresh)" + (" [force]" if force else ""), level="DEBUG", source="Gateway")
            bal = self.get_balance()
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
            self.log("query: /v3/pending_count (cache refresh)" + (" [force]" if force else ""), level="DEBUG", source="Gateway")
            pc = self.pending_count()
            if isinstance(pc, dict):
                self._cached_pending_count = pc
                self._cached_pending_count_ts = now
        except Exception as e:
            self.log(
                f"ERROR: /v3/pending_count cache refresh failed | exception={type(e).__name__}: {e} | "
                f"account UI will show stale or empty pending count",
                level="ERROR",
                source="Gateway",
            )

    def get_cached_balance(self) -> dict[str, Any] | None:
        return self._cached_balance

    def get_cached_pending_count(self) -> dict[str, Any] | None:
        return self._cached_pending_count

    def get_cached_orders_snapshot(self) -> dict[str, Any]:
        """
        Snapshot of order-related cached state without hitting the exchange.

        - pending_by_strategy: current pending order ids per strategy (from local tracking)
        - tracks: last known per-order status/fill (from polling)
        """
        return {
            "pending_by_strategy": self.get_pending_orders(),
            "tracks": [
                {
                    "order_id": t.order_id,
                    "strategy_name": t.strategy_name,
                    "symbol": t.symbol,
                    "side": t.side,
                    "last_status": t.last_status,
                    "last_filled_qty": t.last_filled_qty,
                }
                for t in self._order_tracks.values()
            ],
            "cached_balance_ts": self._cached_balance_ts,
            "cached_pending_count_ts": self._cached_pending_count_ts,
        }

    # ---------------- order polling -> events ----------------

    def register_order(self, strategy_name: str, order_id: str, symbol: str, side: str) -> None:
        """Register an order so gateway can poll status via query_order and emit EVENT_ORDER updates."""
        if not order_id:
            return
        oid = str(order_id)
        strat = strategy_name or "default"
        self._order_tracks[oid] = _OrderTrack(
            order_id=oid,
            strategy_name=strat,
            symbol=str(symbol),
            side=str(side or "").upper(),
        )
        if strat not in self._strategy_pending:
            self._strategy_pending[strat] = set()
        self._strategy_pending[strat].add(oid)

    def get_pending_orders(self, strategy_name: str | None = None) -> dict[str, list[str]]:
        """
        Return current pending order ids.

        - If strategy_name is given, returns {strategy_name: [order_ids]} (or {} if none).
        - If None, returns a full mapping {strategy_name: [order_ids]}.
        """
        if strategy_name is not None:
            strat = strategy_name or "default"
            ids = sorted(self._strategy_pending.get(strat, ()))
            return {strat: ids} if ids else {}
        return {s: sorted(ids) for s, ids in self._strategy_pending.items() if ids}

    def get_pending_orders_by_symbol(self, strategy_name: str) -> dict[str, list[str]]:
        """
        Return pending order ids grouped by symbol for a strategy.
        Result: {symbol: [order_id, ...], ...} — strategies can use this instead of tracking locally.
        """
        strat = strategy_name or "default"
        by_symbol: dict[str, list[str]] = {}
        for oid, track in self._order_tracks.items():
            if track.strategy_name != strat:
                continue
            sym = track.symbol
            if sym not in by_symbol:
                by_symbol[sym] = []
            by_symbol[sym].append(oid)
        for sym in by_symbol:
            by_symbol[sym] = sorted(by_symbol[sym])
        return by_symbol

    def _poll_orders_and_emit(self) -> None:
        """
        Poll /v3/query_order for tracked orders and synchronously update engines.

        To keep ordering intuitive for strategies, we directly call:
        - strategy_engine.on_order(OrderData)
        - risk_engine.on_order(OrderData)

        instead of enqueueing EVENT_ORDER and waiting for the next tick.
        """
        me = self.main_engine
        if not self._order_tracks or me is None:
            return

        # Query calls only (place/cancel are NOT counted as "query").
        self.log(f"query: /v3/query_order batch size={len(self._order_tracks)}", level="DEBUG", source="Gateway")

        finished: list[str] = []
        for oid, track in list(self._order_tracks.items()):
            body = self.query_order(order_id=oid)
            if not isinstance(body, dict):
                self.log(
                    f"WARN: order poll order_id={oid} symbol={track.symbol} returned non-dict | "
                    f"strategy={track.strategy_name} | check _request_post logs for API error",
                    level="WARN",
                    source="Gateway",
                )
                continue
            if body.get("Success") is False:
                err_code = body.get("ErrorCode", body.get("Code", ""))
                err_msg = body.get("ErrorMessage", body.get("Message", str(body)[:200]))
                self.log(
                    f"WARN: order poll order_id={oid} symbol={track.symbol} Success=False | "
                    f"ErrorCode={err_code} ErrorMessage={err_msg} | strategy={track.strategy_name}",
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
            if not detail:
                continue

            status = str(detail.get("Status", "") or "").upper()
            filled_qty = float(detail.get("FilledQuantity", 0.0) or 0.0)
            filled_avg = float(detail.get("FilledAverPrice", 0.0) or 0.0)
            qty = float(detail.get("Quantity", 0.0) or 0.0)
            price = float(detail.get("Price", 0.0) or 0.0)

            changed = (filled_qty != track.last_filled_qty) or (status != track.last_status)
            if changed:
                track.last_filled_qty = filled_qty
                track.last_status = status
                data = OrderData(
                    order_id=oid,
                    symbol=track.symbol,
                    side=track.side,
                    quantity=qty,
                    price=price,
                    status=status or "UNKNOWN",
                    filled_quantity=filled_qty,
                    filled_avg_price=filled_avg,
                    strategy_name=track.strategy_name,
                    ts=None,
                )
                # Persist the latest order state (sqlite) if configured on the main engine.
                if hasattr(me, "order_store") and me.order_store is not None:
                    try:
                        me.order_store.upsert(data, raw=detail if isinstance(detail, dict) else None)
                    except Exception:
                        pass
                # Synchronously update engines so strategies see up-to-date positions
                if hasattr(me, "strategy_engine"):
                    me.strategy_engine.on_order(data)
                if hasattr(me, "risk_engine"):
                    me.risk_engine.on_order(data)

            if status in ("FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED"):
                finished.append(oid)

        for oid in finished:
            track = self._order_tracks.pop(oid, None)
            if track is not None:
                strat = track.strategy_name or "default"
                if strat in self._strategy_pending:
                    self._strategy_pending[strat].discard(oid)

    # ---------------- event bridge ----------------

    def put_bar(self, bar_data: BarData) -> None:
        """Emit EVENT_BAR so the event engine routes to market engine."""
        if self.main_engine:
            self.main_engine.put_event(EVENT_BAR, bar_data)


@dataclass(slots=True)
class _OrderTrack:
    order_id: str
    strategy_name: str
    symbol: str
    side: str
    last_filled_qty: float = 0.0
    last_status: str = ""

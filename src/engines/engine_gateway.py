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

        # order_id -> tracking info for polling query_order and emitting EVENT_ORDER
        self._order_tracks: dict[str, _OrderTrack] = {}
        # strategy_name -> set of currently pending order_ids (for quick lookup/inspection)
        self._strategy_pending: dict[str, set[str]] = {}

    # ---------------- helpers ----------------

    def _generate_signature(self, params: Dict[str, Any]) -> str:
        query_string = "&".join(f"{k}={params[k]}" for k in sorted(params.keys()))
        secret_bytes = self._secret.encode("utf-8")
        m = hmac.new(secret_bytes, query_string.encode("utf-8"), hashlib.sha256)
        return m.hexdigest()

    def _headers(self, params: Dict[str, Any]) -> Dict[str, str]:
        sig = self._generate_signature(params)
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

    def _request_get(self, path: str, params: Dict[str, Any], signed: bool) -> Dict[str, Any] | None:
        try:
            headers = self._headers(params) if signed else None
            url = f"{self.base_url}{path}"
            resp = requests.get(url, params=params, headers=headers, timeout=3.0)
            if resp.status_code != 200:
                print(f"[Gateway] GET {url} failed status={resp.status_code} body={resp.text}")
                return None
            try:
                body = resp.json()
            except Exception as e:
                print(f"[Gateway] GET {url} json error: {e} body={resp.text}")
                return None
            if not isinstance(body, dict):
                print(f"[Gateway] GET {url} unexpected JSON type: {type(body)}")
                return None
            return body
        except Exception as e:
            print(f"[Gateway] GET {path} exception: {e}")
            return None

    def _request_post(self, path: str, data: Dict[str, Any], signed: bool) -> Dict[str, Any] | None:
        try:
            headers = self._headers(data) if signed else None
            url = f"{self.base_url}{path}"
            resp = requests.post(url, data=data, headers=headers, timeout=3.0)
            if resp.status_code != 200:
                print(f"[Gateway] POST {url} failed status={resp.status_code} body={resp.text}")
                return None
            try:
                body = resp.json()
            except Exception as e:
                print(f"[Gateway] POST {url} json error: {e} body={resp.text}")
                return None
            if not isinstance(body, dict):
                print(f"[Gateway] POST {url} unexpected JSON type: {type(body)}")
                return None
            return body
        except Exception as e:
            print(f"[Gateway] POST {path} exception: {e}")
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
        body = self._request_get("/v3/exchangeInfo", params={}, signed=False)
        if body is None:
            print("[Gateway] /v3/exchangeInfo returned None (network/parse failure)")
            return None
        if not isinstance(body, dict):
            print(f"[Gateway] /v3/exchangeInfo unexpected body type: {type(body)}")
            return None
        if body.get("Success") is False:
            # Log full body so we can see error code/message from Roostoo.
            print(f"[Gateway] /v3/exchangeInfo error: {body}")
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

        return self._request_post("/v3/place_order", data=payload, signed=True)

    def cancel_order(self, order_id: str | None = None, symbol: str | None = None) -> Dict[str, Any] | None:
        """POST /v3/cancel_order (SIGNED). Returns raw API response dict or None."""
        payload: Dict[str, Any] = {"timestamp": self._ts_ms()}
        if order_id is not None:
            payload["order_id"] = order_id
        if symbol:
            payload["pair"] = self._to_roostoo_pair(symbol)
        return self._request_post("/v3/cancel_order", data=payload, signed=True)

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

    # ---------------- market data -> bars ----------------

    def _fetch_ticker_all(self) -> Dict[str, Dict[str, Any]] | None:
        """
        Fetch latest ticker for all pairs from Roostoo.

        Docs: if `pair` is NOT sent, /v3/ticker returns Data for all listed pairs.
        We use this once per timer tick and then filter down to the active symbols.
        """
        params: Dict[str, Any] = {"timestamp": self._ts_ms()}
        try:
            resp = requests.get(f"{self.base_url}/v3/ticker", params=params, timeout=2.0)
            if resp.status_code != 200:
                return None
            body = resp.json()
            if not isinstance(body, dict):
                return None
            if not body.get("Success", False):
                return None
            data = body.get("Data")
            if not isinstance(data, dict):
                return None
            # Data is { "BTC/USD": {...}, "ETH/USD": {...}, ... }
            return data  # type: ignore[return-value]
        except Exception:
            return None

    def on_timer(self) -> None:
        """Poll ticker once and update all subscribed symbols."""
        if not self.trading_pairs:
            # No known symbols: still allow order polling even if market data is disabled.
            self._poll_orders_and_emit()
            return

        # One bulk ticker call; then update subscribed internal symbols.
        all_data = self._fetch_ticker_all()
        if not isinstance(all_data, dict):
            self._poll_orders_and_emit()
            return

        for symbol in self.trading_pairs:
            pair = self._to_roostoo_pair(symbol)
            item = all_data.get(pair)
            if not isinstance(item, dict):
                continue

            # Roostoo ticker item keys: MaxBid, MinAsk, LastPrice, Change, CoinTradeValue, UnitTradeValue
            last = float(item.get("LastPrice", 0.0))
            bid = float(item.get("MaxBid", 0.0) or 0.0)
            ask = float(item.get("MinAsk", 0.0) or 0.0)
            change = float(item.get("Change", 0.0) or 0.0)
            # No OHLC in ticker response; represent as 1-tick bar for now.
            high = last
            low = last
            open_ = last
            volume = float(item.get("CoinTradeValue", 0.0) or 0.0)
            notional = float(item.get("UnitTradeValue", 0.0) or 0.0)

            if last <= 0:
                continue

            # Update snapshot fields for the symbol.
            me = self.main_engine
            if me is not None and hasattr(me, "market_engine"):
                me.market_engine.update_symbol_from_ticker(
                    symbol,
                    last_price=last,
                    bid_price=bid if bid > 0 else None,
                    ask_price=ask if ask > 0 else None,
                    volume_24h=volume,
                    notional_24h=notional,
                    change_24h=change,
                )

            bar = BarData(
                symbol=symbol,
                open=open_,
                high=high,
                low=low,
                close=last,
                volume=volume,
                ts=None,
            )
            self.put_bar(bar)

        self._poll_orders_and_emit()

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

    @staticmethod
    def _parse_order_detail(body: dict) -> dict | None:
        if not isinstance(body, dict) or body.get("Success") is False:
            return None
        if isinstance(body.get("OrderDetail"), dict):
            return body["OrderDetail"]
        matched = body.get("OrderMatched")
        if isinstance(matched, list) and matched:
            first = matched[0]
            if isinstance(first, dict):
                return first
        return None

    def _poll_orders_and_emit(self) -> None:
        """
        Poll /v3/query_order for tracked orders and synchronously update engines.

        To keep ordering intuitive for strategies, we directly call:
        - position_engine.on_order(OrderData)
        - strategy_engine.on_order(OrderData)
        - risk_engine.on_order(OrderData)

        instead of enqueueing EVENT_ORDER and waiting for the next tick.
        """
        me = self.main_engine
        if not self._order_tracks or me is None:
            return

        finished: list[str] = []
        for oid, track in list(self._order_tracks.items()):
            body = self.query_order(order_id=oid)
            if not isinstance(body, dict):
                continue
            detail = self._parse_order_detail(body)
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
                # Synchronously update engines so strategies see up-to-date positions
                if hasattr(me, "position_engine"):
                    me.position_engine.on_order(data)
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

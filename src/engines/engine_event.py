"""
Event engine: queue, timer thread, and deterministic routing for all events and intents.
"""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from threading import Thread
from time import sleep
from typing import Any, TYPE_CHECKING

from src.control.log_store import format_engine_log_timestamp
from src.engines.engine_gateway import GatewayEngine
from src.utilities.base_engine import BaseEngine
from src.utilities.events import EVENT_BAR, EVENT_LOG, EVENT_ORDER, EVENT_TIMER
from src.utilities.intents import (
    INTENT_CANCEL_ORDER,
    INTENT_LOG,
    INTENT_PLACE_ORDER,
)
from src.utilities.object import CancelOrderRequest, OrderRequest

if TYPE_CHECKING:
    from .engine_main import MainEngine


class Event:
    """Event object carrying a type string and arbitrary payload."""

    def __init__(self, event_type: str, data: Any | None = None) -> None:
        self.type: str = event_type
        self.data: Any | None = data


HandlerType = Callable[[Event], None]


class EventEngine(BaseEngine):
    """In-process event bus and timer; routes events and intents to main engine's engines in a fixed order."""

    def __init__(
        self,
        main_engine: "MainEngine | None" = None,
        engine_name: str = "Event",
        interval: float = 1.0,
    ) -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        self._interval: float = float(interval)
        self._queue: Queue[Event] = Queue()
        self._active: bool = False

        self._thread: Thread = Thread(target=self._run, name="EventEngineWorker", daemon=True)
        self._timer: Thread = Thread(target=self._run_timer, name="EventEngineTimer", daemon=True)

    # ---------------- internal worker/timer ----------------

    def _run(self) -> None:
        while self._active:
            try:
                event: Event = self._queue.get(block=True, timeout=1.0)
                self._process(event)
            except Empty:
                continue

    def _process(self, event: Event) -> None:
        if not self.main_engine:
            return

        etype = event.type

        if etype == EVENT_BAR:
            self._handle_bar(event)
        elif etype == EVENT_ORDER:
            self._handle_order(event)
        elif etype == EVENT_LOG:
            self._handle_log(event)
        elif etype == EVENT_TIMER:
            self._handle_timer(event)

    def _run_timer(self) -> None:
        while self._active:
            sleep(self._interval)
            if not self._active:
                break
            self.put(Event(EVENT_TIMER))

    # ---------------- public API ----------------

    def start(self) -> None:
        if self._active:
            return

        self._active = True
        if not self._thread.is_alive():
            self._thread = Thread(target=self._run, name="EventEngineWorker", daemon=True)
            self._thread.start()

        if not self._timer.is_alive():
            self._timer = Thread(target=self._run_timer, name="EventEngineTimer", daemon=True)
            self._timer.start()

    def stop(self) -> None:
        if not self._active:
            return

        self._active = False

        if self._timer.is_alive():
            self._timer.join()
        if self._thread.is_alive():
            self._thread.join()

    def close(self) -> None:
        """Cleanup: stop worker and timer (mirrors BaseEngine.close())."""
        self.stop()

    def put(self, event: Event) -> None:
        self._queue.put(event)

    # ---------------- configuration ----------------

    def configure(self, main_engine: "MainEngine") -> None:
        self.set_main_engine(main_engine)

    # ---------------- routing ----------------

    def _handle_bar(self, event: Event) -> None:
        me = self.main_engine
        if me is not None and hasattr(me, "market_engine"):
            me.market_engine.on_bar(event)

    def _handle_order(self, event: Event) -> None:
        me = self.main_engine
        assert me is not None
        me.strategy_engine.on_order(event)

    def _handle_log(self, event: Event) -> None:
        data = event.data
        msg = getattr(data, "msg", None) or str(data)
        level = getattr(data, "level", "INFO") if data is not None else "INFO"
        source = getattr(data, "source", None) or "System" if data is not None else "System"
        try:
            me = self.main_engine
            if me is not None and hasattr(me, "write_log"):
                me.write_log(msg, level=level, source=source)
        except Exception:
            pass
        print(f"{format_engine_log_timestamp()} [{level}] {source} | {msg}")

    def _handle_timer(self, event: Event) -> None:
        me = self.main_engine
        assert me is not None
        # MarketEngine owns market data refresh (Binance klines) per tick.
        if hasattr(me, "market_engine") and me.market_engine is not None:
            me.market_engine.on_timer()

        # Gateway only handles order polling on timer.
        me.gateway_engine.on_timer()
        me.strategy_engine.process_timer_event()
        me.strategy_engine.on_timer()

    # ---------------- intent routing ----------------

    def handle_intent(self, intent_type: str, payload: Any | None = None) -> Any | None:
        if not self.main_engine:
            return None

        me = self.main_engine
        write_log_fn = getattr(me, "write_log", None)

        def _log(msg: str, *, level: str = "INFO", source: str = "EventEngine") -> None:
            # Some integration tests inject a minimal facade without `write_log`.
            if callable(write_log_fn):
                try:
                    write_log_fn(msg, level=level, source=source)
                except Exception:
                    pass

        if intent_type == INTENT_PLACE_ORDER:
            data = payload
            if isinstance(data, OrderRequest):
                price = None if str(data.order_type).upper() == "MARKET" else float(data.price)
                _log(
                    f"[EventEngine] INTENT_PLACE_ORDER calling place_order: strategy={data.strategy_name} "
                    f"symbol={data.symbol} side={data.side} qty={float(data.quantity)} price={data.price} "
                    f"order_type={data.order_type}",
                    level="DEBUG",
                    source="EventEngine",
                )
                resp = me.place_order(
                    symbol=data.symbol,
                    side=data.side,
                    quantity=float(data.quantity),
                    price=price,
                    order_type=data.order_type,
                )
                if isinstance(resp, dict) and resp.get("Success") is False:
                    _log(
                        f"[EventEngine] INTENT_PLACE_ORDER place_order failed: strategy={data.strategy_name} "
                        f"symbol={data.symbol} side={data.side} qty={float(data.quantity)} "
                        f"order_type={data.order_type} err={resp.get('ErrorCode')}/{resp.get('ErrorMessage')}",
                        level="WARN",
                        source="EventEngine",
                    )
                    return None
                order_id = GatewayEngine.extract_order_id_from_place_response(
                    resp if isinstance(resp, dict) else None
                )

                if order_id is None and isinstance(resp, dict) and resp.get("Success") is not False:
                    _log(
                        "place_order: Success=True but OrderDetail.OrderID missing (Roostoo Public API "
                        f"third_party/Roostoo-API-Documents/README.md) — strategy={data.strategy_name} "
                        f"symbol={data.symbol}",
                        level="WARN",
                        source="System",
                    )

                if order_id is not None:
                    oid = str(order_id)
                    strat = getattr(data, "strategy_name", None) or "default"
                    api_detail = resp.get("OrderDetail") if isinstance(resp, dict) else None
                    _log(
                        f"[EventEngine] INTENT_PLACE_ORDER accepted: order_id={oid} strategy={strat} "
                        f"symbol={data.symbol} side={data.side} qty={float(data.quantity)} "
                        f"price={float(data.price) if data.price is not None else 0.0} "
                        f"type={data.order_type} | registering into GatewayEngine",
                        level="INFO",
                        source="EventEngine",
                    )
                    me.gateway_engine.register_order(
                        strategy_name=str(strat),
                        order_id=oid,
                        symbol=str(data.symbol),
                        side=str(data.side),
                        quantity=float(data.quantity),
                        price=float(data.price) if data.price is not None else 0.0,
                        order_type=str(data.order_type or "LIMIT"),
                        api_detail=api_detail,
                    )
                    return oid
                return None
            return None
        if intent_type == INTENT_CANCEL_ORDER:
            data = payload
            if isinstance(data, CancelOrderRequest):
                me.cancel_order(order_id=data.order_id, symbol=data.symbol)
            return None
        if intent_type == INTENT_LOG:
            # Treat payload as log message and emit a LOG event
            me.put_event(EVENT_LOG, payload)
            return None

        return None


"""
Event engine: queue, timer thread, and deterministic routing for all events and intents.
"""

from __future__ import annotations

from collections.abc import Callable
from queue import Empty, Queue
from threading import Thread
from time import sleep
from typing import Any, TYPE_CHECKING

from src.utilities.base_engine import BaseEngine
from src.utilities.events import EVENT_BAR, EVENT_LOG, EVENT_ORDER, EVENT_RISK_ALERT, EVENT_TIMER, EVENT_TRADE
from src.utilities.intents import (
    INTENT_CANCEL_ORDER,
    INTENT_LOG,
    INTENT_PLACE_ORDER,
)

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
        elif etype == EVENT_TRADE:
            self._handle_trade(event)
        elif etype == EVENT_LOG:
            self._handle_log(event)
        elif etype == EVENT_RISK_ALERT:
            self._handle_risk_alert(event)
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
        me.risk_engine.on_order(event)

    def _handle_trade(self, event: Event) -> None:
        me = self.main_engine
        assert me is not None
        me.position_engine.on_trade(event)
        me.strategy_engine.on_trade(event)
        me.risk_engine.on_trade(event)

    def _handle_log(self, event: Event) -> None:
        msg = getattr(event.data, "msg", None) or str(event.data)
        print(f"[LOG] {msg}")

    def _handle_risk_alert(self, event: Event) -> None:
        msg = getattr(event.data, "msg", None) or str(event.data)
        print(f"[RISK] {msg}")

    def _handle_timer(self, event: Event) -> None:
        me = self.main_engine
        assert me is not None
        me.gateway_engine.on_timer()
        me.position_engine.process_timer_event()
        me.strategy_engine.on_timer()
        me.risk_engine.on_timer()

    # ---------------- intent routing ----------------

    def handle_intent(self, intent_type: str, payload: Any | None = None) -> Any | None:
        if not self.main_engine:
            return None

        me = self.main_engine

        if intent_type == INTENT_PLACE_ORDER:
            return me.send_order(payload)
        if intent_type == INTENT_CANCEL_ORDER:
            me.cancel_order(payload)
            return None
        if intent_type == INTENT_LOG:
            # Treat payload as log message and emit a LOG event
            me.put_event(EVENT_LOG, payload)
            return None

        return None


from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Literal, Optional

from src.engines.engine_main import MainEngine


Mode = Literal["mock", "real"]


@dataclass
class SystemStatus:
    running: bool
    mode: Optional[Mode] = None


class EngineManager:
    """
    Owns the lifetime of MainEngine so the control plane can start/stop the trading system.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._engine: MainEngine | None = None
        self._mode: Mode | None = None

    def status(self) -> SystemStatus:
        with self._lock:
            return SystemStatus(running=self._engine is not None, mode=self._mode)

    def get(self) -> MainEngine | None:
        with self._lock:
            return self._engine

    def require(self) -> MainEngine:
        eng = self.get()
        if eng is None:
            raise RuntimeError("system not running")
        return eng

    def start(self, mode: Mode) -> SystemStatus:
        with self._lock:
            if self._engine is not None:
                # Already running; no-op if same mode.
                return SystemStatus(running=True, mode=self._mode)
            self._engine = MainEngine(env_mode=mode)
            self._mode = mode
            return SystemStatus(running=True, mode=self._mode)

    def stop(self) -> SystemStatus:
        with self._lock:
            if self._engine is None:
                return SystemStatus(running=False, mode=None)
            try:
                self._engine.disconnect()
            except Exception:
                pass
            self._engine = None
            self._mode = None
            return SystemStatus(running=False, mode=None)


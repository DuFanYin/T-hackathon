"""
Base engine: all child engines inherit this and hold a main_engine reference and engine_name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


class BaseEngine:
    """Base for gateway, strategy, position, risk, and event engines; provides main_engine and close()."""

    def __init__(
        self,
        main_engine: "MainEngine | None" = None,
        engine_name: str = "",
    ) -> None:
        self._main_engine: "MainEngine | None" = main_engine
        self.engine_name: str = engine_name

    def set_main_engine(self, main_engine: "MainEngine") -> None:
        """Set the main engine reference (used when an engine is injected instead of created by MainEngine)."""
        self._main_engine = main_engine

    @property
    def main_engine(self) -> "MainEngine | None":
        """The main engine this engine is attached to."""
        return self._main_engine

    def close(self) -> None:
        """Override in subclasses for cleanup."""
        pass

from __future__ import annotations

from datetime import datetime


class LogStore:
    """
    Log formatter for control API. Formats messages for disk persistence.
    Format: "MM-DD HH:MM:SS | LEVEL | source | message"
    """

    def append(self, line: str, level: str = "INFO", source: str | None = None) -> str:
        ts = datetime.now().strftime("%m-%d %H:%M:%S")
        lvl = str(level).upper() if level else "INFO"
        if lvl not in ("DEBUG", "INFO", "WARN", "ERROR"):
            lvl = "INFO"
        src = (source or "System").strip() or "System"
        return f"{ts} | {lvl} | {src} | {str(line)}"

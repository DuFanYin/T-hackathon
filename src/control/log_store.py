"""
Log formatting for the control plane. Also exposes ``format_engine_log_timestamp`` for
console echoes (e.g. EventEngine) so all engine-facing wall times match.

Wall clock: **Asia/Singapore**, **24-hour** (SGT). Not for API signing (use Unix epoch ms).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None  # type: ignore[misc, assignment]


def _singapore_tz():
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Asia/Singapore")
        except Exception:
            pass
    return timezone(timedelta(hours=8))


SINGAPORE_TZ = _singapore_tz()


def now_singapore() -> datetime:
    """Current instant as timezone-aware datetime in Singapore."""
    return datetime.now(SINGAPORE_TZ)


def format_engine_log_timestamp(when: datetime | None = None) -> str:
    """
    Log / console prefix: ``MM-DD HH:MM:SS`` in Singapore, 24-hour (%H, not %I).
    If ``when`` is naive, it is treated as UTC then converted to Singapore.
    """
    if when is None:
        dt = now_singapore()
    elif when.tzinfo is None:
        dt = when.replace(tzinfo=timezone.utc).astimezone(SINGAPORE_TZ)
    else:
        dt = when.astimezone(SINGAPORE_TZ)
    return dt.strftime("%m-%d %H:%M:%S")


class LogStore:
    """
    Log formatter for control API. Formats messages for disk persistence.
    Format: "MM-DD HH:MM:SS | LEVEL | source | message"
    """

    def append(self, line: str, level: str = "INFO", source: str | None = None) -> str:
        ts = format_engine_log_timestamp()
        lvl = str(level).upper() if level else "INFO"
        if lvl not in ("DEBUG", "INFO", "WARN", "ERROR"):
            lvl = "INFO"
        src = (source or "System").strip() or "System"
        return f"{ts} | {lvl} | {src} | {str(line)}"

"""
Canonical event type names used across the system.

These are simple string constants so events remain easy to serialize,
log, and route deterministically.
"""

# Market data and price updates
EVENT_TICK = "TICK"  # best bid/ask, last trade, etc.

# Order lifecycle
EVENT_ORDER = "ORDER"  # order state updates
EVENT_TRADE = "TRADE"  # fills/executions

# System / infrastructure
EVENT_LOG = "LOG"
EVENT_RISK_ALERT = "RISK_ALERT"
EVENT_TIMER = "TIMER"


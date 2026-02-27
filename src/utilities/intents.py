"""
High-level intent types used to represent commands or desired actions.

Intents are complementary to events:
- Events describe *what happened*.
- Intents describe *what the system or a strategy wants to do next*.
"""

# Trading intents
INTENT_PLACE_ORDER = "PLACE_ORDER"
INTENT_CANCEL_ORDER = "CANCEL_ORDER"

# Logging intent
INTENT_LOG = "LOG_INTENT"

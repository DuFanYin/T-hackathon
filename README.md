# T-hackathon

## Crypto trading system (skeleton)

This repo is a **deterministic, event-driven** crypto trading skeleton inspired by OTrader-style engines, but simplified:

- **REST-only vendor**: market data + orders are HTTP calls (no connection state, no websockets assumed)
- **Central routing**: `EventEngine` owns the routing + call order
- **Clean responsibilities**: `Gateway` does vendor I/O + symbol cache; strategy/position/risk consume events

---

## Code layout

```text
src/
├── engines/
│   ├── engine_main.py      # MainEngine (composition root / façade)
│   ├── engine_event.py     # EventEngine + Event (queue + deterministic routing)
│   ├── engine_gateway.py   # GatewayEngine (REST ticks + orders, SymbolData cache)
│   ├── engine_strategy.py  # StrategyEngine (signals + intents)
│   ├── engine_position.py  # PositionEngine (positions from trades)
│   └── engine_risk.py      # RiskEngine (risk checks + alerts)
└── utilities/
    ├── events.py           # EVENT_TICK, EVENT_ORDER, EVENT_TRADE, EVENT_LOG, EVENT_RISK_ALERT, EVENT_TIMER
    ├── intents.py          # INTENT_PLACE_ORDER, INTENT_CANCEL_ORDER, INTENT_LOG
    └── object.py           # SymbolData, TickData, OrderRequest, CancelOrderRequest, OrderData, TradeData, LogData, ...
```

---

## Engines (separation of responsibility)

- **`MainEngine`**
  - Creates all engines and starts the event loop.
  - Façade methods:
    - `put_event(event_type, data)` → enqueue an event
    - `handle_intent(intent_type, payload)` → delegate to `EventEngine`
    - `send_order(...)` / `cancel_order(...)` → delegate to `GatewayEngine`

- **`EventEngine`**
  - Owns: event queue worker + timer thread.
  - Owns: **routing + deterministic call order** (no plug-in registration).

- **`GatewayEngine`** (vendor adapter)
  - **Only** place that talks to the vendor (HTTP).
  - Maintains `SymbolData` cache updated from ticks:
    - `on_tick(Event[TickData])` → updates `SymbolData`
    - `get_symbol(symbol)` → used by Strategy/Risk/Position
  - Order endpoints:
    - `send_order(OrderRequest) -> order_id | None`
    - `cancel_order(CancelOrderRequest)`

- **`StrategyEngine`**
  - Consumes: `on_tick`, `on_order`, `on_trade`, `on_timer`.
  - Reads market state via `GatewayEngine.get_symbol(...)`.
  - Acts via intents (place/cancel/log).

- **`PositionEngine`**
  - Consumes: `on_order`, `on_trade`.
  - Tracks positions/PnL in memory from `TradeData`.

- **`RiskEngine`**
  - Consumes: `on_tick`, `on_order`, `on_trade`, `on_timer`.
  - Emits risk warnings via `EVENT_RISK_ALERT` (currently printed by `EventEngine`).

---

## Routing (current deterministic pipelines)

`EventEngine` routes in this fixed order:

- `EVENT_TICK`  → `Gateway.on_tick` → `Strategy.on_tick` → `Risk.on_tick`
- `EVENT_ORDER` → `Position.on_order` → `Strategy.on_order` → `Risk.on_order`
- `EVENT_TRADE` → `Position.on_trade` → `Strategy.on_trade` → `Risk.on_trade`
- `EVENT_TIMER` → `Strategy.on_timer()` → `Risk.on_timer()`
- `EVENT_LOG` / `EVENT_RISK_ALERT` → printed to stdout

Intents:

- `INTENT_PLACE_ORDER` → `MainEngine.send_order(OrderRequest)`
- `INTENT_CANCEL_ORDER` → `MainEngine.cancel_order(CancelOrderRequest)`
- `INTENT_LOG` → `MainEngine.put_event(EVENT_LOG, LogData|str)`

---

## How to use

1. Create: `main = MainEngine()`
2. Feed vendor outputs as events: `main.put_event(EVENT_TICK, TickData(...))`
3. Strategies place orders via intents: `main.handle_intent(INTENT_PLACE_ORDER, OrderRequest(...))`


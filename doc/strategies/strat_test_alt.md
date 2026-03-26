## `StratTestAlt`

Integration / plumbing test strategy (`StratTestAlt` in `src/strategies/factory/strat_test_alt.py`). Trades **only `BTCUSDT`**, **MARKET** orders only.

### Behavior

1. On a new cycle: **BUY MARKET** with configured `quantity` (default `0.01`).
2. Wait **`close_delay_sec`** wall-clock seconds (default **5**).
3. **SELL MARKET** to close (quantity capped by position size).
4. Wait **`cycle_interval_sec`** after the close before the next cycle (default **4 hours**). First cycle can open as soon as the strategy timer runs and conditions allow.

Skips ticks while **pending orders** exist for the symbol (same pattern as other strategies).

### Timer

- `timer_trigger` defaults to **1** (engine tick is typically 1s) so the 5s close can fire reliably.

### Settings (`setting` dict)

| Key | Default | Notes |
|-----|---------|--------|
| `quantity` | `0.01` | Base asset qty |
| `cycle_interval_sec` | `14400` (4h) | Time after **close** before next open |
| `close_delay_sec` | `5` | Delay between open and close |
| `timer_trigger` | `1` | Engine ticks between `on_timer_logic` calls |

### Registry

- Registered as **`StratTestAlt`** in `AVAILABLE_STRATEGIES` (`src/engines/engine_strategy.py`).

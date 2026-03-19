## `strategy_JH`

Support-bounce strategy ported from `pine/strategy.pine`.

### Trading logic (tree)

```text
TIMER TICK
└─ For each symbol in symbols
   ├─ Have enough 15m bars? (need >= max(4, 2*pivot_len+1, atr_len+1))
   │  ├─ no → do nothing
   │  └─ yes
   ├─ In position with active_stop/active_target?
   │  ├─ yes
   │  │  ├─ last_price <= active_stop → SELL (MARKET), clear stop/target
   │  │  ├─ last_price >= active_target → SELL (MARKET), clear stop/target
   │  │  └─ else → continue
   │  └─ no/flat → continue
   ├─ Pending order exists while flat?
   │  ├─ yes AND (bar_count - limit_bar_idx >= fill_bars + 1) → cancel pending
   │  └─ no → continue
   ├─ Pivot low update?
   │  ├─ get_pivot_low(...) returns value → set sup_price, reset hit_count/hit1_low
   │  └─ else → keep prior support state
   ├─ If L <= sup_price → hit_count++ (if first hit: hit1_low = L)
   ├─ Compute filters:
   │  ├─ prev3_bearish_strict == True
   │  ├─ close_top_third == True
   │  ├─ close_above_support == True
   │  ├─ close_not_above_prev_open == True
   │  └─ ATR/risk filter passes
   ├─ Signal?
   │  ├─ hit_count==1 AND all filters → signal
   │  ├─ hit_count==2 AND all filters AND NOT (L > hit1_low) → signal
   │  └─ hit_count==2 AND (L > hit1_low) → reset support state
   └─ If signal AND flat:
      ├─ cancel any pending orders
      ├─ BUY (LIMIT @ rounded entry price)
      └─ set active_stop and active_target (rr-based)
```

### Trading logic (exact decision rules)

Runs on **15m bars** (`interval="15m"`). For each symbol in `symbols` (default 8-pair universe in `PAIRS_CONFIG`):

1. **Data requirement**
   - Fetch last `need = max(4, 2*pivot_len+1, atr_len+1)` 15m bars; if fewer, do nothing.

2. **Position state**
   - `flat` if current holding quantity is 0.
   - Strategy keeps per-symbol state:
     - `sup_price` (support level)
     - `hit_count` (support touches since last pivot update)
     - `hit1_low` (low on first touch)
     - `active_stop`, `active_target`
     - `limit_bar_idx` (bar index when limit order was placed, used for timeout)

3. **Exit checks (only if in position and stop/target set)**
   - If `last_price <= active_stop`: **SELL** (MARKET), clear stop/target.
   - Else if `last_price >= active_target`: **SELL** (MARKET), clear stop/target.

4. **Limit-order timeout**
   - If `flat` and there is a pending order for the symbol:
     - If `bar_count - limit_bar_idx >= fill_bars + 1`: cancel the pending order.

5. **Update support via pivot low**
   - Query `pivot_low = get_pivot_low(symbol, pivot_len, pivot_len, interval="15m")`.
   - If a pivot low exists:
     - set `sup_price = pivot_low`
     - reset `hit_count = 0`, `hit1_low = None`

6. **Compute entry conditions on the most recent bar**
   - Let last bar be \(O,H,L,C\), prev bar open \(prev\_open\).
   - Bar-shape filters:
     - `close_top_third`: \(C \ge L + (H-L)\times 2/3\)
     - `close_above_support`: `sup_price` exists and \(C > sup\_price\)
     - `close_not_above_prev_open`: \(C \le prev\_open\)
   - Entry/stop geometry:
     - `entry_price = (H + L) / 2`
     - `stop_price = L - mintick` (per-pair mintick from `PAIRS_CONFIG`)
     - `risk = entry_price - stop_price`
     - ATR filter: reject if `risk >= ATR(atr_len, interval="15m")`
   - Support-hit counting:
     - If `sup_price` exists and \(L \le sup\_price\), increment `hit_count`.
     - On first hit set `hit1_low = L`.
   - Pattern filter:
     - Require `prev3_bearish_strict(symbol)` to be true.

7. **Signal rule**
   - Signal is true if:
     - (`hit_count == 1` OR `hit_count == 2`) AND
     - strict bearish AND bar-shape filters pass AND ATR/risk filter passes AND
     - for `hit_count == 2`: reject “higher-low fail” where \(L > hit1\_low\)
   - If `hit_count == 2` and the higher-low fail triggers, reset support state.

8. **Entry action (only if `signal` and `flat`)**
   - Compute target:
     - `target_price = entry_price + rr * risk` (rounded to mintick)
   - Position sizing:
     - `alloc_per_pair = capital / N_pairs`
     - `risk_amount = alloc_per_pair * risk_pct`
     - `qty = min(risk_amount / (entry_price - stop_price), alloc_per_pair / entry_price)`
     - quantity rounded to `SymbolData.amount_precision` if available (else 6dp)
   - Cancel any existing pending orders for the symbol.
   - Place **BUY LIMIT** at rounded entry price.
   - Set `active_stop = stop_price`, `active_target = target_price`.

### What it does

- **Universe**: fixed 8-pair universe by default (override with `pairs` setting).
- **Setup**:
  - Tracks a pivot-low derived **support price** (`pivot_len`)
  - Counts support “hits” (H1/H2) and requires a strict bearish setup before entry (`prev3_bearish_strict`)
  - Applies additional bar-shape filters (close in top third, close above support, etc.)
- **Entry**:
  - Buys with **LIMIT** at the mid of the 15m bar range (rounded to mintick)
  - Cancels stale limit orders after `fill_bars+1` bars
- **Exit**:
  - Stop and target are set immediately based on risk (`rr`) and `mintick`
  - Exits are sent as MARKET sells when stop/target is hit

### Key parameters (defaults)

- **`pairs`**: default `["APTUSDT","CRVUSDT","EIGENUSDT","TAOUSDT","UNIUSDT","TRUMPUSDT","BONKUSDT","SHIBUSDT"]`
- **`interval`**: `"15m"`
- **`pivot_len`**: `5`
- **`rr`**: `2.0`
- **`fill_bars`**: `1`
- **`atr_len`**: `14`
- **`capital`**: `150000.0`
- **`risk_pct`**: `0.01`

### Lifecycle / integration

- **Registry name**: `strategy_JH` (see `src/engines/engine_strategy.py:AVAILABLE_STRATEGIES`)
- **Timer behavior**: runs every timer tick and evaluates each configured symbol.
- **Dependencies**: relies on `MarketEngine` indicator helpers:
  - `get_last_bars()`, `get_atr()`, `get_pivot_low()`, `prev3_bearish_strict()`


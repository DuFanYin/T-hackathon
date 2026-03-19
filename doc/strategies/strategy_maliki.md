## `strategy_maliki`

Multi-asset **momentum rotation with a BTC regime filter**.

### Trading logic (tree)

```text
TIMER TICK
├─ Warmup ok? (BTC bars >= regime_ma_candles)
│  ├─ no → do nothing
│  └─ yes
├─ Trailing stop check (each held coin)
│  ├─ ticks_held < min_hold_candles → skip stop
│  └─ else dd >= trailing_stop_pct → SELL (MARKET)
└─ Rebalance tick? (tick_count % rebalance_every == 0)
   ├─ no → done
   └─ yes
      ├─ Regime bullish? (BTC_last > BTC_MA(regime_ma_candles))
      │  ├─ no (BEAR)
      │  │  └─ for each held coin:
      │  │     ├─ ticks_held >= min_hold_candles → SELL (MARKET)
      │  │     └─ else → keep holding
      │  └─ yes (BULL)
      │     ├─ Build rankings over TRACKED_COINS
      │     │  ├─ notional_24h (Σ volume*close over 288 bars) < min_notional_24h → skip coin
      │     │  ├─ momentum < min_momentum_pct → skip coin
      │     │  └─ else → candidate
      │     ├─ Any candidates?
      │     │  ├─ no → (cash mode)
      │     │  │  └─ for each held coin:
      │     │  │     ├─ ticks_held >= min_hold_candles → SELL (MARKET)
      │     │  │     └─ else → keep holding
      │     │  └─ yes
      │     │     ├─ target_coins = top_n by momentum
      │     │     ├─ Rotation exits:
      │     │     │  └─ held coin ∉ target_coins AND ticks_held >= min_hold → SELL (MARKET)
      │     │     └─ Entries:
      │     │        └─ coin ∈ target_coins AND not held → BUY (LIMIT @ price*1.001)
      │     │           (size from cached USD balance; fallback capital_allocation)
```

### Trading logic (exact decision rules)

Runs on **5m bars**. Every timer tick:

1. **Warmup check**
   - Require BTC to have at least `regime_ma_candles` bars available.
   - If not, do nothing.

2. **Trailing-stop check (runs every tick)**
   - For each held coin:
     - Update `peak_price = max(peak_price, last_price)`.
     - If `ticks_held < min_hold_candles`: skip stop checks.
     - Else compute drawdown: \(dd = (peak\_price - last\_price)/peak\_price \times 100\).
     - If `dd >= trailing_stop_pct`: **SELL** that coin (MARKET).

3. **Rebalance step (only when `tick_count % rebalance_every == 0`)**
   - **Regime filter**:
     - Compute BTC MA over last `regime_ma_candles`.
     - If `BTC_last <= BTC_MA`:
       - For each held coin: if `ticks_held >= min_hold_candles`, **SELL** (MARKET).
       - Return (stay in cash).
   - **Momentum ranking**:
     - For each coin in `TRACKED_COINS`, fetch `lookback_candles` bars.
     - **Liquidity filter (24h notional)**:
       - Compute `notional_24h = sum(volume * close)` over last 288 bars (approx 24h).
       - Skip coin if `notional_24h < min_notional_24h`.
     - Compute momentum: \(m = (close_{last} - close_{first}) / close_{first} \times 100\).
     - Filter: keep only if `m >= min_momentum_pct`.
     - Sort descending by `m`.
     - If no coin passes filter: **do not open new positions** (stay in cash).
   - **Target set**:
     - `target_coins = top_n` coins from the sorted list.
   - **Exits (rotation)**:
     - For each held coin not in `target_coins`:
       - If `ticks_held >= min_hold_candles`: **SELL** (MARKET).
   - **Entries**
     - For each coin in `target_coins` not currently held:
       - Compute allocation base:
         - Prefer cached `USD` wallet balance from `GatewayEngine.get_balance()` (no exchange call).
         - Fallback: configured `capital_allocation`.
       - Compute allocation:
         - `alloc_raw = portfolio_value / top_n`
         - `alloc_cap = portfolio_value * (max_single_alloc_pct/100)`
         - `alloc = min(alloc_raw, alloc_cap)`
       - `qty = round(alloc / price, 5)`, skip if `qty <= 0` or `alloc < $10`.
       - Place **BUY LIMIT** at `limit_price = price * 1.001`.

### What it does

- **Universe**: hard-coded list of liquid coins (`TRACKED_COINS`), traded as `COINUSDT` internally (Gateway converts to `COIN/USD` on Roostoo).
- **Regime filter**: if **BTC is below its moving average**, the strategy exits to cash (subject to min-hold).
- **Ranking**: in bullish regime, ranks coins by **percent return over `lookback_candles`**.
- **Portfolio construction**: holds the **top `top_n`** coins that exceed `min_momentum_pct`.
- **Execution**: enters with a **LIMIT** slightly above last price; exits with **MARKET**.
- **Risk control**: uses a **trailing stop** (`trailing_stop_pct`) after the **minimum hold** (`min_hold_candles`) has elapsed.

### Key parameters (defaults)

- **`lookback_candles`**: `96` (8h on 5m bars)
- **`top_n`**: `2`
- **`rebalance_every`**: `48` (4h, since the strategy ticks each timer event)
- **`trailing_stop_pct`**: `3.0`
- **`min_hold_candles`**: `24` (2h)
- **`regime_ma_candles`**: `576` (48h BTC MA)
- **`min_momentum_pct`**: `0.5`
- **`min_notional_24h`**: `1_000_000` (approx quote notional over last 24h; computed as \(\sum volume \times close\))
- **`capital_allocation`**: `850_000`
- **`max_single_alloc_pct`**: `100.0`
- **`order_symbol_format`**: `"gateway"` (recommended) or `"slash"`

### Lifecycle / integration

- **Registry name**: `strategy_maliki` (see `src/engines/engine_strategy.py:AVAILABLE_STRATEGIES`)
- **Timer behavior**:
  - Runs every timer tick (`timer_trigger=1`)
  - Rebalances when `tick_count % rebalance_every == 0`
- **Data requirements**: requests history via `history_requirements()` so `MarketEngine` can backfill the needed bars.
- **Reconciliation logs**: emits periodic reconciliation logs comparing internal `_positions` vs engine holdings and pending orders.


## `strategy_maliki`

Multi-asset **momentum rotation** with a **BTC regime filter** (`StrategyMaliki` in `src/strategies/factory/strategy_maliki.py`). Universe: uses all internal symbols cached in `MarketEngine` at startup (override with `setting["pairs"]`).

### Trading logic (tree)

```text
STRATEGY STEP (timer_trigger=300: ~5m per step if EventEngine interval=1s)
├─ Warmup ok? BTC get_bar_count(BTCUSDT, 5m) >= regime_ma_candles
│  ├─ no → every 10 ticks log "Warming up...", return
│  └─ yes
├─ _get_current_prices(): last_price per `self.symbols` from MarketEngine.get_symbol
├─ if no prices → return
│
├─ TRAILING — _check_trailing_stops (each strategy step)
│  └─ for each held coin (from StrategyEngine holdings):
│     ├─ update peak_price = max(peak, last)
│     ├─ ticks_held = tick_count - entry_tick < min_hold_candles → skip
│     └─ else drawdown from peak >= trailing_stop_pct → SELL MARKET (_close_position)
│
└─ REBALANCE? tick_count % rebalance_every == 0
   ├─ yes → _rebalance
   │  ├─ Regime: BTC_last > MA(regime_ma_candles on BTCUSDT 5m closes)?
   │  │  ├─ NO (bearish)
   │  │  │  └─ for each held coin:
   │  │  │     ├─ ticks_held >= min_hold_candles → SELL MARKET (regime_bearish)
   │  │  │     └─ else → keep
   │  │  └─ YES (bullish)
   │  │     ├─ _get_momentum_rankings over `self.symbols`
   │  │     │  ├─ for each coin: need lookback_candles bars on 5m
   │  │     │  ├─ skip: notional_24h = sum(vol*close) over 288 bars < min_notional_24h
   │  │     │  ├─ momentum_pct = (last_close - first_close)/first_close*100
   │  │     │  ├─ skip: momentum_pct < min_momentum_pct
   │  │     │  └─ sort descending by momentum_pct
   │  │     │
   │  │     ├─ no candidates after filters?
   │  │     │  └─ for each held (min_hold met) → SELL (no_qualifiers); return
   │  │     │
   │  │     ├─ target_coins = top top_n from rankings
   │  │     ├─ ROTATION EXIT: held coin ∉ target_coins and min_hold met → SELL (rotation)
   │  │     └─ ENTRY: for each rank in top top_n
   │  │        ├─ coin already held OR pending on COINUSDT → skip
   │  │        ├─ slots_open = top_n - len(held) <= 0 → stop entries
   │  │        └─ else _open_position LIMIT
   │  │           ├─ portfolio: get_balance() cached Wallet USD (Free+Lock), else capital_allocation
   │  │           ├─ alloc = min(portfolio/top_n, portfolio * max_single_alloc_pct/100)
   │  │           ├─ qty = round(alloc/price, 5); skip if qty<=0 or alloc<$10
   │  │           └─ limit_price = round(price * 1.001, 8)
   │  │
   │  └─ _log_reconciliation: _risk_state vs engine positions vs get_pending_orders
   │
   └─ no → done for this tick
```

### Trading logic (exact decision rules)

- **Interval**: **`5m`** for regime, momentum, notional window (288 bars ≈ 24h), and history backfill.
- **`get_balance()`**: returns **gateway cached** balance (no extra HTTP per call in normal path).
- **`slots_open`**: passed into `_open_position` from `_rebalance` but **not used** in sizing (alloc uses `top_n` only).

### What it does

- **Regime**: if **BTC** is **below** its **MA** over `regime_ma_candles`, exit to cash (subject to min hold).
- **Ranking**: in bull regime, rank by **% return** over `lookback_candles`; filter by **24h notional** and **min_momentum_pct**.
- **Portfolio**: hold up to **`top_n`** names; rotate when leaders change (min hold).
- **Risk**: **trailing stop** after **min_hold_candles**; entries **LIMIT** ~0.1% above last; exits **MARKET**.
- **State**: **`_risk_state`** holds trail/entry metadata; **fills** are source-of-truth in **StrategyEngine** holdings.

### Key parameters (defaults)

| Key | Default | Notes |
|-----|---------|--------|
| `timer_trigger` | `300` | ~5m between `on_timer_logic` runs at EventEngine 1s/tick. |
| `interval` | `"5m"` | |
| `lookback_candles` | `576` | 48h on 5m. |
| `top_n` | `1` | |
| `rebalance_every` | `288` | Steps between rebalances (~24h at 288×5m). |
| `trailing_stop_pct` | `8.0` | |
| `min_hold_candles` | `288` | |
| `regime_ma_candles` | `576` | |
| `min_momentum_pct` | `3.0` | |
| `min_notional_24h` | `1_000_000` | On 288-bar window. |
| `capital_allocation` | `20_000` | Fallback if cached USD total is 0. |
| `max_single_alloc_pct` | `100.0` | |

### Lifecycle / integration

- **Registry**: `strategy_maliki` in `AVAILABLE_STRATEGIES`.
- **History**: `history_requirements()` — BTC `regime_ma_candles` + each `self.symbols` symbol `lookback_candles` at `5m`.
- **Stop**: `on_stop_logic` → `clear_all_positions()`.

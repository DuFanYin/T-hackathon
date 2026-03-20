## `strategy_JH`

Support-bounce strategy on **15m** bars (`StrategyJH` in `src/strategies/factory/strategy_JH.py`). Default universe: keys of `PAIRS_CONFIG` (8 pairs), overridable with `setting["pairs"]`.

### Trading logic (tree)

```text
TIMER TICK (every timer_trigger engine ticks; default 300)
└─ For each symbol in self.symbols
   ├─ EXITS — _check_exit (only if active_stop & active_target set)
   │  ├─ position qty <= 0?
   │  │  ├─ yes + no pending BUY for symbol → clear active_stop / active_target
   │  │  └─ yes + pending BUY → keep staged exits
   │  ├─ last_price <= 0 → return
   │  ├─ last_price <= active_stop → SELL (MARKET) full qty, clear stop/target
   │  └─ last_price >= active_target → SELL (MARKET) full qty, clear stop/target
   │
   ├─ LIMIT TIMEOUT — _check_limit_timeout (interval = self.interval, default 15m)
   │  ├─ no pending orders for symbol → return
   │  ├─ already in position (qty > 0) → return
   │  └─ get_bar_count(sym, interval) - limit_bar_idx >= fill_bars + 1
   │     → cancel first pending order (INTENT_CANCEL_ORDER)
   │
   └─ SIGNAL — _process_signal
      ├─ Have enough bars? need = max(4, 2*pivot_len+1, atr_len+1) on interval
      │  ├─ no → return
      │  └─ yes → cur = last bar, prev = prior bar
      ├─ flat? position_qty == 0
      ├─ Pivot low update
      │  ├─ get_pivot_low(sym, pivot_len, pivot_len, interval) returns value
      │  │  → set sup_price, reset hit_count=0, hit1_low=None
      │  └─ else → need existing sup_price
      ├─ Gate: sup_price set AND cur.low <= sup_price AND flat
      │  └─ else → return (after pivot branch)
      ├─ hit_count++ ; if first hit → hit1_low = cur.low
      ├─ Filters (all on same bar):
      │  ├─ prev3_bearish_strict(sym, interval)
      │  ├─ close_top_third: rng=H-L>0 and close >= L + rng*(2/3)
      │  ├─ close > sup_price
      │  ├─ close <= prev.open
      │  └─ ATR: entry=(H+L)/2, stop=L-mintick, risk=entry-stop, ATR>0 and risk < ATR
      ├─ Signal?
      │  ├─ hit_count==1 and all filters → signal
      │  ├─ hit_count==2 and all filters and NOT (cur.low > hit1_low) → signal
      │  └─ hit_count==2 and higher-low fail → reset sup_price/hit_count/hit1_low, return
      └─ If signal and flat:
         ├─ cancel any pending orders for symbol
         ├─ size qty (alloc_per_pair, risk_pct, cap; round qty per SymbolData.amount_precision or 6dp)
         ├─ round entry/stop/target prices to PAIRS_CONFIG mintick
         ├─ BUY LIMIT @ rounded entry
         ├─ limit_bar_idx = get_bar_count(sym, interval)
         └─ pending_stop / pending_target = rounded stop & target (→ active_* when BUY FILLS)

on_order (BUY FILLED): copy pending_stop/target → active_stop/active_target; clear pending_*
on_order (BUY CANCELED/REJECTED/…): clear pending_stop/target
```

### Trading logic (exact decision rules)

Same as the tree; numeric defaults: `pivot_len=5`, `rr=2.0`, `atr_len=14`, `fill_bars=1`, `capital=20000`, `risk_pct=0.01`.  
`open_position` → `StrategyTemplate.send_order`, which may snap qty/price to cached `TradingPair` / `SymbolData` exchange precisions.

### What it does

- **Universe**: default 8 pairs in `PAIRS_CONFIG` (override with `pairs` list in `setting`).
- **Setup**: pivot-low **support** (`sup_price`), **H1/H2** support touches, strict bearish pattern (`prev3_bearish_strict`), bar-shape filters, **risk < ATR**.
- **Entry**: **LIMIT** at mid-bar entry, rounded to pair **mintick**; stale limit canceled after **`fill_bars + 1`** bars without fill (when flat + pending).
- **Exit**: **MARKET** when **stop** or **target** (`rr` × risk) hit vs `last_price`; stop/target armed after entry **fill** from `pending_*`.

### Key parameters (defaults)

| Key | Default | Notes |
|-----|---------|--------|
| `timer_trigger` | `300` | Ticks between `on_timer_logic`. |
| `interval` | `"15m"` | Bar interval for signals, ATR, pivot, timeout. |
| `pairs` | (use `PAIRS_CONFIG`) | If list provided, replaces default symbols. |
| `pivot_len` | `5` | |
| `rr` | `2.0` | Target distance vs risk segment. |
| `fill_bars` | `1` | Limit timeout: `bars_since_limit >= fill_bars + 1`. |
| `atr_len` | `14` | |
| `capital` | `20000.0` | Split → `_alloc_per_pair = capital / N_symbols`. |
| `risk_pct` | `0.01` | `risk_amount = _alloc_per_pair * risk_pct` for sizing. |

**`PAIRS_CONFIG` minticks**: APTUSDT `0.01`, CRVUSDT `0.0001`, EIGENUSDT `0.001`, TAOUSDT `0.01`, UNIUSDT `0.001`, TRUMPUSDT `0.01`, BONKUSDT `1e-8`, SHIBUSDT `1e-8`.

### Lifecycle / integration

- **Registry**: `strategy_JH` (`AVAILABLE_STRATEGIES` in `src/engines/engine_strategy.py`).
- **History**: `history_requirements()` → `need` bars per symbol at `interval.binance`.
- **MarketEngine**: `get_last_bars`, `get_bar_count`, `get_atr`, `get_pivot_low`, `prev3_bearish_strict`, `get_symbol`.

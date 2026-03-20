"""
strategy_JH: Support Bounce Scalper — 15m Multi-Pair Deployment

Aligned to the provided reference bot:
- Uses 15m bars directly from MarketEngine (no internal resampling).
- Runs signal logic on 15m closes.
- Monitors stop/target exits on every timer tick.
- Trades a fixed 8-pair universe by default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.strategies.template import StrategyTemplate
from src.utilities.intents import INTENT_CANCEL_ORDER
from src.utilities.object import CancelOrderRequest

if TYPE_CHECKING:
    from src.engines.engine_main import MainEngine


# Internal symbol universe (GatewayEngine expects BTCUSDT-style symbols).
PAIRS_CONFIG: dict[str, dict[str, Any]] = {
    "APTUSDT": {"mintick": 0.01},
    "CRVUSDT": {"mintick": 0.0001},
    "EIGENUSDT": {"mintick": 0.001},
    "TAOUSDT": {"mintick": 0.01},
    "UNIUSDT": {"mintick": 0.001},
    "TRUMPUSDT": {"mintick": 0.01},
    "BONKUSDT": {"mintick": 1e-8},
    "SHIBUSDT": {"mintick": 1e-8},
}


def _round_price(value: float, mintick: float) -> float:
    if mintick <= 0:
        return value
    return round(value / mintick) * mintick


def _round_qty(value: float, decimals: int = 6) -> float:
    if decimals < 0:
        return value
    factor = 10.0**decimals
    return int(value * factor) / factor


class StrategyJH(StrategyTemplate):
    """
    Multi-pair 15m support-bounce strategy.

    - Signal computed on internally resampled 15m bars.
    - Stop/target monitored on every 5m tick.
    """

    def __init__(
        self,
        main_engine: "MainEngine",
        strategy_name: str = "strategy_JH",
        setting: dict[str, Any] | None = None,
    ) -> None:
        s = dict(setting or {})
        s.setdefault("timer_trigger", 1)
        s.setdefault("interval", "15m")

        pairs_override = s.get("pairs")
        if isinstance(pairs_override, list) and pairs_override:
            symbols = [str(x).strip().upper() for x in pairs_override if str(x).strip()]
        else:
            symbols = list(PAIRS_CONFIG.keys())
        s["symbols"] = symbols

        super().__init__(main_engine, strategy_name, s)

        self.pivot_len: int = int(s.get("pivot_len", 5))
        self.rr: float = float(s.get("rr", 2.0))
        self.atr_len: int = int(s.get("atr_len", 14))
        self.fill_bars: int = int(s.get("fill_bars", 1))
        self.capital: float = float(s.get("capital", 150_000.0))
        self.risk_pct: float = float(s.get("risk_pct", 0.01))

        self._mintick: dict[str, float] = {sym: float(PAIRS_CONFIG.get(sym, {}).get("mintick", 0.01)) for sym in self.symbols}
        self._state: dict[str, dict[str, Any]] = {}
        self._alloc_per_pair: float = self.capital / max(1, len(self.symbols))

    def history_requirements(self) -> list[dict[str, object]]:
        ival = self.interval.binance
        # Need enough 15m bars for: pivot (2*pivot_len+1), ATR (atr_len+1), and prev3 pattern (4).
        need = max(4, 2 * int(self.pivot_len) + 1, int(self.atr_len) + 1)
        return [{"symbol": sym, "interval": ival, "bars": int(need)} for sym in self.symbols]

    def on_init_logic(self) -> None:
        for sym in self.symbols:
            self._state[sym] = {
                "sup_price": None,
                "hit_count": 0,
                "hit1_low": None,
                "limit_bar_idx": 0,
                "active_stop": None,
                "active_target": None,
                "pending_stop": None,
                "pending_target": None,
                "pending_order_id": "",
                "entry_price": 0.0,
            }
        self.write_log(
            f"Init: {len(self.symbols)} pairs, ${self._alloc_per_pair:,.0f}/pair, "
            f"interval={self.interval.binance} pivot={self.pivot_len} rr={self.rr} atr={self.atr_len} fill={self.fill_bars}",
            level="INFO",
        )

    def on_stop_logic(self) -> None:
        self.write_log("Stopping — clearing all positions", level="INFO")
        self.clear_all_positions()

    def on_timer_logic(self) -> None:
        market = getattr(self._main, "market_engine", None)
        if not market:
            return
        ival = self.interval.binance
        for sym in self.symbols:
            st = self._state.get(sym)
            if st is None:
                continue
            self._check_exit(sym, st)
            self._check_limit_timeout(sym, st, ival)
            self._process_signal(sym, st, ival)

    # ---------------- exits (5m) ----------------

    def _check_exit(self, sym: str, st: dict[str, Any]) -> None:
        if st.get("active_stop") is None or st.get("active_target") is None:
            return

        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(sym)
        qty = float(pos.quantity) if pos else 0.0

        if qty <= 0:
            # If a BUY entry is still pending, keep staged exits untouched.
            pending_ids = self.get_pending_orders().get(sym, [])
            if not pending_ids:
                st["active_stop"] = None
                st["active_target"] = None
            return

        sym_data = self.get_symbol(sym)
        last = float(getattr(sym_data, "last_price", 0.0) or 0.0) if sym_data else 0.0
        if last <= 0:
            return

        stop_price = float(st["active_stop"])
        target_price = float(st["active_target"])

        if last <= stop_price:
            self.close_position(sym, qty, order_type="MARKET")
            self.write_log(f"EXIT STOP {sym}: {last:.6f} <= {stop_price:.6f}", level="WARN")
            st["active_stop"] = None
            st["active_target"] = None
            return

        if last >= target_price:
            self.close_position(sym, qty, order_type="MARKET")
            self.write_log(f"EXIT TARGET {sym}: {last:.6f} >= {target_price:.6f}", level="INFO")
            st["active_stop"] = None
            st["active_target"] = None

    # ---------------- limit timeout (15m) ----------------

    def _check_limit_timeout(self, sym: str, st: dict[str, Any], interval: str) -> None:
        # Timeout is enforced against engine pending orders (per symbol).
        pending_map = self.get_pending_orders()
        pending_ids = pending_map.get(sym, [])
        if not pending_ids:
            return
        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(sym)
        if pos and float(pos.quantity or 0.0) > 0:
            return
        bar_count = int(getattr(self._main.market_engine, "get_bar_count")(sym, interval))
        limit_bar_idx = int(st.get("limit_bar_idx") or 0)
        if bar_count - limit_bar_idx >= self.fill_bars + 1:
            oid = pending_ids[0]
            self._main.handle_intent(INTENT_CANCEL_ORDER, CancelOrderRequest(order_id=oid, symbol=sym))
            self.write_log(f"TIMEOUT {sym}: cancel {oid} after {bar_count - limit_bar_idx} bars", level="WARN")

    # ---------------- signal (15m) ----------------

    def _process_signal(self, sym: str, st: dict[str, Any], interval: str) -> None:
        market = getattr(self._main, "market_engine", None)
        if market is None:
            return
        need = max(4, 2 * self.pivot_len + 1, self.atr_len + 1)
        bars = market.get_last_bars(sym, need, interval)
        if len(bars) < need:
            return
        cur = bars[-1]
        prev = bars[-2]

        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(sym)
        position_qty = float(pos.quantity) if pos else 0.0
        flat = position_qty == 0.0

        pl = market.get_pivot_low(sym, self.pivot_len, self.pivot_len, interval)
        if pl is not None:
            st["sup_price"] = float(pl)
            st["hit_count"] = 0
            st["hit1_low"] = None

        if st.get("sup_price") is None:
            return

        sup_price = float(st["sup_price"])
        hit_support = cur.low <= sup_price
        if not (hit_support and flat):
            return

        st["hit_count"] = int(st.get("hit_count") or 0) + 1
        if int(st["hit_count"]) == 1:
            st["hit1_low"] = cur.low

        ok_bear = market.prev3_bearish_strict(sym, interval)

        rng = cur.high - cur.low
        ok_t3 = rng > 0 and cur.close >= cur.low + rng * (2.0 / 3.0)
        ok_cs = cur.close > sup_price
        ok_po = cur.close <= prev.open

        entry_price = (cur.high + cur.low) / 2.0
        mintick = float(self._mintick.get(sym, 0.01))
        stop_price = cur.low - mintick
        risk = entry_price - stop_price

        atr = float(market.get_atr(sym, self.atr_len, interval))
        ok_atr = atr > 0 and risk < atr

        hit1_low = st.get("hit1_low")
        higher_low_fail = int(st["hit_count"]) == 2 and hit1_low is not None and cur.low > float(hit1_low)

        signal = False
        if int(st["hit_count"]) == 1:
            if ok_bear and ok_t3 and ok_cs and ok_po and ok_atr:
                signal = True
        elif int(st["hit_count"]) == 2:
            if ok_bear and ok_t3 and ok_cs and ok_po and ok_atr and not higher_low_fail:
                signal = True
            else:
                st["sup_price"] = None
                st["hit_count"] = 0
                st["hit1_low"] = None
                return

        if not signal:
            return

        target_price = entry_price + self.rr * risk

        risk_per_unit = entry_price - stop_price
        if risk_per_unit <= 0:
            return
        risk_amount = self._alloc_per_pair * self.risk_pct
        qty = risk_amount / risk_per_unit
        max_qty = self._alloc_per_pair / entry_price if entry_price > 0 else 0.0
        qty = min(qty, max_qty)

        # Precision: prefer SymbolData.amount_precision when available.
        amt_dec = 6
        sym_data = self.get_symbol(sym)
        ap = getattr(sym_data, "amount_precision", None) if sym_data else None
        if isinstance(ap, int) and 0 <= ap <= 12:
            amt_dec = ap
        qty = _round_qty(qty, amt_dec)
        if qty <= 0:
            return

        # Cancel any known pending order for this symbol (engine-side).
        pending_map = self.get_pending_orders()
        for oid in pending_map.get(sym, []):
            self._main.handle_intent(INTENT_CANCEL_ORDER, CancelOrderRequest(order_id=oid, symbol=sym))

        rounded_entry = _round_price(entry_price, mintick)
        rounded_stop = _round_price(stop_price, mintick)
        rounded_target = _round_price(target_price, mintick)

        oid = self.open_position(sym, qty, price=rounded_entry, order_type="LIMIT")
        st["limit_bar_idx"] = int(market.get_bar_count(sym, interval))
        st["pending_order_id"] = str(oid or "")
        st["pending_stop"] = rounded_stop
        st["pending_target"] = rounded_target
        st["entry_price"] = rounded_entry

        ht = "H1" if int(st["hit_count"]) == 1 else "H2"
        self.write_log(
            f"SIGNAL {ht} {sym}: entry={rounded_entry:.6f} stop={rounded_stop:.6f} "
            f"target={rounded_target:.6f} qty={qty:.6f} risk=${risk_amount:.2f}",
            level="INFO",
        )

    def on_order(self, event: Any) -> None:
        super().on_order(event)
        data = getattr(event, "data", event)
        symbol = str(getattr(data, "symbol", "") or "")
        side = str(getattr(data, "side", "") or "").upper()
        status = str(getattr(data, "status", "") or "").upper()
        filled_qty = float(getattr(data, "filled_quantity", 0.0) or 0.0)
        filled_avg = float(getattr(data, "filled_avg_price", 0.0) or 0.0)

        st = self._state.get(symbol)
        if not st:
            return

        if side == "BUY":
            if status == "FILLED" and filled_qty > 0:
                if st.get("pending_stop") is not None and st.get("pending_target") is not None:
                    st["active_stop"] = st["pending_stop"]
                    st["active_target"] = st["pending_target"]
                if filled_avg > 0:
                    st["entry_price"] = filled_avg
                st["pending_stop"] = None
                st["pending_target"] = None
                st["pending_order_id"] = ""
            elif status in {"CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}:
                st["pending_stop"] = None
                st["pending_target"] = None
                st["pending_order_id"] = ""
            return

        if side == "SELL" and status == "FILLED":
            st["active_stop"] = None
            st["active_target"] = None
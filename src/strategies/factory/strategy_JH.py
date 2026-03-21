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


class StrategyJH(StrategyTemplate):
    """
    Multi-pair 15m support-bounce strategy.

    - Signal computed on 15m bars provided by `MarketEngine` (no extra resampling here).
    - Stop/target monitored on every `on_timer_logic()` run (default is ~5m if `EventEngine` is 1s/tick).
    """

    def __init__(
        self,
        main_engine: "MainEngine",
        strategy_name: str = "strategy_JH",
        setting: dict[str, Any] | None = None,
    ) -> None:
        s = dict(setting or {})
        s.setdefault("timer_trigger", 300)
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
        self.capital: float = float(s.get("capital", 20_000.0))
        self.risk_pct: float = float(s.get("risk_pct", 0.01))

        self._mintick: dict[str, float] = {sym: float(PAIRS_CONFIG.get(sym, {}).get("mintick", 0.01)) for sym in self.symbols}
        self._state: dict[str, dict[str, Any]] = {}
        self._alloc_per_pair: float = self.capital / max(1, len(self.symbols))

        self.write_log(
            f"[strategy_JH] CONSTRUCT | pairs={len(self.symbols)} interval={self.interval.binance} "
            f"timer_trigger={self._timer_trigger} pivot_len={self.pivot_len} atr_len={self.atr_len} "
            f"rr={self.rr} fill_bars={self.fill_bars} capital=${self.capital:,.0f} risk_pct={self.risk_pct} "
            f"alloc/pair=${self._alloc_per_pair:,.0f}",
            level="INFO",
        )

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
        ival = self.interval.binance
        need = max(4, 2 * int(self.pivot_len) + 1, int(self.atr_len) + 1)
        me = getattr(self._main, "market_engine", None)
        bar_samples: list[str] = []
        if me:
            for sym in self.symbols[:5]:
                n = me.get_bar_count(sym, ival)
                bar_samples.append(f"{sym}:{n}")
            if len(self.symbols) > 5:
                bar_samples.append(f"…+{len(self.symbols) - 5} more")
        self.write_log(
            f"[strategy_JH] INIT | reset per-symbol state ×{len(self.symbols)} | min_bars_needed={need} | "
            f"bar_counts[{ival}]={', '.join(bar_samples) if bar_samples else 'n/a'}",
            level="INFO",
        )

    def on_start_logic(self) -> None:
        self.write_log(
            f"[strategy_JH] START | timer fires every {self._timer_trigger} engine tick(s) "
            f"→ on_timer_logic ~each {self._timer_trigger}s (default 1s/tick) | "
            f"symbols={len(self.symbols)} interval={self.interval.binance}",
            level="INFO",
        )

    def on_stop_logic(self) -> None:
        self.write_log("Stopping — clearing all positions", level="INFO")
        self.clear_all_positions()

    def _position_reconciliation(self) -> dict[str, Any]:
        """
        Compare per-symbol state vs holdings + pending orders.

        - active_exits_but_flat_no_pending: active_stop/target but qty=0 and no pending (inconsistent).
        - holding_without_active_exits: qty>0 but no active or pending exit plan.
        - pending_plan_but_flat_no_order: pending_stop/target in memory but flat and no engine pending.
        """
        issues: list[dict[str, Any]] = []
        notes: list[dict[str, Any]] = []
        se = getattr(self._main, "strategy_engine", None)
        if se is None:
            return {"ok": True, "issues": [], "notes": [], "skipped": "no strategy_engine"}

        holding = se.get_holding(self.strategy_name)
        pending_map = self.get_pending_orders()

        for sym in self.symbols:
            st = self._state.get(sym) or {}
            qty = 0.0
            if holding is not None:
                pos = holding.positions.get(sym)
                if pos is not None:
                    qty = float(getattr(pos, "quantity", 0.0) or 0.0)

            pend = list(pending_map.get(sym, []) or [])
            pending_oid = str(st.get("pending_order_id") or "").strip()
            has_engine_pending = bool(pend) or bool(pending_oid)

            a_stop = st.get("active_stop")
            a_tgt = st.get("active_target")
            p_stop = st.get("pending_stop")
            p_tgt = st.get("pending_target")

            if qty <= 0 and has_engine_pending:
                notes.append(
                    {
                        "type": "awaiting_fill_or_pending",
                        "symbol": sym,
                        "pending_order_ids": pend if pend else ([pending_oid] if pending_oid else []),
                        "detail": "No position qty but order activity on symbol",
                    }
                )

            if a_stop is not None and a_tgt is not None and qty <= 0 and not has_engine_pending:
                issues.append(
                    {
                        "type": "active_exits_but_flat_no_pending",
                        "symbol": sym,
                        "detail": "active_stop/target set but flat and no pending — state/holdings desync?",
                    }
                )

            if (
                qty <= 0
                and not has_engine_pending
                and p_stop is not None
                and p_tgt is not None
                and not pending_oid
            ):
                issues.append(
                    {
                        "type": "pending_plan_but_flat_no_order",
                        "symbol": sym,
                        "detail": "pending_stop/target in state but flat and no pending_order_id / engine pending",
                    }
                )

            if qty > 0 and (a_stop is None or a_tgt is None) and (p_stop is None or p_tgt is None):
                issues.append(
                    {
                        "type": "holding_without_exit_plan",
                        "symbol": sym,
                        "quantity": qty,
                        "detail": "Position qty>0 but no active or pending stop/target",
                    }
                )

        return {"ok": len(issues) == 0, "issues": issues, "notes": notes}

    def health_snapshot(self) -> dict[str, Any]:
        """Per-pair scanner state + live prices (no log parsing)."""
        h = super().health_snapshot()
        h["kind"] = "jh"
        ival = self.interval.binance
        se = getattr(self._main, "strategy_engine", None)
        holding = se.get_holding(self.strategy_name) if se else None
        market = getattr(self._main, "market_engine", None)
        pairs: list[dict[str, Any]] = []
        for sym in self.symbols:
            st = self._state.get(sym) or {}
            qty = 0.0
            mid = 0.0
            if holding is not None:
                pos = holding.positions.get(sym)
                if pos is not None:
                    qty = float(getattr(pos, "quantity", 0.0) or 0.0)
                    mid = float(getattr(pos, "mid_price", 0.0) or 0.0)
            last = 0.0
            if market is not None:
                sd = market.get_symbol(sym)
                if sd is not None:
                    last = float(getattr(sd, "last_price", 0.0) or 0.0)
            sup = st.get("sup_price")
            pairs.append(
                {
                    "symbol": sym,
                    "sup_price": float(sup) if sup is not None else None,
                    "hit_count": int(st.get("hit_count", 0) or 0),
                    "active_stop": float(st["active_stop"]) if st.get("active_stop") is not None else None,
                    "active_target": float(st["active_target"]) if st.get("active_target") is not None else None,
                    "pending_order_id": str(st.get("pending_order_id") or ""),
                    "has_position": qty > 0,
                    "quantity": qty,
                    "entry_price": float(st.get("entry_price", 0.0) or 0.0),
                    "last_price": last,
                    "mid_price": mid,
                }
            )
        h["pairs"] = pairs
        h["interval"] = str(ival)
        h["pivot_len"] = int(self.pivot_len)
        h["atr_len"] = int(self.atr_len)
        h["rr"] = float(self.rr)
        h["position_reconciliation"] = self._position_reconciliation()
        return h

    def on_timer_logic(self) -> None:
        market = getattr(self._main, "market_engine", None)
        if not market:
            self.write_log("[strategy_JH] TIMER | aborted: no market_engine", level="WARN")
            return
        ival = self.interval.binance
        self.write_log(
            f"[strategy_JH] TIMER | interval={ival} | symbols={len(self.symbols)} | "
            f"pivot_len={self.pivot_len} atr_len={self.atr_len} rr={self.rr} fill_bars={self.fill_bars}",
            level="INFO",
        )
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
            self.write_log(f"[strategy_JH {sym}] EXIT | no active stop/target", level="INFO")
            return

        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(sym)
        qty = float(pos.quantity) if pos else 0.0

        if qty <= 0:
            # If a BUY entry is still pending, keep staged exits untouched.
            pending_ids = self.get_pending_orders().get(sym, [])
            if not pending_ids:
                self.write_log(
                    f"[strategy_JH {sym}] EXIT | flat & no pending → clear stop/target "
                    f"(was stop={st.get('active_stop')} target={st.get('active_target')})",
                    level="INFO",
                )
                st["active_stop"] = None
                st["active_target"] = None
            else:
                self.write_log(
                    f"[strategy_JH {sym}] EXIT | qty=0 pending_BUY={pending_ids} → keep staged stop/target",
                    level="INFO",
                )
            return

        sym_data = self.get_symbol(sym)
        last = float(getattr(sym_data, "last_price", 0.0) or 0.0) if sym_data else 0.0
        stop_price = float(st["active_stop"])
        target_price = float(st["active_target"])
        if last <= 0:
            self.write_log(
                f"[strategy_JH {sym}] EXIT | skip: last_price<=0 qty={qty} stop={stop_price} target={target_price}",
                level="INFO",
            )
            return

        if last <= stop_price:
            self.write_log(
                f"[strategy_JH {sym}] EXIT | TRIGGER STOP | last={last:.6f} <= stop={stop_price:.6f} "
                f"target={target_price:.6f} qty={qty}",
                level="WARN",
            )
            self.close_position(sym, qty, order_type="MARKET")
            st["active_stop"] = None
            st["active_target"] = None
            return

        if last >= target_price:
            self.write_log(
                f"[strategy_JH {sym}] EXIT | TRIGGER TARGET | last={last:.6f} >= target={target_price:.6f} "
                f"stop={stop_price:.6f} qty={qty}",
                level="INFO",
            )
            self.close_position(sym, qty, order_type="MARKET")
            st["active_stop"] = None
            st["active_target"] = None
            return

        self.write_log(
            f"[strategy_JH {sym}] EXIT | HOLD | last={last:.6f} in ({stop_price:.6f}, {target_price:.6f}) qty={qty}",
            level="INFO",
        )

    # ---------------- limit timeout (15m) ----------------

    def _check_limit_timeout(self, sym: str, st: dict[str, Any], interval: str) -> None:
        # Timeout is enforced against engine pending orders (per symbol).
        pending_map = self.get_pending_orders()
        pending_ids = pending_map.get(sym, [])
        if not pending_ids:
            self.write_log(f"[strategy_JH {sym}] LIMIT_TIMEOUT | no pending orders", level="INFO")
            return
        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(sym)
        if pos and float(pos.quantity or 0.0) > 0:
            self.write_log(
                f"[strategy_JH {sym}] LIMIT_TIMEOUT | skip: in position qty={float(pos.quantity or 0)} pending={pending_ids}",
                level="INFO",
            )
            return
        bar_count = int(getattr(self._main.market_engine, "get_bar_count")(sym, interval))
        limit_bar_idx = int(st.get("limit_bar_idx") or 0)
        bars_since = bar_count - limit_bar_idx
        need = self.fill_bars + 1
        if bars_since >= need:
            oid = pending_ids[0]
            self.write_log(
                f"[strategy_JH {sym}] LIMIT_TIMEOUT | CANCEL oid={oid} | bars_since_limit={bars_since} "
                f">= fill_bars+1={need} (bar_count={bar_count} limit_bar_idx={limit_bar_idx})",
                level="WARN",
            )
            self._main.handle_intent(INTENT_CANCEL_ORDER, CancelOrderRequest(order_id=oid, symbol=sym))
        else:
            self.write_log(
                f"[strategy_JH {sym}] LIMIT_TIMEOUT | wait | pending={pending_ids} bars_since={bars_since} "
                f"< need={need} bar_count={bar_count} limit_bar_idx={limit_bar_idx}",
                level="INFO",
            )

    # ---------------- signal (15m) ----------------

    def _process_signal(self, sym: str, st: dict[str, Any], interval: str) -> None:
        market = getattr(self._main, "market_engine", None)
        if market is None:
            return
        need = max(4, 2 * self.pivot_len + 1, self.atr_len + 1)
        bars = market.get_last_bars(sym, need, interval)
        if len(bars) < need:
            self.write_log(
                f"[strategy_JH {sym}] SIGNAL | skip: bars={len(bars)} < need={need}",
                level="INFO",
            )
            return
        cur = bars[-1]
        prev = bars[-2]

        holding = self._main.strategy_engine.get_holding(self.strategy_name)
        pos = holding.positions.get(sym)
        position_qty = float(pos.quantity) if pos else 0.0
        flat = position_qty == 0.0

        pl = market.get_pivot_low(sym, self.pivot_len, self.pivot_len, interval)
        if pl is not None:
            self.write_log(
                f"[strategy_JH {sym}] SIGNAL | pivot_low={float(pl):.6f} → reset sup/hit_count",
                level="INFO",
            )
            st["sup_price"] = float(pl)
            st["hit_count"] = 0
            st["hit1_low"] = None

        if st.get("sup_price") is None:
            self.write_log(f"[strategy_JH {sym}] SIGNAL | skip: no sup_price", level="INFO")
            return

        sup_price = float(st["sup_price"])
        hit_support = cur.low <= sup_price
        if not (hit_support and flat):
            self.write_log(
                f"[strategy_JH {sym}] SIGNAL | skip: hit_support={hit_support} flat={flat} "
                f"L={cur.low:.6f} sup={sup_price:.6f} pos_qty={position_qty}",
                level="INFO",
            )
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
                self.write_log(
                    f"[strategy_JH {sym}] SIGNAL | H2 reset support | higher_low_fail={higher_low_fail} "
                    f"ok_bear={ok_bear} ok_t3={ok_t3} ok_cs={ok_cs} ok_po={ok_po} ok_atr={ok_atr} "
                    f"L={cur.low:.6f} hit1_low={hit1_low}",
                    level="INFO",
                )
                st["sup_price"] = None
                st["hit_count"] = 0
                st["hit1_low"] = None
                return

        hc = int(st["hit_count"])
        self.write_log(
            f"[strategy_JH {sym}] SIGNAL | H{hc} eval | ok_bear={ok_bear} ok_t3={ok_t3} ok_cs={ok_cs} "
            f"ok_po={ok_po} ok_atr={ok_atr} atr={atr:.6f} risk={risk:.6f} higher_low_fail={higher_low_fail} "
            f"OHLC=({cur.open:.6f},{cur.high:.6f},{cur.low:.6f},{cur.close:.6f}) sup={sup_price:.6f} "
            f"entry~{entry_price:.6f} stop~{stop_price:.6f} → signal={signal}",
            level="INFO",
        )

        if not signal:
            return

        target_price = entry_price + self.rr * risk

        risk_per_unit = entry_price - stop_price
        if risk_per_unit <= 0:
            self.write_log(
                f"[strategy_JH {sym}] SIGNAL | skip entry: risk_per_unit={risk_per_unit} <= 0",
                level="INFO",
            )
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
        # Inline: round qty down to exchange amount precision.
        factor = 10.0**amt_dec if amt_dec >= 0 else 1.0
        qty = int(qty * factor) / factor
        if qty <= 0:
            self.write_log(
                f"[strategy_JH {sym}] SIGNAL | skip entry: qty after round <= 0 (raw sizing was risk_amt={risk_amount})",
                level="INFO",
            )
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
            f"[strategy_JH {sym}] SIGNAL | {ht} SUBMIT BUY LIMIT | entry={rounded_entry:.6f} "
            f"stop={rounded_stop:.6f} target={rounded_target:.6f} qty={qty:.6f} risk_amt=${risk_amount:.2f}",
            level="INFO",
        )

    def on_order(self, event: Any) -> None:
        data = getattr(event, "data", event)
        # Order events are broadcast to all strategies; ignore orders not belonging to this strategy.
        order_strat = getattr(data, "strategy_name", None)
        if order_strat is not None and order_strat != self.strategy_name:
            return
        super().on_order(event)
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
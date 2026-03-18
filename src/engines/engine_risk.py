"""
Risk engine: receives order and timer events; can emit EVENT_RISK_ALERT.
Checks drawdown vs ATR-based limit; on breach, closes positions and stops strategies one by one.
"""

import os
from typing import Any

from src.utilities.base_engine import BaseEngine

# Account initial balance (USD) — only constant; override via env RISK_ACCOUNT_INIT_BALANCE
ACCOUNT_INIT_BALANCE: float = float(os.getenv("RISK_ACCOUNT_INIT_BALANCE", "0.0"))

# Hard-coded risk config
RISK_CONFIG = {
    "max_drawdown_pct": 10.0,
    "atr_drawdown_multiplier": 2.0,
    "atr_daily_len": 14,
    "daily_interval": "1d",
    "atr_log_every_ticks": 60,
}


def _parse_equity_usd(bal: dict[str, Any] | None) -> float:
    """Extract total USD/USDT equity from gateway cached balance (Wallet or SpotWallet)."""
    if not bal or not isinstance(bal, dict):
        return 0.0
    wallet = bal.get("Wallet") or bal.get("SpotWallet")
    if not wallet or not isinstance(wallet, dict):
        return 0.0
    total = 0.0
    for asset, entry in wallet.items():
        if not isinstance(entry, dict):
            continue
        free = float(entry.get("Free", 0) or 0)
        lock = float(entry.get("Lock", 0) or 0)
        if str(asset).upper() in ("USD", "USDT", "BUSD"):
            total += free + lock
    return total


class RiskEngine(BaseEngine):
    """Risk checks and alerts; override on_order and on_timer to implement."""

    def __init__(self, main_engine=None, engine_name: str = "Risk") -> None:
        super().__init__(main_engine=main_engine, engine_name=engine_name)
        cfg = RISK_CONFIG
        self.account_init_balance: float = ACCOUNT_INIT_BALANCE
        self.max_drawdown_pct: float = float(cfg["max_drawdown_pct"])
        self.atr_drawdown_multiplier: float = float(cfg["atr_drawdown_multiplier"])
        self.atr_daily_len: int = int(cfg["atr_daily_len"])
        self.daily_interval: str = str(cfg["daily_interval"])
        self.daily_bars_needed: int = self.atr_daily_len + 1
        self.atr_log_every_ticks: int = int(cfg["atr_log_every_ticks"])
        self._daily_atr: dict[str, float] = {}
        self._last_atr_log_tick: int = 0
        self._breach_triggered: bool = False
        self._init_snapped: bool = False

    def on_order(self, event) -> None:
        pass

    def on_timer(self) -> None:
        if self._breach_triggered:
            self._close_and_stop_all()
            return
        self._check_daily_atr()
        self._check_drawdown()

    def _check_daily_atr(self) -> None:
        """Check ATR (daily timeframe) for all active pairs using market engine."""
        me = self.main_engine
        if me is None:
            return
        market = getattr(me, "market_engine", None)
        if market is None or not hasattr(market, "get_atr"):
            return
        try:
            symbols = getattr(me, "active_pairs", None) or getattr(me, "trading_pairs", []) or []
        except Exception:
            symbols = []
        if not symbols:
            return

        self._daily_atr = {}
        for symbol in symbols:
            try:
                market.ensure_history(symbol, self.daily_interval, self.daily_bars_needed)
                atr = market.get_atr(symbol, self.atr_daily_len, self.daily_interval)
                if atr > 0:
                    self._daily_atr[symbol] = atr
            except Exception:
                continue

        if self._daily_atr:
            self._last_atr_log_tick += 1
            if self._last_atr_log_tick % self.atr_log_every_ticks == 1:
                items = sorted(self._daily_atr.items())[:10]
                tail = "..." if len(self._daily_atr) > 10 else ""
                self.log(
                    f"Daily ATR ({self.atr_daily_len}d): " + ", ".join(f"{s}={v:.2f}" for s, v in items) + tail,
                    level="DEBUG",
                    source="Risk",
                )

    def _max_drawdown_pct(self) -> float:
        """Max allowed drawdown %: use config max_drawdown_pct, or ATR-based if ATR available."""
        if self.account_init_balance <= 0:
            return self.max_drawdown_pct
        if not self._daily_atr:
            return self.max_drawdown_pct
        market = getattr(self.main_engine, "market_engine", None) if self.main_engine else None
        if not market:
            return self.max_drawdown_pct
        atr_pcts: list[float] = []
        for symbol, atr in self._daily_atr.items():
            if atr <= 0:
                continue
            sd = market.get_symbol(symbol) if market else None
            price = float(getattr(sd, "last_price", 0) or 0) if sd else 0
            if price > 0:
                atr_pcts.append(atr / price * 100)
        if not atr_pcts:
            return self.max_drawdown_pct
        avg_atr_pct = sum(atr_pcts) / len(atr_pcts)
        atr_based = avg_atr_pct * self.atr_drawdown_multiplier
        return min(self.max_drawdown_pct, max(1.0, atr_based))

    def _check_drawdown(self) -> None:
        """Check drawdown vs limit; on breach, force close all and stop all strategies."""
        me = self.main_engine
        if me is None:
            return
        gateway = getattr(me, "gateway_engine", None)
        if gateway is None or not hasattr(gateway, "get_cached_balance"):
            return

        bal = gateway.get_cached_balance()
        equity = _parse_equity_usd(bal)
        if equity <= 0:
            return
        if self.account_init_balance <= 0 and not self._init_snapped:
            self.account_init_balance = equity
            self._init_snapped = True
            self.log(f"Risk: snapped init balance = {equity:.0f}", level="INFO", source="Risk")
        init = self.account_init_balance
        if init <= 0:
            return
        drawdown_pct = (init - equity) / init * 100.0 if init > 0 else 0.0
        max_dd = self._max_drawdown_pct()

        if drawdown_pct >= max_dd:
            self._breach_triggered = True
            self.log(
                f"RISK BREACH: drawdown {drawdown_pct:.1f}% >= max {max_dd:.1f}% (equity={equity:.0f} init={init:.0f}); "
                "closing positions and stopping strategies",
                level="ERROR",
                source="Risk",
            )
            self._close_and_stop_all()

    def _close_and_stop_all(self) -> None:
        """Check positions per strategy; close then stop one by one. Retries each tick until all stopped."""
        me = self.main_engine
        if me is None:
            return
        strat_engine = getattr(me, "strategy_engine", None)
        if strat_engine is None:
            return
        strategies = getattr(strat_engine, "_strategies", [])
        for s in list(strategies):
            name = str(getattr(s, "strategy_name", "") or "").strip()
            if not name:
                continue
            holding = strat_engine.get_holding(name)
            has_positions = False
            for pos in getattr(holding, "positions", {}).values():
                qty = float(getattr(pos, "quantity", 0.0) or 0.0)
                if qty != 0.0:
                    has_positions = True
                    break
            if has_positions:
                try:
                    if hasattr(s, "clear_all_positions"):
                        s.clear_all_positions()
                        self.log(f"Risk: closing positions for {name}", level="WARN", source="Risk")
                except Exception as e:
                    self.log(f"Risk: clear_all_positions failed for {name}: {e}", level="ERROR", source="Risk")
                continue
            try:
                me.stop_strategy(name)
                self.log(f"Risk: stopped strategy {name}", level="WARN", source="Risk")
            except ValueError as e:
                self.log(f"Risk: {e}", level="DEBUG", source="Risk")
            except Exception as e:
                self.log(f"Risk: stop_strategy failed for {name}: {e}", level="ERROR", source="Risk")

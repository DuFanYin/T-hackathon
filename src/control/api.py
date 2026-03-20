from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.control.engine_manager import EngineManager, Mode
from src.control.order_store import OrderStore
from src.engines.engine_strategy import AVAILABLE_STRATEGIES
from src.strategies.template import StrategyTemplate


def _holding_to_dict(holding) -> dict[str, Any]:
    positions = {}
    for sym, pos in getattr(holding, "positions", {}).items():
        positions[sym] = {
            "symbol": getattr(pos, "symbol", sym),
            "quantity": float(getattr(pos, "quantity", 0.0) or 0.0),
            "avg_cost": float(getattr(pos, "avg_cost", 0.0) or 0.0),
            "cost_value": float(getattr(pos, "cost_value", 0.0) or 0.0),
            "realized_pnl": float(getattr(pos, "realized_pnl", 0.0) or 0.0),
            "mid_price": float(getattr(pos, "mid_price", 0.0) or 0.0),
            "current_value": float(getattr(pos, "current_value")() if hasattr(pos, "current_value") else 0.0),
        }
    return {
        "positions": positions,
        "total_cost": float(getattr(holding, "total_cost", 0.0) or 0.0),
        "current_value": float(getattr(holding, "current_value", 0.0) or 0.0),
        "unrealized_pnl": float(getattr(holding, "unrealized_pnl", 0.0) or 0.0),
        "realized_pnl": float(getattr(holding, "realized_pnl", 0.0) or 0.0),
        "pnl": float(getattr(holding, "pnl", 0.0) or 0.0),
    }


def create_app(engine_manager: EngineManager) -> FastAPI:
    app = FastAPI(title="T-hackathon Control API", version="0.1")

    os_mod = __import__("os")
    cors_origins_env = str(getattr(os_mod, "getenv")("CONTROL_CORS_ORIGINS", "")).strip()
    environment = str(getattr(os_mod, "getenv")("ENVIRONMENT", "local")).strip().lower()

    allow_origins: list[str] = []
    if cors_origins_env:
        allow_origins.extend([o.strip() for o in cors_origins_env.split(",") if o.strip()])

    # In local mode always permit the Vite dev origins, even if CONTROL_CORS_ORIGINS is set.
    if environment == "local":
        for o in ("http://localhost:5173", "http://127.0.0.1:5173"):
            if o not in allow_origins:
                allow_origins.append(o)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _eng():
        try:
            return engine_manager.require()
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/system/status")
    def system_status():
        st = engine_manager.status()
        return {"running": st.running, "mode": st.mode}

    @app.post("/system/start")
    def system_start(payload: dict[str, Any]):
        mode = str(payload.get("mode", "")).strip().lower()
        if mode not in ("mock", "real"):
            raise HTTPException(status_code=400, detail="mode must be mock or real")
        st = engine_manager.start(mode=mode)  # type: ignore[arg-type]
        return {"running": st.running, "mode": st.mode}

    @app.post("/system/stop")
    def system_stop():
        try:
            st = engine_manager.stop()
            return {"running": st.running, "mode": st.mode}
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/health")
    def health():
        main_engine = _eng()
        return {"ok": True, "env_mode": getattr(main_engine, "env_mode", "unknown")}

    @app.get("/strategies/available")
    def strategies_available():
        return {"available": sorted(list(AVAILABLE_STRATEGIES.keys()))}

    @app.get("/pairs")
    def pairs():
        main_engine = _eng()
        return {"pairs": main_engine.get_all_trading_pairs()}

    # ------------------------------------------------------------------
    # Account / exchange state (Roostoo v3 passthrough)
    # ------------------------------------------------------------------

    @app.get("/account/balance")
    def account_balance():
        main_engine = _eng()
        return {"balance": main_engine.gateway_engine.get_cached_balance()}

    @app.get("/account/pending_count")
    def account_pending_count():
        main_engine = _eng()
        return {"pending_count": main_engine.gateway_engine.get_cached_pending_count()}

    @app.get("/account/orders")
    def account_orders(pending_only: bool = True, limit: int = 200):
        main_engine = _eng()
        # Cached snapshot only (UI must not trigger exchange calls).
        return {"orders": main_engine.gateway_engine.get_cached_orders_snapshot()}

    @app.get("/account/pnl")
    def account_pnl():
        """Current equity, PnL and PnL % from risk engine."""
        main_engine = _eng()
        risk = getattr(main_engine, "risk_engine", None)
        if risk is None or not hasattr(risk, "get_current_pnl"):
            return {"equity": 0.0, "init_balance": 0.0, "pnl": 0.0, "pnl_pct": 0.0}
        return risk.get_current_pnl()

    # ------------------------------------------------------------------
    # Orders DB (SQLite)
    # ------------------------------------------------------------------

    @app.get("/orders")
    def orders_latest(
        strategy: str | None = None,
        symbol: str | None = None,
        limit: int = 500,
    ):
        """
        Read orders from the local SQLite store (latest row per order_id).
        Works even when the engine is stopped.
        """
        try:
            store = OrderStore()
            rows = store.query(strategy=strategy, symbol=symbol, limit=limit)
            return {"rows": rows}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/strategies/running")
    def strategies_running():
        main_engine = _eng()
        items = []
        for s in getattr(main_engine.strategy_engine, "_strategies", []):
            items.append(
                {
                    "name": getattr(s, "strategy_name", ""),
                    "inited": bool(getattr(s, "inited", False)),
                    "started": bool(getattr(s, "started", False)),
                    "error": bool(getattr(s, "error", False)),
                    "error_msg": str(getattr(s, "error_msg", "")),
                }
            )
        return {"running": items}

    @app.post("/strategies/start")
    def strategy_start(payload: dict[str, Any]):
        main_engine = _eng()
        # Accept either {name} (preferred) or legacy {strategy} (mapped to name).
        name = str(payload.get("name", "")).strip()
        if not name:
            strategy = str(payload.get("strategy", "")).strip()
            if not strategy:
                raise HTTPException(
                    status_code=400,
                    detail="payload must include either name or strategy",
                )
            name = strategy
        if main_engine.get_strategy(name) is None:
            raise HTTPException(status_code=404, detail=f"strategy not found: {name}")
        try:
            main_engine.start_strategy(name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "name": name}

    @app.post("/strategies/stop")
    def strategy_stop(payload: dict[str, Any]):
        main_engine = _eng()
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="payload must include name")
        try:
            main_engine.stop_strategy(name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "name": name}

    @app.get("/positions")
    def positions():
        main_engine = _eng()
        holdings = getattr(main_engine.strategy_engine, "_holdings", {})
        out: dict[str, Any] = {}
        for strat_name, holding in holdings.items():
            out[strat_name] = _holding_to_dict(holding)
        return {"holdings": out}

    @app.post("/positions/close")
    def close_strategy_positions(payload: dict[str, Any]):
        """
        Close (flatten) all positions for one strategy.

        Long-only: issues MARKET SELL for any positive quantity tracked in holdings.
        """
        main_engine = _eng()
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="payload must include name")
        s = main_engine.get_strategy(name)
        if s is None:
            raise HTTPException(status_code=404, detail=f"strategy not found: {name}")
        if not isinstance(s, StrategyTemplate):
            raise HTTPException(status_code=500, detail="strategy type unsupported")
        try:
            s.clear_all_positions()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "name": name}

    @app.post("/positions/close_all")
    def close_all_positions():
        """
        Close (flatten) all positions for all registered strategies.
        """
        main_engine = _eng()
        closed: list[str] = []
        errors: dict[str, str] = {}
        for s in getattr(main_engine.strategy_engine, "_strategies", []):
            name = str(getattr(s, "strategy_name", "") or "").strip()
            if not name:
                continue
            if not isinstance(s, StrategyTemplate):
                errors[name] = "strategy type unsupported"
                continue
            try:
                s.clear_all_positions()
                closed.append(name)
            except Exception as e:
                errors[name] = str(e)
        return {"ok": True, "closed": closed, "errors": errors}

    @app.get("/logs/tail")
    def logs_tail(n: int = 200):
        """Read last n lines from log file. Works even when engine is stopped."""
        log_file = (os.getenv("LOG_FILE") or "data/logs/system.log").strip()
        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            lines = [ln.rstrip("\n\r") for ln in lines[-n:] if ln.strip()]
            return {"lines": lines}
        except FileNotFoundError:
            return {"lines": []}
        except Exception:
            return {"lines": []}

    return app


from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from src.engines.engine_strategy import AVAILABLE_STRATEGIES
from src.control.engine_manager import EngineManager, Mode


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

    admin_token_env = str(getattr(os_mod, "getenv")("CONTROL_ADMIN_TOKEN", "")).strip() or None

    def _require_admin(x_admin_token: str | None = Header(default=None, alias="x-admin-token")) -> None:
        """
        Simple shared-token guard for mutating endpoints.
        If CONTROL_ADMIN_TOKEN is not set, all calls are allowed (dev mode).
        """
        if admin_token_env is None:
            return
        if not x_admin_token or x_admin_token != admin_token_env:
            raise HTTPException(status_code=401, detail="admin token required")

    def _eng():
        try:
            return engine_manager.require()
        except Exception as e:
            raise HTTPException(status_code=503, detail=str(e))

    @app.get("/auth/check")
    def auth_check(_: None = Depends(_require_admin)):
        return {"ok": True}

    @app.get("/system/status")
    def system_status():
        st = engine_manager.status()
        return {"running": st.running, "mode": st.mode}

    @app.post("/system/start")
    def system_start(payload: dict[str, Any], _: None = Depends(_require_admin)):
        mode = str(payload.get("mode", "")).strip().lower()
        if mode not in ("mock", "real"):
            raise HTTPException(status_code=400, detail="mode must be mock or real")
        st = engine_manager.start(mode=mode)  # type: ignore[arg-type]
        return {"running": st.running, "mode": st.mode}

    @app.post("/system/stop")
    def system_stop(_: None = Depends(_require_admin)):
        st = engine_manager.stop()
        return {"running": st.running, "mode": st.mode}

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
    def account_balance(_: None = Depends(_require_admin)):
        main_engine = _eng()
        return {"balance": main_engine.gateway_engine.get_cached_balance()}

    @app.get("/account/pending_count")
    def account_pending_count(_: None = Depends(_require_admin)):
        main_engine = _eng()
        return {"pending_count": main_engine.gateway_engine.get_cached_pending_count()}

    @app.get("/account/orders")
    def account_orders(pending_only: bool = True, limit: int = 200, _: None = Depends(_require_admin)):
        main_engine = _eng()
        # Cached snapshot only (UI must not trigger exchange calls).
        return {"orders": main_engine.gateway_engine.get_cached_orders_snapshot()}

    # ------------------------------------------------------------------
    # Orders DB (SQLite)
    # ------------------------------------------------------------------

    @app.get("/orders")
    def orders_latest(
        strategy: str | None = None,
        symbol: str | None = None,
        limit: int = 500,
        _: None = Depends(_require_admin),
    ):
        """
        Read orders from the local SQLite store (latest row per order_id).
        Works even when the engine is stopped.
        """
        db_path = "data/orders/orders.db"
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            where: list[str] = []
            params: list[object] = []
            if strategy:
                where.append("strategy_name = ?")
                params.append(strategy)
            if symbol:
                where.append("symbol = ?")
                params.append(symbol)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            lim = max(1, min(int(limit), 5000))
            rows = conn.execute(
                f"""
                SELECT
                  order_id, strategy_name, symbol, side, status,
                  quantity, price, filled_quantity, filled_avg_price,
                  updated_ts, raw_json
                FROM orders_latest
                {where_sql}
                ORDER BY updated_ts DESC
                LIMIT ?
                """,
                (*params, lim),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for r in rows:
                out.append({k: r[k] for k in r.keys()})
            return {"rows": out}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            try:
                conn.close()
            except Exception:
                pass

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
    def strategy_start(payload: dict[str, Any], _: None = Depends(_require_admin)):
        main_engine = _eng()
        # Accept either {strategy, symbol} or {name}
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
                try:
                    main_engine.add_strategy(strategy)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))
        try:
            main_engine.init_strategy(name)
            main_engine.start_strategy(name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "name": name}

    @app.post("/strategies/stop")
    def strategy_stop(payload: dict[str, Any], _: None = Depends(_require_admin)):
        main_engine = _eng()
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="payload must include name")
        try:
            main_engine.stop_strategy(name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "name": name}

    @app.post("/strategies/add")
    def strategy_add(payload: dict[str, Any], _: None = Depends(_require_admin)):
        main_engine = _eng()
        strategy = str(payload.get("strategy", "")).strip()
        if not strategy:
            raise HTTPException(status_code=400, detail="payload must include strategy")
        full_name = strategy
        try:
            if main_engine.get_strategy(full_name) is not None:
                return {"ok": True, "name": full_name}
            main_engine.add_strategy(strategy)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "name": full_name}

    @app.post("/strategies/init")
    def strategy_init(payload: dict[str, Any], _: None = Depends(_require_admin)):
        main_engine = _eng()
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="payload must include name")
        try:
            main_engine.init_strategy(name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "name": name}

    @app.post("/strategies/delete")
    def strategy_delete(payload: dict[str, Any], _: None = Depends(_require_admin)):
        main_engine = _eng()
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="payload must include name")
        try:
            main_engine.delete_strategy(name)
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

    @app.get("/logs/tail")
    def logs_tail(n: int = 200):
        # Use the manager directly so "not running" returns 200 with empty lines.
        main_engine = engine_manager.get()
        if main_engine is None:
            return {"lines": []}
        return {"lines": main_engine.log_store.tail(n)}

    @app.get("/logs/stream")
    async def logs_stream():
        """
        Stream logs via Server-Sent Events.

        If the trading engine is not running yet, return an empty SSE stream (200)
        instead of failing, so the frontend can stay connected while waiting.
        """
        # Use the manager directly so we can tolerate "not running" without raising.
        main_engine = engine_manager.get()

        if main_engine is None:
            async def empty_gen():
                if False:
                    yield ""  # pragma: no cover
            return StreamingResponse(empty_gen(), media_type="text/event-stream")

        async def event_gen():
            async for line in main_engine.log_store.subscribe():
                payload = json.dumps({"line": line}, ensure_ascii=False)
                yield f"data: {payload}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    return app


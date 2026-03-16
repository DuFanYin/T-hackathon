from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException
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

    cors_origins_env = str(getattr(__import__("os"), "getenv")("CONTROL_CORS_ORIGINS", "")).strip()
    allow_origins = (
        [o.strip() for o in cors_origins_env.split(",") if o.strip()]
        if cors_origins_env
        else ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
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
        # Accept either {strategy, symbol} or {name}
        name = str(payload.get("name", "")).strip()
        if not name:
            strategy = str(payload.get("strategy", "")).strip()
            symbol = str(payload.get("symbol", "")).strip().upper()
            if not strategy or not symbol:
                raise HTTPException(
                    status_code=400,
                    detail="payload must include either name or (strategy and symbol)",
                )
            name = f"{strategy}_{symbol}"
            if main_engine.get_strategy(name) is None:
                try:
                    main_engine.add_strategy(strategy, symbol)
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))
        try:
            main_engine.init_strategy(name)
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

    @app.post("/strategies/add")
    def strategy_add(payload: dict[str, Any]):
        main_engine = _eng()
        strategy = str(payload.get("strategy", "")).strip()
        symbol = str(payload.get("symbol", "")).strip().upper()
        if not strategy or not symbol:
            raise HTTPException(status_code=400, detail="payload must include strategy and symbol")
        full_name = f"{strategy}_{symbol}"
        try:
            if main_engine.get_strategy(full_name) is not None:
                return {"ok": True, "name": full_name}
            main_engine.add_strategy(strategy, symbol)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "name": full_name}

    @app.post("/strategies/init")
    def strategy_init(payload: dict[str, Any]):
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
    def strategy_delete(payload: dict[str, Any]):
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
        holdings = getattr(main_engine.position_engine, "_holdings", {})
        out: dict[str, Any] = {}
        for strat_name, holding in holdings.items():
            out[strat_name] = _holding_to_dict(holding)
        return {"holdings": out}

    @app.get("/symbols")
    def symbols_all():
        """
        Return snapshot data for all symbols currently known to the market engine.

        This is intended for the control UI "Symbols" page: a read-only view with no controls.
        """
        main_engine = _eng()
        # Access the internal cache directly; this is a read-only snapshot.
        market_engine = main_engine.market_engine
        out: dict[str, Any] = {}
        symbols_cache = getattr(market_engine, "_symbols", {}) or {}
        for sym_key, sym in symbols_cache.items():
            if sym is None:
                continue
            symbol_upper = str(getattr(sym, "symbol", sym_key or "") or "").upper()
            if not symbol_upper:
                continue
            out[symbol_upper] = {
                "symbol": symbol_upper,
                "last_price": float(getattr(sym, "last_price", 0.0) or 0.0),
                "bid_price": getattr(sym, "bid_price", None),
                "ask_price": getattr(sym, "ask_price", None),
                "volume_24h": getattr(sym, "volume_24h", None),
                "notional_24h": getattr(sym, "notional_24h", None),
                "change_24h": getattr(sym, "change_24h", None),
                "price_precision": getattr(sym, "price_precision", None),
                "amount_precision": getattr(sym, "amount_precision", None),
                "min_order_notional": getattr(sym, "min_order_notional", None),
            }
        return {"symbols": out}

    @app.get("/logs/tail")
    def logs_tail(n: int = 200):
        main_engine = _eng()
        return {"lines": main_engine.log_store.tail(n)}

    @app.get("/logs/stream")
    async def logs_stream():
        main_engine = _eng()
        async def event_gen():
            async for line in main_engine.log_store.subscribe():
                # SSE: "data: <json>\n\n"
                payload = json.dumps({"line": line}, ensure_ascii=False)
                yield f"data: {payload}\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    return app


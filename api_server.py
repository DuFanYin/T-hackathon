#!/usr/bin/env python3
"""
AWS-friendly control-plane entrypoint:

- Creates MainEngine (mock|real)
- Auto-loads strategies_config.json and starts all strategies (same as main.py)
- Starts FastAPI server for remote control/monitoring

Run:
  python api_server.py mock
  python api_server.py real
"""

from __future__ import annotations

import json
import os
import sys
from dotenv import load_dotenv


def main() -> int:
    root_dir = os.path.dirname(os.path.abspath(__file__))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)

    # Load .env at repo root (typical for EC2 deployment)
    load_dotenv(os.path.join(root_dir, ".env"))

    from src.control.api import create_app
    from src.control.engine_manager import EngineManager

    host = os.getenv("CONTROL_HOST", "0.0.0.0")
    port = int(os.getenv("CONTROL_PORT", "8000"))

    mgr = EngineManager()
    # Optional: allow starting system from CLI arg.
    if len(sys.argv) >= 2:
        arg = str(sys.argv[1]).strip().lower()
        if arg in ("mock", "real"):
            print(f"[API] Auto-start system mode={arg}")
            mgr.start(mode=arg)  # type: ignore[arg-type]
        else:
            print("[API] Usage: python api_server.py [mock|real]")
            return 2

    app = create_app(mgr)

    import uvicorn

    print(f"[API] Listening on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


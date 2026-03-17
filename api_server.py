#!/usr/bin/env python3
"""
Control-plane entrypoint:

- Loads .env
- Creates EngineManager
- Starts FastAPI server for remote control/monitoring

Run:
  python api_server.py
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

    app = create_app(mgr)

    import uvicorn

    print(f"[API] Listening on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


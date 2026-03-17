from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Optional

from src.utilities.object import OrderData


class OrderStore:
    """
    SQLite-backed order persistence.

    - orders_latest: one row per order_id (latest known state)
    - order_updates: append-only history of updates
    """

    def __init__(self, db_path: str = "data/orders/orders.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders_latest (
              order_id TEXT PRIMARY KEY,
              strategy_name TEXT,
              symbol TEXT,
              side TEXT,
              status TEXT,
              quantity REAL,
              price REAL,
              filled_quantity REAL,
              filled_avg_price REAL,
              updated_ts REAL,
              raw_json TEXT
            );
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS order_updates (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              order_id TEXT NOT NULL,
              strategy_name TEXT,
              symbol TEXT,
              side TEXT,
              status TEXT,
              quantity REAL,
              price REAL,
              filled_quantity REAL,
              filled_avg_price REAL,
              updated_ts REAL,
              raw_json TEXT
            );
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_order_updates_order_id ON order_updates(order_id);")
        self._conn.commit()

    def close(self) -> None:
        try:
            with self._lock:
                self._conn.close()
        except Exception:
            pass

    def upsert(self, order: OrderData, *, raw: Optional[dict[str, Any]] = None) -> None:
        """
        Persist an OrderData update (latest + history).
        Never throws (best-effort persistence).
        """
        try:
            now = time.time()
            raw_json = None
            if raw is not None:
                try:
                    raw_json = json.dumps(raw, ensure_ascii=False)
                except Exception:
                    raw_json = None

            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO order_updates (
                      order_id, strategy_name, symbol, side, status,
                      quantity, price, filled_quantity, filled_avg_price,
                      updated_ts, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        str(order.order_id),
                        str(getattr(order, "strategy_name", "") or ""),
                        str(order.symbol),
                        str(order.side),
                        str(order.status),
                        float(order.quantity or 0.0),
                        float(order.price or 0.0),
                        float(order.filled_quantity or 0.0),
                        float(order.filled_avg_price or 0.0),
                        float(now),
                        raw_json,
                    ),
                )
                self._conn.execute(
                    """
                    INSERT INTO orders_latest (
                      order_id, strategy_name, symbol, side, status,
                      quantity, price, filled_quantity, filled_avg_price,
                      updated_ts, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(order_id) DO UPDATE SET
                      strategy_name=excluded.strategy_name,
                      symbol=excluded.symbol,
                      side=excluded.side,
                      status=excluded.status,
                      quantity=excluded.quantity,
                      price=excluded.price,
                      filled_quantity=excluded.filled_quantity,
                      filled_avg_price=excluded.filled_avg_price,
                      updated_ts=excluded.updated_ts,
                      raw_json=COALESCE(excluded.raw_json, orders_latest.raw_json);
                    """,
                    (
                        str(order.order_id),
                        str(getattr(order, "strategy_name", "") or ""),
                        str(order.symbol),
                        str(order.side),
                        str(order.status),
                        float(order.quantity or 0.0),
                        float(order.price or 0.0),
                        float(order.filled_quantity or 0.0),
                        float(order.filled_avg_price or 0.0),
                        float(now),
                        raw_json,
                    ),
                )
                self._conn.commit()
        except Exception:
            return


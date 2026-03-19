from __future__ import annotations

import os
import sqlite3
from typing import Any, Optional


class OrderStore:
    """
    Read-only SQLite order store for control API.

    - orders: single table of finished orders (FILLED only, written by GatewayEngine)
    """

    def __init__(self, db_path: str = "data/orders/orders.db") -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        self._init_schema(conn)
        conn.close()

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
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
        conn.commit()

    def query(
        self,
        strategy: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Read finished orders from orders table. Works even when engine is stopped."""
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
        params.append(lim)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"""
                SELECT
                  order_id, strategy_name, symbol, side, status,
                  quantity, price, filled_quantity, filled_avg_price,
                  updated_ts, raw_json
                FROM orders
                {where_sql}
                ORDER BY updated_ts DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

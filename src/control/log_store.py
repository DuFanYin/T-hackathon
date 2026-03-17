from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime
from typing import AsyncIterator, Deque, Set


class LogStore:
    """
    In-memory log fanout for control API.

    - Keeps a bounded tail buffer for "recent logs".
    - Allows multiple SSE subscribers via asyncio queues.
    """

    def __init__(self, maxlen: int = 2000) -> None:
        self._tail: Deque[str] = deque(maxlen=maxlen)
        self._subscribers: Set[asyncio.Queue[str]] = set()

    def append(self, line: str) -> None:
        # Backend is the single source of timestamp formatting.
        ts = datetime.now().strftime("%m-%d %H:%M:%S")
        msg = f"{ts} | {str(line)}"
        self._tail.append(msg)
        # Non-blocking fanout; drop if subscriber queue is full/hung.
        for q in list(self._subscribers):
            try:
                q.put_nowait(msg)
            except Exception:
                # remove broken subscriber
                self._subscribers.discard(q)

    def tail(self, n: int = 200) -> list[str]:
        if n <= 0:
            return []
        return list(self._tail)[-n:]

    async def subscribe(self) -> AsyncIterator[str]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        try:
            while True:
                line = await q.get()
                yield line
        finally:
            self._subscribers.discard(q)


"""Retrying uploader that acknowledges offline events only after success."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from ..queue import OfflineQueue


class QueueUploader:
    def __init__(self, queue: OfflineQueue, send: Callable[[dict[str, Any]], Awaitable[Any]],
                 max_attempts: int = 3, base_delay: float = .1) -> None:
        self.queue, self.send = queue, send
        self.max_attempts, self.base_delay = max_attempts, base_delay

    async def flush(self, limit: int = 100) -> int:
        items = self.queue.peek_batch(limit)
        acknowledged: list[int] = []
        for item_id, payload in items:
            for attempt in range(self.max_attempts):
                try:
                    await self.send(payload)
                    acknowledged.append(item_id)
                    break
                except Exception:
                    if attempt + 1 == self.max_attempts:
                        break
                    await asyncio.sleep(self.base_delay * (2 ** attempt))
            if item_id not in acknowledged:
                break
        self.queue.ack(acknowledged)
        return len(acknowledged)

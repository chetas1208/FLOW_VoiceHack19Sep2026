"""Fixed-window rate limiting with in-memory and Redis backends."""

from __future__ import annotations

import threading
import time
from typing import Protocol


class RateLimiter(Protocol):
    def hit(self, key: str, limit: int, window_seconds: int) -> bool: ...


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._counts: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        window = int(time.time() // window_seconds)
        with self._lock:
            current_window, count = self._counts.get(key, (window, 0))
            if current_window != window:
                count = 0
            count += 1
            self._counts[key] = (window, count)
            if len(self._counts) > 50_000:
                self._counts = {k: v for k, v in self._counts.items() if v[0] == window}
            return count <= limit


class RedisRateLimiter:
    def __init__(self, client) -> None:  # noqa: ANN001
        self.client = client

    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        window = int(time.time() // window_seconds)
        name = f"flow:rl:{key}:{window}"
        try:
            pipe = self.client.pipeline()
            pipe.incr(name); pipe.expire(name, window_seconds + 1)
            count = pipe.execute()[0]
        except Exception:  # Redis outage must not take ingestion down; fail open, logged by caller metrics
            return True
        return int(count) <= limit

"""Realtime fan-out. The database stays the source of truth; the bus only wakes subscribers."""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Protocol


class Subscription(Protocol):
    async def get(self, timeout: float) -> dict[str, Any] | None: ...
    async def close(self) -> None: ...


class RealtimeBus(Protocol):
    def publish(self, session_id: str, message: dict[str, Any]) -> None: ...
    async def subscribe(self, session_id: str) -> Subscription: ...
    async def aclose(self) -> None: ...


class _LocalSubscription:
    def __init__(self, bus: "InProcessBus", session_id: str, loop: asyncio.AbstractEventLoop) -> None:
        self.bus, self.session_id, self.loop = bus, session_id, loop
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self.overflowed = False

    def offer(self, message: dict[str, Any]) -> None:
        try:
            self.queue.put_nowait(message)
        except asyncio.QueueFull:
            self.overflowed = True

    async def get(self, timeout: float) -> dict[str, Any] | None:
        if self.overflowed:
            raise OverflowError("subscriber too slow")
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def close(self) -> None:
        self.bus._remove(self.session_id, self)


class InProcessBus:
    """Single-replica fan-out (development and tests)."""

    def __init__(self) -> None:
        self._subs: dict[str, list[_LocalSubscription]] = {}
        self._lock = threading.Lock()

    def publish(self, session_id: str, message: dict[str, Any]) -> None:
        with self._lock:
            subs = list(self._subs.get(session_id, ()))
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.offer, message)
            except RuntimeError:
                pass

    async def subscribe(self, session_id: str) -> _LocalSubscription:
        sub = _LocalSubscription(self, session_id, asyncio.get_running_loop())
        with self._lock:
            self._subs.setdefault(session_id, []).append(sub)
        return sub

    def _remove(self, session_id: str, sub: _LocalSubscription) -> None:
        with self._lock:
            remaining = [item for item in self._subs.get(session_id, []) if item is not sub]
            if remaining:
                self._subs[session_id] = remaining
            else:
                self._subs.pop(session_id, None)

    async def aclose(self) -> None:
        return None


class _RedisSubscription:
    def __init__(self, pubsub) -> None:  # noqa: ANN001
        self.pubsub = pubsub

    async def get(self, timeout: float) -> dict[str, Any] | None:
        message = await self.pubsub.get_message(ignore_subscribe_messages=True, timeout=timeout)
        if message is None:
            return None
        return json.loads(message["data"])

    async def close(self) -> None:
        try:
            await self.pubsub.aclose()
        except Exception:
            pass


class RedisBus:
    """Cross-replica fan-out via Redis pub/sub."""

    def __init__(self, url: str) -> None:
        import redis
        import redis.asyncio as aredis
        self.sync = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
        self.url, self._aredis = url, aredis
        self._async_client = None

    @staticmethod
    def channel(session_id: str) -> str:
        return f"flow:rt:{session_id}"

    def publish(self, session_id: str, message: dict[str, Any]) -> None:
        try:
            self.sync.publish(self.channel(session_id), json.dumps(message, separators=(",", ":")))
        except Exception:
            pass  # subscribers recover via last_sequence replay from the database

    async def subscribe(self, session_id: str) -> _RedisSubscription:
        if self._async_client is None:
            self._async_client = self._aredis.Redis.from_url(self.url)
        pubsub = self._async_client.pubsub()
        await pubsub.subscribe(self.channel(session_id))
        return _RedisSubscription(pubsub)

    async def aclose(self) -> None:
        if self._async_client is not None:
            await self._async_client.aclose()
        self.sync.close()

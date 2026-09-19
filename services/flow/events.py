"""Persisted, replayable FLOW events plus a small local pub/sub bridge."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .models import iso, utc_now


@dataclass(frozen=True, slots=True)
class FlowEvent:
    event_id: str
    type: str
    session_id: str
    timestamp: datetime
    sequence: int
    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "type": self.type, "session_id": self.session_id,
                "timestamp": iso(self.timestamp), "sequence": self.sequence, "data": self.data}


class EventHub:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue[FlowEvent]]]] = {}

    def subscribe(self, session_id: str) -> tuple[asyncio.Queue[FlowEvent], callable]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[FlowEvent] = asyncio.Queue()
        self._subscribers.setdefault(session_id, []).append((loop, queue))

        def close() -> None:
            subscribers = self._subscribers.get(session_id, [])
            self._subscribers[session_id] = [item for item in subscribers if item[1] is not queue]
            if not self._subscribers[session_id]:
                self._subscribers.pop(session_id, None)
        return queue, close

    def publish(self, event: FlowEvent) -> None:
        for loop, queue in tuple(self._subscribers.get(event.session_id, [])):
            loop.call_soon_threadsafe(queue.put_nowait, event)


def event(event_type: str, session_id: str, sequence: int, data: dict[str, Any], event_id: str,
          timestamp: datetime | None = None) -> FlowEvent:
    return FlowEvent(event_id, event_type, session_id, timestamp or utc_now(), sequence, data)

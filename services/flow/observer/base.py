"""Observer protocol. Native capture is deliberately isolated from FLOW logic."""

from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Protocol

from .frame import CapturedFrame, CaptureReason


@dataclass(frozen=True, slots=True)
class ObserverContext:
    application: str | None = None
    bundle_id: str | None = None
    window_title: str | None = None
    display_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DesktopObserver(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def snapshot(self, reason: CaptureReason = CaptureReason.PERIODIC) -> CapturedFrame | None: ...
    async def active_context(self) -> ObserverContext: ...


class UnsupportedObserver:
    async def start(self) -> None:
        raise RuntimeError("macOS desktop observation is available only on macOS")

    async def stop(self) -> None:
        return None

    async def snapshot(self, reason=CaptureReason.PERIODIC):
        raise RuntimeError("macOS desktop observation is available only on macOS")

    async def active_context(self) -> ObserverContext:
        return ObserverContext()


class MockDesktopObserver:
    """Replayable observer for tests; never accesses the real desktop."""

    def __init__(self, frames: list[CapturedFrame] | None = None) -> None:
        self.frames = list(frames or [])
        self.started = False
        self._index = 0

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def snapshot(self, reason=CaptureReason.PERIODIC) -> CapturedFrame | None:
        if not self.started or self._index >= len(self.frames):
            return None
        frame = self.frames[self._index]
        self._index += 1
        return frame

    async def active_context(self) -> ObserverContext:
        if self._index < len(self.frames):
            frame = self.frames[self._index]
            return ObserverContext(frame.application, frame.bundle_id, frame.window_title,
                                   frame.display_id, frame.timestamp)
        return ObserverContext()


def create_observer() -> DesktopObserver:
    if platform.system() == "Darwin":
        from .macos import MacOSObserver
        return MacOSObserver()
    return UnsupportedObserver()

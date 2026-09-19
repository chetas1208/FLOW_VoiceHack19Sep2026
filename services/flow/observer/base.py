"""Observer protocol. Native capture is deliberately isolated from FLOW logic."""

from __future__ import annotations

import asyncio
import os
import platform
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncIterator, Protocol

from .frame import CapturedFrame, CaptureReason

if TYPE_CHECKING:
    from ..privacy.policy import PrivacyPolicy


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


def create_observer(privacy: "PrivacyPolicy | None" = None) -> DesktopObserver:
    """Select an observer. ``FLOW_OBSERVER=replay`` (+ ``FLOW_OBSERVER_SCRIPT=path.json``) replays a
    scripted, synthetic desktop for tests and demos; otherwise macOS uses the native observer."""
    mode = os.getenv("FLOW_OBSERVER", "auto").strip().lower()
    if mode == "replay":
        from .replay import load_replay_frames
        return MockDesktopObserver(load_replay_frames(os.getenv("FLOW_OBSERVER_SCRIPT")))
    if mode not in {"auto", "macos", ""}:
        raise ValueError(f"unknown FLOW_OBSERVER {mode!r}; use auto, macos or replay")
    if platform.system() == "Darwin":
        from ..config import config_dir
        from ..privacy.policy import PrivacyPolicy
        from .macos import MacOSObserver
        return MacOSObserver(privacy=privacy or PrivacyPolicy.load(config_dir() / "privacy.json"))
    return UnsupportedObserver()

"""Native bridge boundary for ScreenCaptureKit.

The Swift helper is intentionally not imported on non-macOS hosts. This Python
adapter provides a deterministic permission/error contract for the daemon.
"""

from __future__ import annotations

import platform
from datetime import datetime, timezone

from ..base import ObserverContext
from ..frame import CapturedFrame, CaptureReason


class MacOSObserver:
    def __init__(self, helper_path=None) -> None:
        self.helper_path = helper_path
        self.started = False

    async def start(self) -> None:
        if platform.system() != "Darwin":
            raise RuntimeError("ScreenCaptureKit requires macOS")
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def active_context(self) -> ObserverContext:
        if not self.started:
            raise RuntimeError("observer is not running")
        raise RuntimeError("ScreenCaptureKit helper is not installed")

    async def snapshot(self, reason: CaptureReason = CaptureReason.PERIODIC) -> CapturedFrame:
        if not self.started:
            raise RuntimeError("observer is not running")
        raise RuntimeError("ScreenCaptureKit helper is not installed")

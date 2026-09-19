"""macOS observer: Swift ScreenCaptureKit helper first, ``screencapture``/``lsappinfo`` fallback.

Frames are held in memory only. The helper streams bytes over a pipe; the CLI fallback uses a
private temp file that is unlinked immediately. Excluded applications are checked BEFORE any
capture call, so their pixels are never taken.

STATUS: IMPLEMENTED_ENVIRONMENT_UNVERIFIED (exercised on Linux only with mocked subprocesses).
"""

from __future__ import annotations

import asyncio
import os
import platform
from datetime import datetime, timezone
from typing import Callable, Mapping

from ...privacy.policy import PrivacyPolicy
from ..base import ObserverContext
from ..frame import CapturedFrame, CaptureReason
from . import cli_capture
from .active_window import context_from_cli, context_from_helper
from .displays import DisplayInfo, list_displays
from .errors import (CaptureFailed, HelperMissing, HelperUnsupported, ObserverError, ObserverNotRunning,
                     PermissionDenied)
from .helper import Helper, find_helper
from .permissions import PermissionStatus, screen_recording_status
from .runner import Runner, run


def _screencapture_available() -> bool:
    return os.path.exists(cli_capture.SCREENCAPTURE)


class MacOSObserver:
    def __init__(self, helper_path: str | None = None, *, privacy: PrivacyPolicy | None = None,
                 max_dim: int = 1280, image_format: str = "jpeg", call_timeout: float = 10.0,
                 capture_timeout: float = 20.0, runner: Runner = run,
                 system: Callable[[], str] = platform.system, allow_fallback: bool = True,
                 env: Mapping[str, str] | None = None) -> None:
        self.helper_path = helper_path
        self.privacy = privacy
        self.max_dim, self.image_format = max_dim, image_format
        self.call_timeout, self.capture_timeout = call_timeout, capture_timeout
        self.runner, self._system, self.allow_fallback = runner, system, allow_fallback
        self._env = env
        self.backend: str | None = None  # "helper" | "screencapture"
        self.permission: PermissionStatus | None = None
        self.started = False
        self._helper: Helper | None = None
        self._lock = asyncio.Lock()

    # -- lifecycle ---------------------------------------------------------------------------
    async def start(self) -> None:
        if self._system() != "Darwin":
            raise ObserverError("ScreenCaptureKit requires macOS")
        path = find_helper(self.helper_path, self._env)
        self._helper = None
        if path:
            candidate = Helper(path, self.runner, self.call_timeout)
            try:
                await asyncio.to_thread(candidate.version)
                self._helper = candidate
            except ObserverError:
                if not self.allow_fallback:
                    raise
        if self._helper is not None:
            self.backend = "helper"
        elif self.allow_fallback and _screencapture_available():
            self.backend = "screencapture"
        else:
            raise HelperMissing("no usable capture backend: helper not found and screencapture unavailable",
                                hint="run scripts/build-macos-helper.sh and set FLOW_MACOS_HELPER")
        self.permission = await asyncio.to_thread(screen_recording_status, path, self.runner, self._system)
        self.started = True

    async def stop(self) -> None:
        self.started = False

    def _require_started(self) -> None:
        if not self.started:
            raise ObserverNotRunning("observer is not running")

    # -- context -----------------------------------------------------------------------------
    async def active_context(self) -> ObserverContext:
        self._require_started()
        if self._helper is not None:
            context = context_from_helper(await asyncio.to_thread(self._helper.call, "context"))
        else:
            context = await asyncio.to_thread(context_from_cli, self.runner)
        if self._is_excluded(context):
            # Excluded apps are metadata-only: never surface their window titles.
            return ObserverContext(context.application, context.bundle_id, None, context.display_id,
                                   context.timestamp)
        return context

    def _is_excluded(self, context: ObserverContext) -> bool:
        return bool(self.privacy and (self.privacy.is_excluded(context.application)
                                       or self.privacy.is_excluded(context.bundle_id)))

    async def displays(self) -> list[DisplayInfo]:
        self._require_started()
        return await asyncio.to_thread(list_displays, self._helper.path if self._helper else None,
                                       self.runner, self._system)

    # -- capture -----------------------------------------------------------------------------
    async def snapshot(self, reason: CaptureReason = CaptureReason.PERIODIC) -> CapturedFrame | None:
        self._require_started()
        async with self._lock:
            context = await self.active_context()
            if self._is_excluded(context):
                return None  # decided before any pixels are taken
            image, width, height, display_id = await self._capture(context)
            return CapturedFrame(datetime.now(timezone.utc), display_id, width, height, self.image_format,
                                 context.application, context.bundle_id, context.window_title, image, reason)

    async def _capture(self, context: ObserverContext) -> tuple[bytes, int, int, str | None]:
        if self._helper is not None:
            try:
                meta, data = await asyncio.to_thread(
                    self._helper.capture, context.display_id or "active", self.max_dim, self.image_format,
                    self.capture_timeout)
                return data, int(meta["width"]), int(meta["height"]), str(meta.get("display_id", "")) or None
            except HelperUnsupported:
                if not self.allow_fallback:
                    raise
                self._helper, self.backend = None, "screencapture"  # macOS 13: no SCScreenshotManager
        if self.permission is None or self.permission.screen_recording != "granted":
            self.permission = await asyncio.to_thread(screen_recording_status, None, self.runner, self._system)
            if self.permission.screen_recording == "denied":
                raise PermissionDenied("Screen Recording permission is not granted",
                                       hint="run: flow permissions open")
        try:
            data, width, height = await asyncio.to_thread(
                cli_capture.capture_main_display, self.image_format, self.max_dim, self.capture_timeout, self.runner)
        except CaptureFailed:
            state = (await asyncio.to_thread(screen_recording_status, None, self.runner, self._system)).screen_recording
            if state == "denied":
                raise PermissionDenied("Screen Recording permission is not granted",
                                       hint="run: flow permissions open") from None
            raise
        return data, width, height, "1"

"""Real Screen Recording status: Swift helper first, in-process CoreGraphics call second."""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Callable

from .errors import ObserverError
from .helper import Helper, find_helper
from .runner import Runner, run

SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
_CG_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"


@dataclass(frozen=True, slots=True)
class PermissionStatus:
    screen_recording: str  # granted | denied | unknown | unavailable
    accessibility: str = "not_required"
    microphone: str = "optional"
    notifications: str = "optional"
    source: str = "none"  # helper | coregraphics | none


def _coregraphics(symbol: str) -> bool | None:
    """Call a bool-returning CoreGraphics permission function via ctypes (macOS only)."""
    try:
        import ctypes
        library = ctypes.CDLL(_CG_PATH)
        function = getattr(library, symbol)
        function.restype = ctypes.c_bool
        function.argtypes = []
        return bool(function())
    except (OSError, AttributeError, ImportError):
        return None


def screen_recording_status(helper_path: str | None = None, runner: Runner = run,
                            system: Callable[[], str] = platform.system) -> PermissionStatus:
    if system() != "Darwin":
        return PermissionStatus("unavailable")
    path = find_helper(helper_path)
    if path:
        try:
            state = Helper(path, runner).call("permission").get("screen_recording")
            if state in ("granted", "denied"):
                return PermissionStatus(state, source="helper")
        except ObserverError:
            pass
    granted = _coregraphics("CGPreflightScreenCaptureAccess")
    if granted is None:
        return PermissionStatus("unknown")
    return PermissionStatus("granted" if granted else "denied", source="coregraphics")


def request_screen_recording(helper_path: str | None = None, runner: Runner = run,
                             system: Callable[[], str] = platform.system) -> PermissionStatus:
    """Trigger the macOS consent prompt (only shown once per binary), then re-read the state."""
    if system() != "Darwin":
        return PermissionStatus("unavailable")
    path = find_helper(helper_path)
    if path:
        try:
            state = Helper(path, runner, timeout=60).call("request-permission", timeout=60).get("screen_recording")
            if state in ("granted", "denied"):
                return PermissionStatus(state, source="helper")
        except ObserverError:
            pass
    granted = _coregraphics("CGRequestScreenCaptureAccess")
    if granted is None:
        return PermissionStatus("unknown")
    return PermissionStatus("granted" if granted else "denied", source="coregraphics")


def open_screen_recording_settings(runner: Runner = run,
                                   system: Callable[[], str] = platform.system) -> bool:
    if system() != "Darwin":
        return False
    try:
        return runner(["/usr/bin/open", SETTINGS_URL], 10).returncode == 0
    except ObserverError:
        return False

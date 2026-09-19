"""Permission status contract; native implementation is only meaningful on macOS."""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PermissionStatus:
    screen_recording: str
    accessibility: str = "not_required"
    microphone: str = "optional"
    notifications: str = "optional"


def screen_recording_status() -> PermissionStatus:
    if platform.system() != "Darwin":
        return PermissionStatus("unavailable")
    return PermissionStatus("unknown")


def open_screen_recording_settings() -> None:
    if platform.system() == "Darwin":
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"], check=False)

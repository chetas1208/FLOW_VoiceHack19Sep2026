"""Frontmost-window metadata boundary for the native macOS helper."""

from __future__ import annotations

import platform

from ..base import ObserverContext


async def active_window() -> ObserverContext:
    if platform.system() != "Darwin":
        raise RuntimeError("active-window detection requires macOS")
    raise RuntimeError("native frontmost-window bridge is not installed")

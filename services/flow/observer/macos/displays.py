"""Display discovery boundary; capture should target the active display only."""

from __future__ import annotations

import platform


async def displays() -> list[dict[str, str]]:
    if platform.system() != "Darwin":
        raise RuntimeError("display discovery requires macOS")
    raise RuntimeError("native display bridge is not installed")

"""Display discovery. The helper is authoritative; the CLI fallback can only see the main display."""

from __future__ import annotations

import asyncio
import platform
from dataclasses import dataclass
from typing import Any, Callable

from .errors import ObserverError
from .helper import Helper, find_helper
from .runner import Runner, run


@dataclass(frozen=True, slots=True)
class DisplayInfo:
    id: str
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    is_main: bool = False
    scale: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "width": self.width, "height": self.height, "is_main": self.is_main,
                "scale": self.scale}


def parse_displays(payload: dict[str, Any]) -> list[DisplayInfo]:
    result = []
    for item in payload.get("displays", []):
        frame = item.get("frame") or {}
        result.append(DisplayInfo(str(item["id"]), float(frame.get("x", 0)), float(frame.get("y", 0)),
                                  float(frame.get("width", 0)), float(frame.get("height", 0)),
                                  bool(item.get("isMain", item.get("is_main", False))),
                                  float(item.get("scale", 1.0))))
    return result


def list_displays(helper_path: str | None = None, runner: Runner = run,
                  system: Callable[[], str] = platform.system) -> list[DisplayInfo]:
    if system() != "Darwin":
        raise ObserverError("display discovery requires macOS")
    path = find_helper(helper_path)
    if path is None:
        # Without the helper only the main display can be targeted (screencapture -D 1).
        return [DisplayInfo("1", is_main=True)]
    return parse_displays(Helper(path, runner).call("displays"))


async def displays(helper_path: str | None = None) -> list[DisplayInfo]:
    return await asyncio.to_thread(list_displays, helper_path)

"""Scripted replay observer input (FLOW_OBSERVER=replay) for tests and demos; never touches a desktop.

Script format (JSON): ``{"frames": [{"application": "Editor", "bundle_id": "x", "window_title": "t",
"display_id": "1", "offset_seconds": 0, "text": "pixels stand-in", "image_base64": "...",
"width": 100, "height": 80}]}`` or a bare list of frames. Frames carry only synthetic bytes.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .frame import CapturedFrame, CaptureReason

DEFAULT_SCRIPT: list[dict[str, Any]] = [
    {"application": "Editor", "window_title": "auth.py", "offset_seconds": 0},
    {"application": "Docs", "window_title": "JWT reference", "offset_seconds": 30},
    {"application": "Editor", "window_title": "auth.py", "offset_seconds": 60},
    {"application": "Social", "window_title": "Feed", "offset_seconds": 90},
    {"application": "Social", "window_title": "Feed", "offset_seconds": 120},
    {"application": "Editor", "window_title": "auth.py", "offset_seconds": 150},
]


class ReplayScriptError(ValueError):
    pass


def frames_from_script(script: Any, start: datetime | None = None) -> list[CapturedFrame]:
    items = script.get("frames") if isinstance(script, dict) else script
    if not isinstance(items, list):
        raise ReplayScriptError("replay script must be a list or an object with a 'frames' list")
    start = start or datetime.now(timezone.utc)
    frames = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ReplayScriptError(f"frame {index} must be an object")
        raw = item.get("image_base64")
        try:
            image = base64.b64decode(raw, validate=True) if raw else \
                str(item.get("text", f"replay-frame-{index}")).encode()
        except (binascii.Error, ValueError) as exc:
            raise ReplayScriptError(f"frame {index}: invalid image_base64") from exc
        try:
            when = start + timedelta(seconds=float(item.get("offset_seconds", index * 10)))
            width, height = int(item.get("width", 0)), int(item.get("height", 0))
        except (TypeError, ValueError) as exc:
            raise ReplayScriptError(f"frame {index}: numeric field is invalid") from exc
        frames.append(CapturedFrame(
            when, item.get("display_id"), width, height, "replay", item.get("application"),
            item.get("bundle_id"), item.get("window_title"), image,
            CaptureReason(item.get("reason", "periodic"))))
    return frames


def load_replay_frames(path: str | Path | None) -> list[CapturedFrame]:
    if not path:
        return frames_from_script(DEFAULT_SCRIPT)
    try:
        return frames_from_script(json.loads(Path(path).read_text()))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayScriptError(f"cannot read replay script {path}: {exc}") from exc

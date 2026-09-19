"""Ephemeral frame metadata. Pixel bytes are never persisted by this module."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class CaptureReason(str, Enum):
    PERIODIC = "periodic"
    CONTEXT_SWITCH = "context_switch"
    DRIFT_PROBE = "drift_probe"
    MANUAL = "manual"
    RECOVERY_PROBE = "recovery_probe"


@dataclass(slots=True)
class CapturedFrame:
    timestamp: datetime
    display_id: str | None = None
    width: int = 0
    height: int = 0
    pixel_format: str = "unknown"
    application: str | None = None
    bundle_id: str | None = None
    window_title: str | None = None
    image_bytes: bytes | None = None
    reason: CaptureReason = CaptureReason.PERIODIC
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.fingerprint is None and self.image_bytes:
            self.fingerprint = hashlib.sha256(self.image_bytes).hexdigest()

    def discard_pixels(self) -> None:
        self.image_bytes = None

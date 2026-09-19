"""Platform-neutral idle state classification from activity timestamps."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum


class IdleState(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    AWAY = "away"


class IdleDetector:
    def __init__(self, idle_after: float = 60.0, away_after: float = 300.0) -> None:
        if not 0 < idle_after < away_after:
            raise ValueError("idle_after must be positive and less than away_after")
        self.idle_after, self.away_after = idle_after, away_after

    def state(self, last_activity: datetime, now: datetime | None = None) -> IdleState:
        now = now or datetime.now(timezone.utc)
        elapsed = max(0.0, (now - last_activity).total_seconds())
        if elapsed >= self.away_after: return IdleState.AWAY
        if elapsed >= self.idle_after: return IdleState.IDLE
        return IdleState.ACTIVE

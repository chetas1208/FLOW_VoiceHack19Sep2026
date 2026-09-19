"""Typed FLOW domain objects and JSON-safe serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ActivityCategory(str, Enum):
    CORE_TASK = "core_task"
    SUPPORTING_TASK = "supporting_task"
    NEUTRAL = "neutral"
    DISTRACTION = "distraction"
    UNKNOWN = "unknown"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class InterventionChannel(str, Enum):
    VOICE = "voice"
    CLI = "cli"
    WEB = "web"


class InterventionStatus(str, Enum):
    PROPOSED = "proposed"
    DELIVERED = "delivered"
    DISMISSED = "dismissed"
    FAILED = "failed"


class DriftState(str, Enum):
    FOCUSED = "focused"
    MIXED = "mixed"
    DRIFTING = "drifting"
    SUSTAINED_DRIFT = "sustained_drift"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return ensure_utc(value).isoformat()


@dataclass(slots=True)
class WorkSession:
    id: str
    goal: str
    status: SessionStatus
    started_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "goal": self.goal, "status": self.status.value,
                "started_at": iso(self.started_at), "updated_at": iso(self.updated_at),
                "ended_at": iso(self.ended_at) if self.ended_at else None,
                "created_by": self.created_by, "metadata": self.metadata}


@dataclass(slots=True)
class Observation:
    id: str
    session_id: str
    timestamp: datetime
    source: str
    app_name: str | None = None
    window_title: str | None = None
    activity_summary: str | None = None
    category: ActivityCategory = ActivityCategory.UNKNOWN
    goal_alignment: float | None = None
    progress_signal: float | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "session_id": self.session_id, "timestamp": iso(self.timestamp),
                "source": self.source, "app_name": self.app_name, "window_title": self.window_title,
                "activity_summary": self.activity_summary, "category": self.category.value,
                "goal_alignment": self.goal_alignment, "progress_signal": self.progress_signal,
                "confidence": self.confidence, "metadata": self.metadata}


@dataclass(slots=True)
class Intervention:
    id: str
    session_id: str
    timestamp: datetime
    reason: str
    channel: InterventionChannel
    message: str | None = None
    status: InterventionStatus = InterventionStatus.PROPOSED
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "session_id": self.session_id, "timestamp": iso(self.timestamp),
                "reason": self.reason, "channel": self.channel.value, "message": self.message,
                "status": self.status.value, "metadata": self.metadata}


@dataclass(slots=True)
class SessionMetrics:
    goal_alignment: float | None = None
    focus_continuity: float | None = None
    context_stability: float | None = None
    progress: float | None = None
    session_score: float | None = None
    aligned_seconds: float = 0.0
    supporting_seconds: float = 0.0
    neutral_seconds: float = 0.0
    distraction_seconds: float = 0.0
    unknown_seconds: float = 0.0
    context_switches: int = 0
    intervention_count: int = 0
    coverage: float = 0.0
    confidence: float = 0.0
    drift_state: DriftState = DriftState.UNKNOWN
    longest_focus_block: float = 0.0
    mean_focus_block: float = 0.0
    focus_blocks: int = 0

    def to_dict(self) -> dict[str, Any]:
        result = {name: getattr(self, name) for name in self.__dataclass_fields__}
        result["drift_state"] = self.drift_state.value
        return result

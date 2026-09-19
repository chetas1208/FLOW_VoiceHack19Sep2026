"""Strict wire schemas. Unknown fields are rejected so raw pixels can never ride along."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ..flow.models import ActivityCategory, InterventionChannel, InterventionStatus

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_\-]{8,80}$")]
Short = Annotated[str, StringConstraints(max_length=200)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]
MIN_TIME = datetime(2020, 1, 1, tzinfo=timezone.utc)

EVENT_TYPES = Literal[
    "session.started", "session.paused", "session.resumed", "session.completed", "observation.created",
    "segment.updated", "metrics.updated", "drift.changed", "drift.entered", "drift.cleared", "blocker.changed",
    "intervention.proposed", "intervention.delivered", "efficiency.updated", "observer.health",
    "recommendation.created", "recommendation.updated", "goal.updated", "voice.state", "subtask.updated",
    "task.created", "task.planning", "task.approval_requested", "task.approval_resolved", "task.running",
    "task.tool_started", "task.tool_completed", "task.completed", "task.failed", "task.cancelled",
    "command.acked", "presence.changed", "chat.message"]

FORBIDDEN_KEYS = {"image", "image_bytes", "image_base64", "screenshot", "frame", "pixels", "raw_frame"}
MAX_EVENT_BYTES = 16_384


def _aware(value: datetime) -> datetime:
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    if value < MIN_TIME or value > datetime.now(timezone.utc) + timedelta(days=1):
        raise ValueError("timestamp outside the accepted range")
    return value


def _scan(value: Any, depth: int = 0) -> None:
    if depth > 8:
        raise ValueError("payload nesting too deep")
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"field {key!r} is not accepted; raw screen content is never uploaded")
            _scan(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _scan(item, depth + 1)


def bounded_json(value: dict[str, Any], limit: int) -> dict[str, Any]:
    _scan(value)
    if len(json.dumps(value, separators=(",", ":"), default=str)) > limit:
        raise ValueError(f"payload exceeds {limit} bytes")
    return value


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DeviceInfo(Strict):
    device_id: Annotated[str, StringConstraints(pattern=r"^dev_[A-Za-z0-9_\-]{8,60}$")]
    name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    os: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    architecture: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    flow_version: Annotated[str, StringConstraints(min_length=1, max_length=40)]


class AuthRequestCreate(Strict):
    device: DeviceInfo
    code_challenge: Annotated[str, StringConstraints(min_length=43, max_length=128)]
    code_challenge_method: Literal["S256"] = "S256"
    state: Annotated[str, StringConstraints(min_length=16, max_length=200)]
    nonce: Annotated[str, StringConstraints(min_length=16, max_length=200)]


class AuthTokenRequest(Strict):
    auth_request_id: Annotated[str, StringConstraints(min_length=8, max_length=64)]
    device_id: Annotated[str, StringConstraints(min_length=8, max_length=64)]
    code_verifier: Annotated[str, StringConstraints(min_length=43, max_length=128)]


class RefreshRequest(Strict):
    refresh_token: Annotated[str, StringConstraints(min_length=20, max_length=200)]
    device_id: Annotated[str, StringConstraints(min_length=8, max_length=64)]


class LogoutRequest(Strict):
    refresh_token: Annotated[str, StringConstraints(min_length=20, max_length=200)]


class DevLogin(Strict):
    email: Annotated[str, StringConstraints(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+$")]


class SessionCreate(Strict):
    id: Identifier
    goal: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    started_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    _time = field_validator("started_at")(_aware)

    @field_validator("metadata")
    @classmethod
    def _meta(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_json(value, 4096)


class ObservationIn(Strict):
    id: Identifier
    sequence: Annotated[int, Field(ge=1, le=10_000_000)]
    timestamp: datetime
    activity: Annotated[str, StringConstraints(max_length=1000)] | None = None
    category: ActivityCategory
    goal_alignment: Unit | None = None
    progress_signal: Unit | None = None
    confidence: Unit | None = None
    task_phase: Annotated[str, StringConstraints(max_length=40)] | None = None
    application: Short | None = None
    activity_type: Annotated[str, StringConstraints(max_length=40)] | None = None
    source: Annotated[str, StringConstraints(min_length=1, max_length=40)] = "observer"
    blocker: Short | None = None

    _time = field_validator("timestamp")(_aware)

    def row(self) -> dict[str, Any]:
        data = self.model_dump(mode="python")
        data["client_timestamp"] = data.pop("timestamp")
        data["category"] = self.category.value
        return data


class ObservationBatch(Strict):
    observations: Annotated[list[ObservationIn], Field(min_length=1, max_length=100)]


class EventIn(Strict):
    id: Identifier
    sequence: Annotated[int, Field(ge=1, le=10_000_000)]
    type: EVENT_TYPES
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)

    _time = field_validator("timestamp")(_aware)

    @field_validator("data")
    @classmethod
    def _data(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_json(value, MAX_EVENT_BYTES)

    def row(self) -> dict[str, Any]:
        return {"event_id": self.id, "sequence": self.sequence, "type": self.type,
                "client_timestamp": self.timestamp, "data": self.data}


class EventBatch(Strict):
    events: Annotated[list[EventIn], Field(min_length=1, max_length=100)]


class InterventionIn(Strict):
    id: Identifier
    timestamp: datetime
    reason: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    channel: InterventionChannel
    message: Annotated[str, StringConstraints(max_length=1000)] | None = None
    status: InterventionStatus
    metadata: dict[str, Any] = Field(default_factory=dict)

    _time = field_validator("timestamp")(_aware)

    @field_validator("metadata")
    @classmethod
    def _meta(cls, value: dict[str, Any]) -> dict[str, Any]:
        return bounded_json(value, 4096)

    def row(self) -> dict[str, Any]:
        return {"id": self.id, "timestamp": self.timestamp, "reason": self.reason, "channel": self.channel.value,
                "message": self.message, "status": self.status.value, "metadata": self.metadata}


class SegmentIn(Strict):
    id: Identifier
    start: datetime
    end: datetime
    activity: Annotated[str, StringConstraints(max_length=1000)] | None = None
    category: ActivityCategory
    application: Short | None = None
    alignment: Unit | None = None
    confidence: Unit | None = None
    observation_count: Annotated[int, Field(ge=0, le=100_000)] = 0
    revision: Annotated[int, Field(ge=1, le=1_000_000)] = 1

    _s = field_validator("start")(_aware)
    _e = field_validator("end")(_aware)

    def row(self) -> dict[str, Any]:
        return {"id": self.id, "start_at": self.start, "end_at": self.end, "activity": self.activity,
                "category": self.category.value, "application": self.application, "alignment": self.alignment,
                "confidence": self.confidence, "observation_count": self.observation_count, "revision": self.revision}


class SummaryIn(Strict):
    schema_version: Annotated[int, Field(ge=1, le=100)] = 1
    goal: Annotated[str, StringConstraints(max_length=2000)]
    duration_seconds: Annotated[float, Field(ge=0)]
    active_seconds: Annotated[float, Field(ge=0)] = 0
    away_seconds: Annotated[float, Field(ge=0)] = 0
    goal_alignment: Unit | None = None
    focus_continuity: Unit | None = None
    context_stability: Unit | None = None
    progress: Unit | None = None
    session_score: Annotated[float, Field(ge=0, le=100)] | None = None
    coverage: Unit = 0
    confidence: Unit = 0
    segments: Annotated[list[dict[str, Any]], Field(max_length=2000)] = Field(default_factory=list)
    blockers: Annotated[list[dict[str, Any]], Field(max_length=200)] = Field(default_factory=list)
    drift_periods: Annotated[list[dict[str, Any]], Field(max_length=500)] = Field(default_factory=list)
    interventions: Annotated[list[dict[str, Any]], Field(max_length=500)] = Field(default_factory=list)
    recommendations: Annotated[list[Any], Field(max_length=100)] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("segments", "blockers", "drift_periods", "interventions", "recommendations", "extra")
    @classmethod
    def _scan_nested(cls, value: Any) -> Any:
        _scan(value)
        if len(json.dumps(value, default=str)) > 200_000:
            raise ValueError("summary section too large")
        return value


class StopRequest(Strict):
    ended_at: datetime | None = None
    summary: SummaryIn | None = None

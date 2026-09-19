"""Shared domain models for the remote operating layer.

These are the single definition used by the local daemon, the CLI, and the cloud API. All wire
JSON is produced by ``to_dict`` and consumed by ``from_dict``; times are ISO-8601 UTC strings.
"""

from __future__ import annotations

import secrets
import types
import typing
from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from .models import iso, utc_now


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(10)}"


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _coerce(hint: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = typing.get_origin(hint)
    if origin in (typing.Union, types.UnionType):
        options = [a for a in typing.get_args(hint) if a is not type(None)]
        return _coerce(options[0], value) if len(options) == 1 else value
    if origin in (list, tuple):
        (inner,) = typing.get_args(hint)[:1] or (Any,)
        return [_coerce(inner, item) for item in value]
    if isinstance(hint, type):
        if issubclass(hint, Enum):
            return hint(value)
        if hint is datetime:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        if hasattr(hint, "from_dict") and isinstance(value, dict):
            return hint.from_dict(value)
    return value


class Model:
    def to_dict(self) -> dict[str, Any]:
        return {f.name: _plain(getattr(self, f.name)) for f in fields(self)}  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        hints = typing.get_type_hints(cls)
        known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        return cls(**{key: _coerce(hints[key], value) for key, value in data.items() if key in known})


# ---- sessions ----------------------------------------------------------------------------------
class RuntimeStatus(str, Enum):
    STARTING = "starting"
    ACTIVE = "active"
    PAUSED = "paused"
    WAITING_FOR_USER = "waiting_for_user"
    EXECUTING_DELEGATED_TASK = "executing_delegated_task"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"
    OFFLINE = "offline"


# ---- commands ----------------------------------------------------------------------------------
class CommandType(str, Enum):
    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"
    UPDATE_GOAL = "UPDATE_GOAL"
    REQUEST_STATUS = "REQUEST_STATUS"
    MUTE_VOICE = "MUTE_VOICE"
    UNMUTE_VOICE = "UNMUTE_VOICE"
    REQUEST_SUMMARY = "REQUEST_SUMMARY"
    ADD_TASK = "ADD_TASK"
    CANCEL_TASK = "CANCEL_TASK"
    APPROVE_ACTION = "APPROVE_ACTION"
    DENY_ACTION = "DENY_ACTION"
    EXECUTE_RECOMMENDATION = "EXECUTE_RECOMMENDATION"
    ASK = "ASK"
    DISMISS_RECOMMENDATION = "DISMISS_RECOMMENDATION"
    FEEDBACK_RECOMMENDATION = "FEEDBACK_RECOMMENDATION"
    SET_PERMISSION_POLICY = "SET_PERMISSION_POLICY"
    UPDATE_SUBTASKS = "UPDATE_SUBTASKS"


class CommandSource(str, Enum):
    CLI = "cli"
    WEB = "web"
    SYSTEM = "system"
    VOICE_AGENT = "voice_agent"


class CommandStatus(str, Enum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    DENIED = "denied"


TERMINAL_COMMAND_STATUSES = {CommandStatus.SUCCEEDED, CommandStatus.FAILED, CommandStatus.EXPIRED,
                             CommandStatus.CANCELLED, CommandStatus.DENIED}

# Commands that may be queued while the device is offline; everything else is rejected with 409.
OFFLINE_QUEUEABLE = {CommandType.STOP, CommandType.PAUSE, CommandType.MUTE_VOICE, CommandType.UNMUTE_VOICE}
# Commands that need no session_id (they act on a device).
DEVICE_COMMANDS = {CommandType.START}

COMMAND_TTL_SECONDS = {
    CommandType.START: 300, CommandType.REQUEST_STATUS: 30, CommandType.REQUEST_SUMMARY: 60, CommandType.ASK: 120,
    CommandType.APPROVE_ACTION: 600, CommandType.DENY_ACTION: 600, CommandType.EXECUTE_RECOMMENDATION: 600,
    CommandType.ADD_TASK: 600, CommandType.CANCEL_TASK: 600, CommandType.UPDATE_GOAL: 600,
    CommandType.STOP: 3600, CommandType.PAUSE: 3600, CommandType.RESUME: 600,
    CommandType.MUTE_VOICE: 3600, CommandType.UNMUTE_VOICE: 3600,
    CommandType.DISMISS_RECOMMENDATION: 600, CommandType.FEEDBACK_RECOMMENDATION: 600,
    CommandType.SET_PERMISSION_POLICY: 600, CommandType.UPDATE_SUBTASKS: 600}


def default_expiry(command_type: CommandType, now: datetime | None = None) -> datetime:
    return (now or utc_now()) + timedelta(seconds=COMMAND_TTL_SECONDS[command_type])


@dataclass(slots=True)
class SessionCommand(Model):
    command_id: str
    type: CommandType
    user_id: str
    device_id: str
    source: CommandSource
    session_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    status: CommandStatus = CommandStatus.QUEUED
    result: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None

    def is_expired(self, now: datetime | None = None) -> bool:
        return self.expires_at is not None and (now or utc_now()) >= self.expires_at


# ---- permissions / tasks / approvals -----------------------------------------------------------
class PermissionLevel(str, Enum):
    READ_ONLY = "read_only"
    SAFE_EXECUTE = "safe_execute"
    WRITE_PROJECT = "write_project"
    EXTERNAL_NETWORK = "external_network"
    DESTRUCTIVE = "destructive"


class PermissionPolicy(str, Enum):
    MANUAL = "manual"
    SAFE_AUTO = "safe_auto"
    READ_ONLY = "read_only"


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskOrigin(str, Enum):
    CLI = "cli"
    WEB = "web"
    RECOMMENDATION = "recommendation"


@dataclass(slots=True)
class DelegatedTask(Model):
    id: str
    session_id: str
    user_id: str
    device_id: str
    instruction: str
    status: TaskStatus = TaskStatus.QUEUED
    created_from: TaskOrigin = TaskOrigin.CLI
    created_at: datetime = field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    permission_level: PermissionLevel = PermissionLevel.SAFE_EXECUTE
    plan: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    evidence: list[str] = field(default_factory=list)
    error: str | None = None
    recommendation_id: str | None = None
    revision: int = 1


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(slots=True)
class ActionApproval(Model):
    id: str
    session_id: str
    task_id: str
    action: dict[str, Any]
    risk: str
    requested_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    why: str | None = None
    permission_level: PermissionLevel = PermissionLevel.SAFE_EXECUTE
    scope: str | None = None
    revision: int = 1


# ---- recommendations ---------------------------------------------------------------------------
class RecommendationType(str, Enum):
    RETURN_TO_TASK = "RETURN_TO_TASK"
    CONTINUE_CURRENT_TASK = "CONTINUE_CURRENT_TASK"
    RUN_VALIDATION = "RUN_VALIDATION"
    INVESTIGATE_ERROR = "INVESTIGATE_ERROR"
    CHECK_DOCUMENTATION = "CHECK_DOCUMENTATION"
    REVIEW_CHANGE = "REVIEW_CHANGE"
    COMPLETE_SUBTASK = "COMPLETE_SUBTASK"
    BREAK_TASK_DOWN = "BREAK_TASK_DOWN"
    CLARIFY_GOAL = "CLARIFY_GOAL"
    REDUCE_CONTEXT_SWITCHING = "REDUCE_CONTEXT_SWITCHING"
    TAKE_SHORT_BREAK = "TAKE_SHORT_BREAK"
    DELEGATE_TASK = "DELEGATE_TASK"


class ActionLevel(str, Enum):
    PASSIVE = "passive"
    SUGGEST = "suggest"
    RECOMMEND = "recommend"
    URGENT = "urgent"


class RecommendationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


@dataclass(slots=True)
class ActionRecommendation(Model):
    id: str
    session_id: str
    type: RecommendationType
    title: str
    description: str
    reason: str
    evidence: list[str]
    confidence: float
    impact_estimate: str = "medium"
    requires_user_action: bool = True
    can_delegate: bool = False
    proposed_task: str | None = None
    level: ActionLevel = ActionLevel.SUGGEST
    status: RecommendationStatus = RecommendationStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    feedback: str | None = None
    revision: int = 1


# ---- goal ---------------------------------------------------------------------------------------
class GoalState(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PARTIALLY_COMPLETE = "partially_complete"
    LIKELY_COMPLETE = "likely_complete"
    CONFIRMED_COMPLETE = "confirmed_complete"


class SubtaskStatus(str, Enum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass(slots=True)
class Subtask(Model):
    id: str
    session_id: str
    title: str
    status: SubtaskStatus = SubtaskStatus.TODO
    evidence: list[str] = field(default_factory=list)
    position: int = 0
    origin: str = "observed"
    revision: int = 1


@dataclass(slots=True)
class GoalVersion(Model):
    session_id: str
    version: int
    goal: str
    effective_at: datetime = field(default_factory=utc_now)
    source: str = "cli"
    state: GoalState = GoalState.NOT_STARTED

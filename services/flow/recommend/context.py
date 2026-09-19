"""Inputs to the recommendation engine: a read-only snapshot of what FLOW knows right now."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..models import Observation, ensure_utc
from ..remote_models import ActionRecommendation, DelegatedTask, GoalState, Subtask, TaskStatus
from ..temporal import TaskSegmenter

ACTIVE_TASK_STATUSES = frozenset({TaskStatus.QUEUED, TaskStatus.PLANNING, TaskStatus.WAITING_FOR_APPROVAL, TaskStatus.RUNNING})
_TEST_COMMAND = re.compile(r"\b(pytest|py\.test|unittest|tox|nox|jest|vitest|mocha|rspec|phpunit|go\s+test|cargo\s+test|"
                           r"npm\s+(run\s+)?test|yarn\s+test|pnpm\s+test|make\s+test|mvn\s+test|gradle\s+test|ctest|lint|ruff|mypy|tsc)\b", re.I)


@dataclass(frozen=True, slots=True)
class CommandRecord:
    """A shell command the user or the delegated agent ran, with its exit code when known."""
    command: str
    exit_code: int | None
    at: datetime
    source: str = "human"          # "human" | "agent"

    @property
    def is_test(self) -> bool:
        return bool(_TEST_COMMAND.search(self.command))

    @property
    def failed(self) -> bool:
        return self.exit_code is not None and self.exit_code != 0

    @classmethod
    def coerce(cls, value: Any) -> "CommandRecord":
        if isinstance(value, cls):
            return value
        at = value.get("at") or value.get("timestamp")
        if isinstance(at, str):
            at = datetime.fromisoformat(at.replace("Z", "+00:00"))
        return cls(str(value["command"]), value.get("exit_code"), ensure_utc(at or datetime.now(timezone.utc)),
                   value.get("source", "human"))


@dataclass(slots=True)
class RecommendationContext:
    session_id: str
    goal: str
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_task: str | None = None
    task_phase: str = "unknown"
    observations: list[Observation] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    progress: float | None = None
    alignment: float | None = None
    blocker: str | None = None
    blocker_evidence: dict[str, Any] | None = None
    drift_state: str = "unknown"
    drift_seconds: float = 0.0
    context_switches: int = 0
    switch_window_seconds: float = 600.0
    recent_commands: list[CommandRecord] = field(default_factory=list)
    delegated_tasks: list[DelegatedTask] = field(default_factory=list)
    recent_recommendations: list[ActionRecommendation] = field(default_factory=list)
    confidence: float = 0.0
    subtasks: list[Subtask] = field(default_factory=list)
    last_aligned_task: str | None = None
    goal_state: GoalState | None = None
    session_started_at: datetime | None = None

    def __post_init__(self) -> None:
        self.now = ensure_utc(self.now)
        self.recent_commands = [CommandRecord.coerce(item) for item in self.recent_commands]

    @property
    def active_tasks(self) -> list[DelegatedTask]:
        return [task for task in self.delegated_tasks if task.status in ACTIVE_TASK_STATUSES]

    @classmethod
    def from_engine(cls, engine, session_id: str, *, now: datetime | None = None, window: int = 60, **kwargs: Any) -> "RecommendationContext":
        state = engine.state
        now = ensure_utc(now) if now else datetime.now(timezone.utc)
        observations = list(state.observations[-window:])
        return cls(session_id=session_id, goal=state.goal.primary_goal, now=now, current_task=state.current_task,
                   task_phase=state.current_task_phase, observations=observations,
                   segments=[item.to_dict() for item in TaskSegmenter().segment(observations)],
                   progress=state.progress, alignment=state.alignment, blocker=state.blocker,
                   blocker_evidence=state.blocker_evidence, drift_state=state.drift_state,
                   drift_seconds=engine.drift_seconds(now), context_switches=engine.context_switch_count(),
                   confidence=engine.recent_confidence(5), last_aligned_task=state.last_high_alignment_task, **kwargs)

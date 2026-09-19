"""Perception output: semantic description, not productivity scoring."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ..models import iso


class VisionActivityType(str, Enum):
    IMPLEMENTATION = "implementation"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    DOCUMENTATION = "documentation"
    COMMUNICATION = "communication"
    TESTING = "testing"
    REVIEW = "review"
    PLANNING = "planning"
    WAITING = "waiting"
    BROWSING = "browsing"
    MEDIA = "media"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class VisionObservation:
    timestamp: datetime
    application: str | None
    window_title: str | None
    activity: str
    activity_type: VisionActivityType
    task_phase: str = "unknown"
    relevance: float | None = None
    progress_signal: float | None = None
    confidence: float | None = None
    visible_evidence: tuple[str, ...] = ()
    possible_blocker: str | None = None
    possible_completion: bool = False
    task_boundary: bool = False
    screen_change_score: float | None = None
    source: str = "moondream"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"timestamp": iso(self.timestamp), "application": self.application,
                "window_title": self.window_title, "activity": self.activity,
                "activity_type": self.activity_type.value, "task_phase": self.task_phase,
                "relevance": self.relevance, "progress_signal": self.progress_signal,
                "confidence": self.confidence, "visible_evidence": list(self.visible_evidence),
                "possible_blocker": self.possible_blocker, "possible_completion": self.possible_completion,
                "task_boundary": self.task_boundary, "screen_change_score": self.screen_change_score,
                "source": self.source, "metadata": self.metadata}

"""Deterministic temporal reasoning over semantic vision observations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ..models import ActivityCategory, Observation
from ..temporal import TaskSegmenter
from ..vision.schema import VisionActivityType, VisionObservation


class Recommendation(str, Enum):
    NONE = "none"
    REMIND_GOAL = "remind_goal"
    RETURN_TO_LAST_TASK = "return_to_last_task"
    SUMMARIZE_LAST_PROGRESS = "summarize_last_progress"
    SUGGEST_NEXT_STEP = "suggest_next_step"
    FLAG_POSSIBLE_BLOCKER = "flag_possible_blocker"
    RECOMMEND_BREAK = "recommend_break"
    ASK_CLARIFY_GOAL = "ask_clarify_goal"


@dataclass(frozen=True, slots=True)
class GoalRepresentation:
    primary_goal: str
    keywords: tuple[str, ...]
    success_signals: tuple[str, ...]

    @classmethod
    def from_text(cls, goal: str) -> "GoalRepresentation":
        words = [word.casefold() for word in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]{2,}", goal)]
        return cls(goal.strip(), tuple(dict.fromkeys(words)), ("tests pass", "completed", "resolved"))


@dataclass(slots=True)
class EfficiencyState:
    goal: GoalRepresentation
    current_task: str | None = None
    current_task_phase: str = "unknown"
    alignment: float | None = None
    progress: float | None = None
    focus_continuity: float | None = None
    context_stability: float | None = None
    drift_state: str = "unknown"
    idle_state: str = "active"
    coverage: float = 0.0
    confidence: float = 0.0
    last_intervention: datetime | None = None
    last_high_alignment_task: str | None = None
    last_progress_event: str | None = None
    session_score: float | None = None
    recommendation: Recommendation = Recommendation.NONE
    blocker: str | None = None
    observations: list[Observation] = field(default_factory=list)


class EfficiencyEngine:
    def __init__(self, goal: str) -> None:
        self.state = EfficiencyState(GoalRepresentation.from_text(goal))

    def _alignment(self, vision: VisionObservation) -> tuple[float | None, ActivityCategory]:
        if vision.relevance is not None:
            value = max(0.0, min(1.0, vision.relevance))
        else:
            content = f"{vision.activity} {' '.join(vision.visible_evidence)}".casefold()
            matches = sum(1 for word in self.state.goal.keywords if word in content)
            if matches:
                value = min(.95, .55 + matches * .12)
            elif vision.activity_type in {VisionActivityType.UNKNOWN, VisionActivityType.WAITING}:
                return None, ActivityCategory.UNKNOWN
            elif vision.activity_type in {VisionActivityType.RESEARCH, VisionActivityType.DOCUMENTATION, VisionActivityType.COMMUNICATION}:
                value = .55
            else:
                value = .15
        if value >= .7:
            return value, ActivityCategory.CORE_TASK if vision.activity_type in {VisionActivityType.IMPLEMENTATION, VisionActivityType.DEBUGGING, VisionActivityType.TESTING, VisionActivityType.REVIEW} else ActivityCategory.SUPPORTING_TASK
        if value >= .4:
            return value, ActivityCategory.NEUTRAL
        return value, ActivityCategory.DISTRACTION

    def update(self, vision: VisionObservation, idle_state: str = "active") -> Observation:
        alignment, category = self._alignment(vision)
        observation = Observation("obs_eff_" + str(len(self.state.observations)), "", vision.timestamp,
            vision.source, vision.application, vision.window_title, vision.activity, category,
            alignment, vision.progress_signal, vision.confidence, {"vision": vision.to_dict()})
        self.state.observations.append(observation)
        self.state.observations = self.state.observations[-500:]
        self.state.current_task, self.state.current_task_phase = vision.activity, vision.task_phase
        self.state.alignment, self.state.progress, self.state.idle_state = alignment, vision.progress_signal, idle_state
        if alignment is not None and alignment >= .7:
            self.state.last_high_alignment_task = vision.activity
        if vision.progress_signal is not None and vision.progress_signal >= .7:
            self.state.last_progress_event = vision.activity
        self.state.blocker = vision.possible_blocker
        self.state.recommendation = Recommendation.FLAG_POSSIBLE_BLOCKER if vision.possible_blocker else Recommendation.NONE
        self.state.coverage = sum(item.goal_alignment is not None for item in self.state.observations) / len(self.state.observations)
        confidences = [item.confidence for item in self.state.observations if item.confidence is not None]
        self.state.confidence = sum(confidences) / len(confidences) if confidences else 0.0
        self.state.drift_state = "drifting" if alignment is not None and alignment < .3 else "focused" if alignment is not None and alignment >= .7 else "mixed"
        segments = TaskSegmenter().segment(self.state.observations)
        self.state.context_stability = max(0.0, 1 - (max(0, len(segments) - 1) / max(1, len(self.state.observations) - 1)))
        self.state.focus_continuity = min(1.0, max((segment.to_dict()["duration_seconds"] for segment in segments if segment.alignment is not None and segment.alignment >= .7), default=0) / 300)
        if alignment is not None and self.state.focus_continuity is not None and self.state.context_stability is not None and self.state.progress is not None:
            self.state.session_score = 100 * (.4 * alignment + .25 * self.state.focus_continuity + .15 * self.state.context_stability + .2 * self.state.progress)
        return observation

    def report(self) -> dict[str, Any]:
        return {"goal": self.state.goal.primary_goal, "current_task": self.state.current_task,
                "task_phase": self.state.current_task_phase, "alignment": self.state.alignment,
                "progress": self.state.progress, "focus_continuity": self.state.focus_continuity,
                "context_stability": self.state.context_stability, "drift_state": self.state.drift_state,
                "coverage": self.state.coverage, "confidence": self.state.confidence,
                "session_score": self.state.session_score, "recommendation": self.state.recommendation.value,
                "blocker": self.state.blocker, "segments": [item.to_dict() for item in TaskSegmenter().segment(self.state.observations)]}

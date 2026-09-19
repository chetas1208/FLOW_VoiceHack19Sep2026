"""Compact temporal context and reproducible task segmentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean
from typing import Any

from .models import ActivityCategory, Observation, ensure_utc, iso


@dataclass(slots=True)
class TaskSegment:
    start: datetime
    end: datetime
    activity_summary: str
    category: ActivityCategory
    app_name: str | None
    alignment: float | None
    confidence: float | None
    observation_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"start": iso(self.start), "end": iso(self.end), "duration_seconds": max(0.0, (self.end - self.start).total_seconds()),
                "activity_summary": self.activity_summary, "category": self.category.value,
                "app_name": self.app_name, "alignment": self.alignment, "confidence": self.confidence,
                "observation_count": self.observation_count}


@dataclass(slots=True)
class TemporalContext:
    goal: str
    current_activity: str | None = None
    task_phase: str = "unknown"
    recent_observations: list[dict[str, Any]] = field(default_factory=list)
    last_aligned_activity: str | None = None
    current_drift_state: str = "unknown"

    def update(self, observation: Observation, drift_state: str) -> None:
        self.current_activity = observation.activity_summary
        self.current_drift_state = drift_state
        if observation.goal_alignment is not None and observation.goal_alignment >= .7:
            self.last_aligned_activity = observation.activity_summary
        self.recent_observations.append(observation.to_dict())
        self.recent_observations = self.recent_observations[-10:]


class TaskSegmenter:
    def __init__(self, gap_seconds: float = 120.0) -> None:
        self.gap_seconds = gap_seconds

    def segment(self, observations: list[Observation]) -> list[TaskSegment]:
        ordered = sorted(observations, key=lambda item: (ensure_utc(item.timestamp), item.id))
        if not ordered:
            return []
        segments: list[TaskSegment] = []
        current: TaskSegment | None = None
        previous: Observation | None = None
        for item in ordered:
            split = current is not None and previous is not None and (
                item.category != current.category or item.app_name != current.app_name or
                item.activity_summary != current.activity_summary or
                (ensure_utc(item.timestamp) - ensure_utc(previous.timestamp)).total_seconds() > self.gap_seconds)
            if current is None or split:
                if current is not None:
                    segments.append(current)
                current = TaskSegment(ensure_utc(item.timestamp), ensure_utc(item.timestamp),
                                      item.activity_summary or "Unknown activity", item.category, item.app_name,
                                      item.goal_alignment, item.confidence, 1)
            else:
                current.end = ensure_utc(item.timestamp)
                values = [current.alignment, item.goal_alignment]
                current.alignment = mean([value for value in values if value is not None]) if any(value is not None for value in values) else None
                conf = [current.confidence, item.confidence]
                current.confidence = mean([value for value in conf if value is not None]) if any(value is not None for value in conf) else None
                current.observation_count += 1
            previous = item
        if current is not None:
            segments.append(current)
        return segments

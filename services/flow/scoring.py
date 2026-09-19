"""Deterministic metrics and drift calculations over semantic observations."""

from __future__ import annotations

from datetime import timedelta
from statistics import mean

from .models import ActivityCategory, DriftState, Observation, SessionMetrics


class ScoringEngine:
    def __init__(self, drift_duration_seconds: float = 2.0, recovery_observations: int = 2) -> None:
        self.drift_duration_seconds = drift_duration_seconds
        self.recovery_observations = recovery_observations

    def metrics(self, observations: list[Observation], intervention_count: int = 0) -> SessionMetrics:
        if not observations:
            return SessionMetrics(intervention_count=intervention_count)
        ordered = sorted(observations, key=lambda item: (item.timestamp, item.id))
        durations = self._durations(ordered)
        observed_seconds = sum(durations)
        known_seconds = sum(duration for item, duration in zip(ordered, durations) if item.category != ActivityCategory.UNKNOWN)
        alignment_values = [(item.goal_alignment, duration) for item, duration in zip(ordered, durations)
                            if item.goal_alignment is not None and duration > 0]
        alignment = self._weighted(alignment_values)
        progress_values = [item.progress_signal for item in ordered if item.progress_signal is not None]
        progress = mean(progress_values) if progress_values else None
        counts = {category: sum(duration for item, duration in zip(ordered, durations) if item.category == category)
                  for category in ActivityCategory}
        contexts = [(item.app_name, item.window_title) for item in ordered]
        switches = sum(1 for previous, current in zip(contexts, contexts[1:]) if previous != current)
        stability = max(0.0, 1.0 - (switches / max(1, len(ordered) - 1))) if len(ordered) > 1 else 1.0
        blocks = self._focus_blocks(ordered, durations)
        focus = min(1.0, (mean(blocks) / 300.0)) if blocks else 0.0
        coverage = known_seconds / observed_seconds if observed_seconds else 0.0
        confidence_values = [item.confidence for item in ordered if item.confidence is not None]
        confidence = (mean(confidence_values) * coverage) if confidence_values else 0.0
        score = None
        if alignment is not None and progress is not None:
            score = 100 * (0.40 * alignment + 0.25 * focus + 0.15 * stability + 0.20 * progress)
        elif alignment is not None:
            score = 100 * (0.65 * alignment + 0.35 * focus) if coverage else None
        return SessionMetrics(alignment, focus if known_seconds else None, stability if observed_seconds else None,
            progress, score, counts[ActivityCategory.CORE_TASK], counts[ActivityCategory.SUPPORTING_TASK],
            counts[ActivityCategory.NEUTRAL], counts[ActivityCategory.DISTRACTION], counts[ActivityCategory.UNKNOWN],
            switches, intervention_count, coverage, confidence, self.drift_state(ordered),
            max(blocks, default=0.0), mean(blocks) if blocks else 0.0, len(blocks))

    @staticmethod
    def _weighted(values: list[tuple[float | None, float]]) -> float | None:
        usable = [(value, duration) for value, duration in values if value is not None and duration > 0]
        total = sum(duration for _, duration in usable)
        return sum(value * duration for value, duration in usable) / total if total else None

    @staticmethod
    def _durations(observations: list[Observation]) -> list[float]:
        # A sample represents the interval until the next sample. The final sample has
        # no observed interval, avoiding fabricated wall-clock evidence.
        return [max(0.0, (right.timestamp - left.timestamp).total_seconds())
                for left, right in zip(observations, observations[1:])] + [0.0]

    @staticmethod
    def _focus_blocks(observations: list[Observation], durations: list[float]) -> list[float]:
        blocks: list[float] = []
        current = 0.0
        for item, duration in zip(observations, durations):
            if item.goal_alignment is not None and item.goal_alignment >= 0.70:
                current += duration
            elif current:
                blocks.append(current)
                current = 0.0
        if current:
            blocks.append(current)
        return blocks

    def drift_state(self, observations: list[Observation]) -> DriftState:
        usable = [item for item in observations if item.goal_alignment is not None]
        if len(usable) < 2:
            return DriftState.UNKNOWN
        recent = usable[-5:]
        average = mean(item.goal_alignment for item in recent)
        low_seconds = 0.0
        for index in range(len(usable) - 2, -1, -1):
            left, right = usable[index], usable[index + 1]
            if left.goal_alignment is None or left.goal_alignment >= 0.25:
                break
            low_seconds += max(0.0, (right.timestamp - left.timestamp).total_seconds())
        low_average = mean(item.goal_alignment for item in recent if item.goal_alignment < 0.25) if any(item.goal_alignment < 0.25 for item in recent) else 1.0
        if low_average < 0.25 and low_seconds >= self.drift_duration_seconds:
            return DriftState.SUSTAINED_DRIFT
        if average < 0.45:
            return DriftState.DRIFTING
        if average < 0.75:
            return DriftState.MIXED
        if len(recent) >= self.recovery_observations and all(item.goal_alignment >= 0.70 for item in recent[-self.recovery_observations:]):
            return DriftState.FOCUSED
        return DriftState.RECOVERING

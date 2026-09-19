"""Validated semantic-analysis contracts; screen text is evidence, never instructions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import ActivityCategory
from .observer.frame import CapturedFrame
from .privacy.redaction import redact_text


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    activity_summary: str
    category: ActivityCategory
    goal_alignment: float | None
    progress_signal: float | None
    confidence: float | None
    reasoning_summary: str | None = None
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_observation_fields(self) -> dict[str, Any]:
        return {"activity_summary": redact_text(self.activity_summary), "category": self.category.value,
                "goal_alignment": self.goal_alignment, "progress_signal": self.progress_signal,
                "confidence": self.confidence, "metadata": {**self.metadata,
                    "reasoning_summary": redact_text(self.reasoning_summary),
                    "evidence": [redact_text(item) for item in self.evidence]}}


class ActivityAnalyzer(Protocol):
    async def analyze(self, goal: str, frame: CapturedFrame, context: dict[str, Any],
                      history: list[dict[str, Any]]) -> AnalysisResult: ...


class MockAnalyzer:
    def __init__(self, result: AnalysisResult | None = None) -> None:
        self.result = result or AnalysisResult("Observed desktop activity", ActivityCategory.UNKNOWN, None, None, .1)

    async def analyze(self, goal, frame, context, history) -> AnalysisResult:
        return self.result


def validate_analysis(value: Any) -> AnalysisResult:
    if not isinstance(value, dict):
        raise ValueError("analysis result must be an object")
    summary = value.get("activity_summary")
    if not isinstance(summary, str) or not summary or len(summary) > 4000:
        raise ValueError("activity_summary must be a non-empty bounded string")
    try:
        category = ActivityCategory(value.get("category", "unknown"))
    except ValueError as exc:
        raise ValueError("invalid analysis category") from exc
    fields = {}
    for key in ("goal_alignment", "progress_signal", "confidence"):
        item = value.get(key)
        if item is not None and (not isinstance(item, (float, int)) or not 0 <= item <= 1):
            raise ValueError(f"invalid {key}")
        fields[key] = float(item) if item is not None else None
    evidence = value.get("evidence", [])
    if not isinstance(evidence, list) or len(evidence) > 20 or not all(isinstance(item, str) and len(item) <= 500 for item in evidence):
        raise ValueError("invalid evidence")
    return AnalysisResult(summary, category, fields["goal_alignment"], fields["progress_signal"],
                          fields["confidence"], value.get("reasoning_summary"), tuple(evidence), value.get("metadata", {}))

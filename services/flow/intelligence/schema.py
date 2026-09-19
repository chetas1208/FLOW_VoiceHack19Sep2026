"""Strict semantic contract produced by local intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..vision.schema import VisionActivityType, VisionObservation


@dataclass(frozen=True, slots=True)
class IntelligenceObservation:
    """Vendor-neutral observation with no productivity score invented by the model."""

    observation: VisionObservation
    raw_provider: str

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, timestamp, application, window_title,
                  source: str = "qwen3-vl") -> "IntelligenceObservation":
        kind = VisionActivityType(str(value.get("activity_type", "unknown")).lower())
        def bounded(name: str) -> float | None:
            item = value.get(name)
            if item is None:
                return None
            if not isinstance(item, (int, float)) or isinstance(item, bool):
                raise ValueError(f"{name} must be numeric or null")
            return max(0.0, min(1.0, float(item)))
        evidence = value.get("evidence", [])
        if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
            raise ValueError("evidence must be a list of strings")
        observation = VisionObservation(
            timestamp=timestamp, application=application, window_title=window_title,
            activity=str(value.get("activity") or "Unknown activity")[:4000], activity_type=kind,
            task_phase=str(value.get("task_phase") or "unknown")[:80], relevance=bounded("goal_relevance"),
            progress_signal=bounded("progress_signal"), confidence=bounded("confidence"),
            visible_evidence=tuple(item[:500] for item in evidence[:20]),
            possible_blocker=(str(value["blocker_signal"])[:500] if value.get("blocker_signal") else None),
            possible_completion=bool(value.get("completion_signal", False)),
            task_boundary=bool(value.get("task_boundary", False)), source=source,
            metadata={"provider": source})
        return cls(observation, source)

"""Cooldown and confidence policy for rare, non-shaming interventions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True, slots=True)
class InterventionPolicyConfig:
    minimum_confidence: float = .75
    minimum_drift_seconds: float = 120.0
    cooldown_seconds: float = 600.0


class InterventionPolicy:
    def __init__(self, config: InterventionPolicyConfig | None = None) -> None:
        self.config = config or InterventionPolicyConfig()
        self._last_intervention: datetime | None = None

    def should_intervene(self, *, drift_seconds: float, confidence: float,
                         now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        if confidence < self.config.minimum_confidence or drift_seconds < self.config.minimum_drift_seconds:
            return False
        if self._last_intervention and now - self._last_intervention < timedelta(seconds=self.config.cooldown_seconds):
            return False
        self._last_intervention = now
        return True

    @staticmethod
    def message(last_activity: str | None, drift_seconds: float) -> str:
        minutes = max(1, round(drift_seconds / 60))
        subject = f" Your last aligned activity was {last_activity}." if last_activity else ""
        return f"You've been away from the declared task for about {minutes} minutes.{subject}"

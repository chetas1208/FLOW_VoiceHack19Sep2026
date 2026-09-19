"""Coaching policy around TTS; Kokoro itself only turns text into sound."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..efficiency import EfficiencyState, Recommendation
from ..voice.policy import InterventionPolicy


class VoiceAgent:
    def __init__(self, engine, policy: InterventionPolicy | None = None, enabled: bool = True) -> None:
        self.engine, self.policy, self.enabled = engine, policy or InterventionPolicy(), enabled
        self.last_message: str | None = None

    def message_for(self, state: EfficiencyState, drift_seconds: float) -> str | None:
        if state.recommendation == Recommendation.FLAG_POSSIBLE_BLOCKER and state.blocker:
            return f"You may be stuck on {state.blocker}. Consider checking the unresolved error before switching tasks."
        if state.drift_state in {"possible_drift", "drifting", "sustained_drift"}:
            return self.policy.message(state.last_high_alignment_task, drift_seconds)
        return None

    async def consider(self, state: EfficiencyState, drift_seconds: float,
                       now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        confidence = state.confidence
        message = self.message_for(state, drift_seconds)
        if not message or not self.policy.should_intervene(drift_seconds=drift_seconds, confidence=confidence, now=now):
            return False
        try:
            await self.engine.speak(message)
        except Exception:
            return False
        self.last_message = message
        return True

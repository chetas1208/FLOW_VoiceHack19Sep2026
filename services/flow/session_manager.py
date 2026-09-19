"""Application service containing the single source of truth for lifecycle rules."""

from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from .config import data_dir
from .events import EventHub, FlowEvent, event
from .models import (ActivityCategory, DriftState, Intervention, InterventionChannel,
                     Observation, SessionStatus, WorkSession, ensure_utc, utc_now)
from .scoring import ScoringEngine
from .store import FlowStore


class SessionError(Exception):
    pass


class SessionNotFound(SessionError):
    pass


class InvalidTransition(SessionError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.now(timezone.utc).timestamp() * 1000):x}{secrets.token_urlsafe(8)}"


class SessionManager:
    def __init__(self, store: FlowStore | None = None, hub: EventHub | None = None,
                 scorer: ScoringEngine | None = None) -> None:
        self.store = store or FlowStore(data_dir())
        self.hub = hub or EventHub()
        self.scorer = scorer or ScoringEngine()
        self._event_lock = threading.RLock()

    def _session(self, session_id: str) -> WorkSession:
        result = self.store.get_session(session_id)
        if result is None:
            raise SessionNotFound(f"session not found: {session_id}")
        return result

    def _emit(self, session_id: str, event_type: str, data: dict[str, Any]) -> FlowEvent:
        with self._event_lock:
            item = event(event_type, session_id, self.store.next_sequence(session_id), data, _id("evt"))
            self.store.save_event(item)
            self.hub.publish(item)
            return item

    def start_session(self, goal: str, metadata: dict[str, Any] | None = None, created_by: str | None = None) -> WorkSession:
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")
        now = utc_now()
        session = WorkSession(_id("ses"), goal.strip(), SessionStatus.ACTIVE, now, now,
                              metadata=metadata or {}, created_by=created_by)
        self.store.save_session(session)
        self._emit(session.id, "session.started", {"goal": session.goal})
        return session

    def get_session(self, session_id: str) -> WorkSession:
        return self._session(session_id)

    def list_sessions(self, status: SessionStatus | None = None, limit: int = 50) -> list[WorkSession]:
        return self.store.list_sessions(status, limit)

    def _transition(self, session_id: str, target: SessionStatus, event_type: str) -> WorkSession:
        session = self._session(session_id)
        allowed = {SessionStatus.ACTIVE: {SessionStatus.PAUSED, SessionStatus.COMPLETED},
                   SessionStatus.PAUSED: {SessionStatus.ACTIVE, SessionStatus.COMPLETED}}
        if target not in allowed.get(session.status, set()):
            if target == SessionStatus.COMPLETED and session.status == SessionStatus.COMPLETED:
                return session
            raise InvalidTransition(f"cannot change {session.status.value} session to {target.value}")
        now = utc_now()
        session.status = target
        session.updated_at = now
        if target == SessionStatus.COMPLETED:
            session.ended_at = now
        self.store.save_session(session)
        self._emit(session.id, event_type, {"status": target.value})
        return session

    def pause_session(self, session_id: str) -> WorkSession:
        return self._transition(session_id, SessionStatus.PAUSED, "session.paused")

    def resume_session(self, session_id: str) -> WorkSession:
        return self._transition(session_id, SessionStatus.ACTIVE, "session.resumed")

    def stop_session(self, session_id: str) -> WorkSession:
        return self._transition(session_id, SessionStatus.COMPLETED, "session.completed")

    def add_observation(self, session_id: str, observation: Observation) -> Observation:
        session = self._session(session_id)
        if session.status not in {SessionStatus.ACTIVE, SessionStatus.PAUSED}:
            raise InvalidTransition("observations can only be added to an active or paused session")
        if observation.session_id != session_id:
            raise ValueError("observation session_id does not match target session")
        if not observation.source:
            raise ValueError("observation source must not be empty")
        for name in ("goal_alignment", "progress_signal", "confidence"):
            value = getattr(observation, name)
            if value is not None and not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if not isinstance(observation.category, ActivityCategory):
            try:
                observation.category = ActivityCategory(observation.category)
            except ValueError as exc:
                raise ValueError("invalid observation category") from exc
        observation.timestamp = ensure_utc(observation.timestamp)
        previous_metrics = next((item for item in reversed(self.store.list_events(session_id))
                                 if item.type == "metrics.updated"), None)
        previous_state = previous_metrics.data.get("drift_state") if previous_metrics else DriftState.UNKNOWN.value
        self.store.save_observation(observation)
        self._emit(session_id, "observation.created", observation.to_dict())
        metrics = self.metrics(session_id)
        self._emit(session_id, "metrics.updated", metrics.to_dict())
        if metrics.drift_state.value != previous_state:
            was_drifting = previous_state in {DriftState.DRIFTING.value, DriftState.SUSTAINED_DRIFT.value}
            is_drifting = metrics.drift_state in {DriftState.DRIFTING, DriftState.SUSTAINED_DRIFT}
            if is_drifting or was_drifting:
                transition = "drift.entered" if is_drifting else "drift.cleared"
                self._emit(session_id, transition, {"from": previous_state, "to": metrics.drift_state.value})
        if metrics.drift_state == DriftState.SUSTAINED_DRIFT:
            previous = self.store.list_events(session_id)
            if not any(item.type == "intervention.proposed" and item.data.get("reason") == "sustained_goal_drift" for item in previous):
                intervention = Intervention(_id("int"), session_id, utc_now(), "sustained_goal_drift",
                    InterventionChannel.CLI, "Your recent activity appears substantially outside the declared goal.")
                self.add_intervention(session_id, intervention)
        return observation

    def observations(self, session_id: str) -> list[Observation]:
        self._session(session_id)
        return self.store.list_observations(session_id)

    def add_intervention(self, session_id: str, intervention: Intervention) -> Intervention:
        self._session(session_id)
        if intervention.session_id != session_id:
            raise ValueError("intervention session_id does not match target session")
        self.store.save_intervention(intervention)
        self._emit(session_id, "intervention.proposed", intervention.to_dict())
        return intervention

    def interventions(self, session_id: str) -> list[Intervention]:
        self._session(session_id)
        return self.store.list_interventions(session_id)

    def events(self, session_id: str, after: int = 0) -> list[FlowEvent]:
        self._session(session_id)
        return self.store.list_events(session_id, after)

    def metrics(self, session_id: str):
        self._session(session_id)
        return self.scorer.metrics(self.store.list_observations(session_id), len(self.store.list_interventions(session_id)))

    def report(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        return {**session.to_dict(), "metrics": self.metrics(session_id).to_dict(),
                "observation_count": len(self.observations(session_id)),
                "intervention_count": len(self.interventions(session_id))}

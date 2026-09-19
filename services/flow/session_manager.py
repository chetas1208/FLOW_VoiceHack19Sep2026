"""Application service containing the single source of truth for lifecycle rules."""

from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone
from typing import Any, Callable

from .config import data_dir, drift_seconds
from .events import EventHub, FlowEvent
from .models import (ActivityCategory, DriftState, Intervention, InterventionChannel,
                     Observation, SessionStatus, WorkSession, ensure_utc, utc_now)
from .scoring import ScoringEngine
from .store import FlowStore
from .temporal import TaskSegmenter


class SessionError(Exception):
    pass


class SessionNotFound(SessionError):
    pass


class InvalidTransition(SessionError):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{int(datetime.now(timezone.utc).timestamp() * 1000):x}{secrets.token_urlsafe(8)}"


SEGMENT_SYNC_EVERY = 6  # observations between incremental segment uploads


class SessionManager:
    """``cloud_sync=True`` writes a durable ``sync_outbox`` row in the same transaction as every entity."""

    def __init__(self, store: FlowStore | None = None, hub: EventHub | None = None,
                 scorer: ScoringEngine | None = None, cloud_sync: bool = False) -> None:
        self.store = store or FlowStore(data_dir())
        self.hub = hub or EventHub()
        self.scorer = scorer or ScoringEngine()
        self.cloud_sync = cloud_sync
        self._event_lock = threading.RLock()

    @classmethod
    def from_environment(cls, store: FlowStore | None = None, hub: EventHub | None = None,
                         scorer: ScoringEngine | None = None) -> "SessionManager":
        """Production wiring: realistic drift threshold, and cloud sync only while signed in."""
        try:
            from .sync.state import cloud_sync_enabled
        except ModuleNotFoundError:
            # The local-only distribution intentionally has no cloud sync
            # package; that must not prevent the daemon from starting.
            cloud_sync_enabled = lambda: False
        return cls(store, hub, scorer or ScoringEngine(drift_duration_seconds=drift_seconds()),
                   cloud_sync=cloud_sync_enabled())

    @property
    def outbox(self):
        from .sync.outbox import SyncOutbox
        return SyncOutbox(self.store)

    def _session(self, session_id: str) -> WorkSession:
        result = self.store.get_session(session_id)
        if result is None:
            raise SessionNotFound(f"session not found: {session_id}")
        return result

    def _emit(self, session_id: str, event_type: str, data: dict[str, Any]) -> FlowEvent:
        with self._event_lock:
            item = self.store.append_event(session_id, event_type, data, _id("evt"), sync=self.cloud_sync)
            self.hub.publish(item)
            return item

    def start_session(self, goal: str, metadata: dict[str, Any] | None = None, created_by: str | None = None) -> WorkSession:
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")
        now = utc_now()
        session = WorkSession(_id("ses"), goal.strip(), SessionStatus.ACTIVE, now, now,
                              metadata=metadata or {}, created_by=created_by)
        self.store.save_session(session, sync=self.cloud_sync)
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
        if self.cloud_sync:
            if target == SessionStatus.COMPLETED:
                self._enqueue_completion(session.id)
            else:
                self.sync_segments(session.id)
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
        previous_metrics = self.store.latest_event(session_id, "metrics.updated")
        previous_state = previous_metrics.data.get("drift_state") if previous_metrics else DriftState.UNKNOWN.value
        self.store.save_observation(observation, sync=self.cloud_sync)
        self._emit(session_id, "observation.created", observation.to_dict())
        metrics = self.metrics(session_id)
        self._emit(session_id, "metrics.updated", metrics.to_dict())
        if metrics.drift_state.value != previous_state:
            self._emit(session_id, "drift.changed", {"from": previous_state, "to": metrics.drift_state.value})
            was_drifting = previous_state in {DriftState.DRIFTING.value, DriftState.SUSTAINED_DRIFT.value}
            is_drifting = metrics.drift_state in {DriftState.DRIFTING, DriftState.SUSTAINED_DRIFT}
            if is_drifting or was_drifting:
                transition = "drift.entered" if is_drifting else "drift.cleared"
                self._emit(session_id, transition, {"from": previous_state, "to": metrics.drift_state.value})
        if metrics.drift_state == DriftState.SUSTAINED_DRIFT:
            if not self.store.has_intervention_reason(session_id, "sustained_goal_drift"):
                intervention = Intervention(_id("int"), session_id, utc_now(), "sustained_goal_drift",
                    InterventionChannel.CLI, "Your recent activity appears substantially outside the declared goal.")
                self.add_intervention(session_id, intervention)
        if self.cloud_sync and observation.sequence and observation.sequence % SEGMENT_SYNC_EVERY == 0:
            self.sync_segments(session_id)
        return observation

    def observations(self, session_id: str) -> list[Observation]:
        self._session(session_id)
        return self.store.list_observations(session_id)

    def add_intervention(self, session_id: str, intervention: Intervention) -> Intervention:
        self._session(session_id)
        if intervention.session_id != session_id:
            raise ValueError("intervention session_id does not match target session")
        self.store.save_intervention(intervention, sync=self.cloud_sync)
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
        observations = self.observations(session_id)
        return {**session.to_dict(), "metrics": self.metrics(session_id).to_dict(),
                "observation_count": len(observations),
                "intervention_count": len(self.interventions(session_id)),
                "task_segments": [segment.to_dict() for segment in TaskSegmenter().segment(observations)]}

    # ---- cloud sync helpers ---------------------------------------------------------------------
    def completion_payloads(self, session_id: str) -> dict[str, Any]:
        """Wire payloads for a finished session: segments, the immutable summary and the stop request."""
        from .sync import payloads
        session = self._session(session_id)
        observations = self.store.list_observations(session_id)
        interventions = self.store.list_interventions(session_id)
        events = self.store.list_events(session_id, 0, limit=10 ** 9)
        segments = TaskSegmenter().segment(observations)
        metrics = self.scorer.metrics(observations, len(interventions))
        return {"segments": [payloads.segment_payload(session_id, item) for item in segments],
                "summary": payloads.summary_payload(session, metrics, observations, interventions, events, segments),
                "stop": payloads.stop_payload(session)}

    def _enqueue_completion(self, session_id: str) -> None:
        payload = self.completion_payloads(session_id)
        items = [("segment", item["id"], item, None) for item in payload["segments"]]
        items += [("summary", session_id, payload["summary"], None), ("stop", session_id, payload["stop"], None)]
        self.store.enqueue_many(session_id, items)

    def sync_segments(self, session_id: str) -> int:
        """Queue current task segments (upserted by id; a higher ``revision`` replaces a queued older one)."""
        if not self.cloud_sync:
            return 0
        from .sync import payloads
        segments = TaskSegmenter().segment(self.store.list_observations(session_id))
        items = [("segment", payloads.segment_id(session_id, item.start), payloads.segment_payload(session_id, item), None)
                 for item in segments]
        return self.store.enqueue_many(session_id, items)

    def sync_entity(self, session_id: str, kind: str, entity_id: str, revision: int, data: dict[str, Any]) -> bool:
        """Queue a remote-layer entity (task, approval, recommendation, subtask, goal_version, chat, runtime_state)."""
        if not self.cloud_sync:
            return False
        from .sync import payloads
        payload = payloads.entity_payload(kind, entity_id, revision, data)
        return self.store.enqueue("entity", payloads.entity_key(kind, entity_id), session_id, payload)

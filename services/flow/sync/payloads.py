"""Upload payload builders: the only place local data becomes cloud JSON.

Privacy is enforced here, once, so every path (live enqueue, crash reconcile, entity sync) is covered:

* pixels / raw frames never leave the device (forbidden keys are dropped at any depth);
* window titles are dropped unless ``FLOW_SYNC_WINDOW_TITLES=true`` and then only ever ride inside
  ``observation.created`` event data (the observation wire schema has no title field);
* evidence text (``evidence`` fields of recommendations, tasks, subtasks...) is emptied unless
  ``FLOW_SYNC_EVIDENCE=true``;
* free text passes through ``privacy.redaction.redact_text``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from .. import config
from ..events import FlowEvent
from ..models import Intervention, Observation, SessionMetrics, WorkSession, ensure_utc, iso
from ..privacy.redaction import redact_text
from ..temporal import TaskSegment

FORBIDDEN_KEYS = {"image", "image_bytes", "image_base64", "screenshot", "screenshot_path", "frame", "pixels",
                  "raw_frame", "image_path", "thumbnail"}
TITLE_KEYS = {"window_title", "window_titles"}
EVIDENCE_KEYS = {"evidence", "evidence_text", "evidence_excerpts"}
STRUCTURAL_KEYS = {"id", "type", "status", "category", "kind", "level", "channel", "source", "state", "timestamp",
                   "from", "to", "version", "sequence", "revision"}
ENTITY_KINDS = {"task", "approval", "recommendation", "subtask", "goal_version", "chat", "runtime_state"}
MAX_EVENT_BYTES = 16_000
MAX_DEPTH = 7


def _structural(key: str | None) -> bool:
    return bool(key) and (key in STRUCTURAL_KEYS or key.endswith(("_id", "_ids", "_at")))


def _text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    return (redact_text(value) or "")[:limit]


def sanitize(value: Any, key: str | None = None, depth: int = 0) -> Any:
    """Recursively drop forbidden keys, gate titles/evidence behind their flags, and redact free text."""
    if depth > MAX_DEPTH:
        return None
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for name, item in value.items():
            lowered = str(name).lower()
            if lowered in FORBIDDEN_KEYS:
                continue
            if lowered in TITLE_KEYS and not config.sync_window_titles():
                continue
            if lowered in EVIDENCE_KEYS and not config.sync_evidence():
                clean[str(name)] = [] if isinstance(item, (list, tuple)) else None
                continue
            clean[str(name)] = sanitize(item, str(name), depth + 1)
        return clean
    if isinstance(value, (list, tuple)):
        return [sanitize(item, key, depth + 1) for item in value]
    if isinstance(value, str):
        return value[:4000] if _structural(key) else _text(value, 4000)
    if isinstance(value, datetime):
        return iso(value)
    return value


def _size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), default=str))


def _bounded(data: dict[str, Any], limit: int = MAX_EVENT_BYTES) -> dict[str, Any]:
    if _size(data) <= limit:
        return data
    scalars = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
    scalars["truncated"] = True
    return scalars if _size(scalars) <= limit else {"truncated": True}


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


# ---- sessions / observations / events / interventions ------------------------------------------
def session_payload(session: WorkSession) -> dict[str, Any]:
    metadata = sanitize(session.metadata or {})
    return {"id": session.id, "goal": _text(session.goal, 2000) or "", "started_at": iso(session.started_at),
            "metadata": metadata if _size(metadata) <= 3500 else {}}


def _observation_fields(data: dict[str, Any]) -> dict[str, Any]:
    meta = data.get("metadata") or {}
    return _clean({
        "id": data["id"], "sequence": data.get("sequence"), "timestamp": data["timestamp"],
        "activity": _text(data.get("activity_summary"), 1000),
        "category": data.get("category") or "unknown",
        "goal_alignment": data.get("goal_alignment"), "progress_signal": data.get("progress_signal"),
        "confidence": data.get("confidence"),
        "task_phase": _text(meta.get("task_phase"), 40),
        "application": _text(data.get("app_name"), 200),
        "activity_type": _text(meta.get("activity_type"), 40),
        "source": (data.get("source") or "observer")[:40],
        "blocker": _text(meta.get("blocker") if isinstance(meta.get("blocker"), str) else None, 200)})


def observation_payload(observation: Observation) -> dict[str, Any]:
    """Exactly the wire ``ObservationIn``: no window title, no evidence, no metadata blob, no pixels."""
    return _observation_fields(observation.to_dict())


def event_payload(item: FlowEvent) -> dict[str, Any]:
    if item.type == "observation.created":
        data = _observation_fields(item.data)
        title = item.data.get("window_title")
        if config.sync_window_titles() and isinstance(title, str):
            data["window_title"] = _text(title, 300)
    else:
        data = sanitize(item.data)
    return {"id": item.event_id, "sequence": item.sequence, "type": item.type,
            "timestamp": iso(item.timestamp), "data": _bounded(data)}


def intervention_payload(intervention: Intervention) -> dict[str, Any]:
    metadata = sanitize(intervention.metadata or {})
    return _clean({"id": intervention.id, "timestamp": iso(intervention.timestamp),
                   "reason": (intervention.reason or "unknown")[:100], "channel": intervention.channel.value,
                   "message": _text(intervention.message, 1000), "status": intervention.status.value,
                   "metadata": metadata if _size(metadata) <= 3500 else {}})


# ---- segments / entities / summary / stop -------------------------------------------------------
def segment_id(session_id: str, start: datetime) -> str:
    return "seg_" + hashlib.sha1(f"{session_id}:{ensure_utc(start).isoformat()}".encode()).hexdigest()[:24]


def segment_payload(session_id: str, segment: TaskSegment) -> dict[str, Any]:
    return _clean({"id": segment_id(session_id, segment.start), "start": iso(segment.start), "end": iso(segment.end),
                   "activity": _text(segment.activity_summary, 1000), "category": segment.category.value,
                   "application": _text(segment.app_name, 200), "alignment": segment.alignment,
                   "confidence": segment.confidence, "observation_count": segment.observation_count,
                   "revision": max(1, segment.observation_count)})


def entity_payload(kind: str, entity_id: str, revision: int, data: dict[str, Any]) -> dict[str, Any]:
    if kind not in ENTITY_KINDS:
        raise ValueError(f"unknown entity kind {kind!r}; expected one of {sorted(ENTITY_KINDS)}")
    return {"kind": kind, "id": str(entity_id), "revision": max(1, int(revision)), "data": _bounded(sanitize(data), 60_000)}


def entity_key(kind: str, entity_id: str) -> str:
    return f"{kind}/{entity_id}"


def drift_periods(events: list[FlowEvent]) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    for item in sorted(events, key=lambda e: e.sequence):
        if item.type == "drift.entered":
            periods.append({"start": iso(item.timestamp), "end": None, "state": item.data.get("to")})
        elif item.type == "drift.cleared" and periods and periods[-1]["end"] is None:
            periods[-1]["end"] = iso(item.timestamp)
    return periods[-500:]


def summary_payload(session: WorkSession, metrics: SessionMetrics, observations: list[Observation],
                    interventions: list[Intervention], events: list[FlowEvent],
                    segments: list[TaskSegment]) -> dict[str, Any]:
    end = session.ended_at or session.updated_at
    duration = max(0.0, (ensure_utc(end) - ensure_utc(session.started_at)).total_seconds())
    active = (metrics.aligned_seconds + metrics.supporting_seconds + metrics.neutral_seconds
              + metrics.distraction_seconds + metrics.unknown_seconds)
    blockers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in observations:
        blocker = (observation.metadata or {}).get("blocker")
        if isinstance(blocker, str) and blocker and blocker not in seen and len(blockers) < 200:
            seen.add(blocker)
            blockers.append({"blocker": _text(blocker, 200), "first_seen": iso(observation.timestamp)})
    return _clean({
        "schema_version": 1, "goal": _text(session.goal, 2000) or "", "duration_seconds": duration,
        "active_seconds": min(active, duration) if duration else active, "away_seconds": max(0.0, duration - active),
        "goal_alignment": metrics.goal_alignment, "focus_continuity": metrics.focus_continuity,
        "context_stability": metrics.context_stability, "progress": metrics.progress,
        "session_score": metrics.session_score, "coverage": metrics.coverage, "confidence": metrics.confidence,
        "segments": [{k: v for k, v in segment_payload(session.id, s).items() if k != "revision"}
                     for s in segments][:2000],
        "blockers": blockers, "drift_periods": drift_periods(events),
        "interventions": [{"id": i.id, "reason": i.reason[:100], "channel": i.channel.value,
                           "timestamp": iso(i.timestamp), "status": i.status.value} for i in interventions][:500],
        "recommendations": [],
        "extra": {"observation_count": len(observations), "context_switches": metrics.context_switches,
                  "drift_state": metrics.drift_state.value}})


def stop_payload(session: WorkSession) -> dict[str, Any]:
    return {"ended_at": iso(session.ended_at or session.updated_at)}

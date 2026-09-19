"""Read models: session detail, live view and structured report (pure functions over the repo)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..flow.models import ActivityCategory, Observation
from ..flow.scoring import ScoringEngine
from ..flow.temporal import TaskSegmenter
from .core import command_out, entity_out, event_out, presence_view, session_out
from .repo import Repo, iso, now, utc


def _obs_models(rows: list[dict[str, Any]]) -> list[Observation]:
    return [Observation(r["id"], r["session_id"], r["client_timestamp"], r["source"], r["application"], None, r["activity"],
                        ActivityCategory(r["category"]), r["goal_alignment"], r["progress_signal"], r["confidence"], {})
            for r in rows]


def _device_name(repo: Repo, device_id: str) -> str | None:
    device = repo.get_device(device_id)
    return device["name"] if device else None


def runtime_state(repo: Repo, session_id: str) -> dict[str, Any] | None:
    row = repo.get_entity(session_id, "runtime_state", "current")
    return row["data"] if row else None


def session_view(repo: Repo, session: dict[str, Any]) -> dict[str, Any]:
    return session_out(session, _device_name(repo, session["device_id"]), runtime_state(repo, session["id"]))


def latest_data(repo: Repo, session_id: str, event_type: str) -> dict[str, Any] | None:
    row = repo.latest_event(session_id, event_type)
    return row["data"] if row else None


def segment_out(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "start": iso(row["start_at"]), "end": iso(row["end_at"]), "activity": row["activity"],
            "category": row["category"], "application": row["application"], "alignment": row["alignment"],
            "confidence": row["confidence"], "observation_count": row["observation_count"], "revision": row["revision"],
            "duration_seconds": max(0.0, (row["end_at"] - row["start_at"]).total_seconds())}


def intervention_out(row: dict[str, Any]) -> dict[str, Any]:
    return {"id": row["id"], "timestamp": iso(row["timestamp"]), "reason": row["reason"], "channel": row["channel"],
            "message": row["message"], "status": row["status"], "metadata": row["metadata"]}


def goal_history(repo: Repo, session_id: str) -> list[dict[str, Any]]:
    items = [e["data"] for e in repo.list_entities(session_id, "goal_version", limit=200)]
    return sorted(items, key=lambda i: i.get("version", 0))


def session_detail(repo: Repo, session: dict[str, Any]) -> dict[str, Any]:
    sid = session["id"]
    summary = repo.latest_summary(sid)
    return {"session": session_view(repo, session),
            "summary": {"version": summary["version"], "source": summary["source"], "created_at": iso(summary["created_at"]),
                        **summary["summary"]} if summary else None,
            "metrics": latest_data(repo, sid, "metrics.updated"),
            "segments": [segment_out(r) for r in repo.list_segments(sid)],
            "interventions": [intervention_out(r) for r in repo.list_interventions(sid)],
            "goal_history": goal_history(repo, sid),
            "subtasks": sorted((e["data"] for e in repo.list_entities(sid, "subtask", limit=200)),
                               key=lambda s: s.get("position", 0))}


def live_view(repo: Repo, session: dict[str, Any]) -> dict[str, Any]:
    sid = session["id"]
    latest = repo.latest_observation(sid)
    efficiency = latest_data(repo, sid, "efficiency.updated") or {}
    metrics = latest_data(repo, sid, "metrics.updated") or {}
    segments = repo.list_segments(sid)
    runtime = runtime_state(repo, sid) or {}
    tasks = [e["data"] for e in repo.list_entities(sid, "task", limit=20)]
    approvals = [e["data"] for e in repo.list_entities(sid, "approval", status="pending", limit=20)]
    recs = repo.list_entities(sid, "recommendation", status="pending", limit=1)
    active_task = next((t for t in tasks if t.get("status") in {"planning", "running", "waiting_for_approval"}), None)
    presence = presence_view(repo.get_presence(session["device_id"]))
    goal_versions = goal_history(repo, sid)
    subtasks = sorted((e["data"] for e in repo.list_entities(sid, "subtask", limit=200)), key=lambda s: s.get("position", 0))
    return {
        "session": session_view(repo, session),
        "presence": presence,
        "current": {"activity": latest["activity"] if latest else None,
                    "task_phase": efficiency.get("task_phase") or (latest or {}).get("task_phase"),
                    "alignment": efficiency.get("alignment", (latest or {}).get("goal_alignment")),
                    "drift": efficiency.get("drift_state") or metrics.get("drift_state"),
                    "blocker": efficiency.get("blocker") or (latest or {}).get("blocker") or "none",
                    "category": (latest or {}).get("category"), "application": (latest or {}).get("application")},
        "metrics": metrics, "efficiency": efficiency,
        "latest_segment": segment_out(segments[-1]) if segments else None,
        "observer_health": {"observer": runtime.get("observer"), "vision": runtime.get("vision"),
                            "device": presence["health"]},
        "voice": {"state": runtime.get("voice", "unknown"), "muted_until": runtime.get("voice_muted_until")},
        "agent": {"status": "running" if active_task else "idle", "current_task": active_task,
                  "pending_approvals": len(approvals)},
        "goal": {"text": session["goal"], "version": session.get("goal_version", 1),
                 "state": runtime.get("goal_state", "in_progress"), "history": goal_versions, "subtasks": subtasks},
        "recommendation": recs[0]["data"] if recs else None,
        "tasks": tasks, "approvals": approvals,
        "last_event_sequence": (repo.sequence_state(_events_table(), sid, 0)["highest_sequence"]),
        "sync": {"observations": repo.sequence_state(_obs_table(), sid), "events": repo.sequence_state(_events_table(), sid)},
    }


def _events_table():
    from . import db
    return db.events


def _obs_table():
    from . import db
    return db.observations


def derive_summary(repo: Repo, session: dict[str, Any]) -> dict[str, Any]:
    """Cloud-side fallback summary built from stored observations (used when the device never sent one)."""
    sid = session["id"]
    rows = repo.list_observations(sid, 0, 100_000)
    observations = _obs_models(rows)
    metrics = ScoringEngine().metrics(observations, len(repo.list_interventions(sid)))
    end = utc(session.get("ended_at")) or now()
    duration = max(0.0, (end - utc(session["started_at"])).total_seconds())
    observed = metrics.aligned_seconds + metrics.supporting_seconds + metrics.neutral_seconds + metrics.distraction_seconds + metrics.unknown_seconds
    segments = [s.to_dict() for s in TaskSegmenter().segment(observations)]
    return {"schema_version": 1, "goal": session["goal"], "duration_seconds": duration,
            "active_seconds": observed, "away_seconds": max(0.0, duration - observed),
            "goal_alignment": metrics.goal_alignment, "focus_continuity": metrics.focus_continuity,
            "context_stability": metrics.context_stability, "progress": metrics.progress,
            "session_score": metrics.session_score, "coverage": metrics.coverage, "confidence": min(1.0, metrics.confidence),
            "segments": segments[:2000], "blockers": [], "drift_periods": [], "interventions": [],
            "recommendations": [], "extra": {"derived": True, "observations": len(observations)}}


def _agent_section(repo: Repo, sid: str) -> dict[str, Any]:
    tasks = [e["data"] for e in repo.list_entities(sid, "task", limit=500)]
    seconds = 0.0
    for task in tasks:
        started, finished = task.get("started_at"), task.get("completed_at")
        if started and finished:
            seconds += max(0.0, (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds())
    counts = {name: sum(1 for t in tasks if t.get("status") == name) for name in ("completed", "failed", "cancelled")}
    return {"tasks_delegated": len(tasks), **{f"tasks_{k}": v for k, v in counts.items()},
            "agent_execution_seconds": round(seconds, 1),
            "timeline": [{"task_id": t["id"], "instruction": t.get("instruction"), "status": t.get("status"),
                          "start": t.get("started_at"), "end": t.get("completed_at"),
                          "summary": (t.get("result") or {}).get("summary")} for t in tasks], "tasks": tasks}


def build_report(repo: Repo, session: dict[str, Any]) -> dict[str, Any]:
    sid = session["id"]
    stored = repo.latest_summary(sid)
    summary = stored["summary"] if stored else derive_summary(repo, session)
    source = stored["source"] if stored else "cloud-derived"
    recs = [e["data"] for e in repo.list_entities(sid, "recommendation", limit=500)]
    approvals = [e["data"] for e in repo.list_entities(sid, "approval", limit=500)]
    interventions = [intervention_out(r) for r in repo.list_interventions(sid)]
    agent = _agent_section(repo, sid)
    return {
        "session": session_view(repo, session), "source": source, "summary": summary,
        "human": {"goal_alignment": summary.get("goal_alignment"), "focus_continuity": summary.get("focus_continuity"),
                  "context_stability": summary.get("context_stability"), "progress": summary.get("progress"),
                  "active_seconds": summary.get("active_seconds"), "away_seconds": summary.get("away_seconds"),
                  "segments": summary.get("segments", [])},
        "agent": agent,
        "recommendations": {"generated": len(recs), "accepted": sum(r.get("status") == "accepted" for r in recs),
                            "dismissed": sum(r.get("status") == "dismissed" for r in recs),
                            "delegated": sum(1 for t in agent["tasks"] if t.get("created_from") == "recommendation"),
                            "items": recs},
        "approvals": {"requested": len(approvals), "approved": sum(a.get("status") == "approved" for a in approvals),
                      "denied": sum(a.get("status") == "denied" for a in approvals), "items": approvals},
        "voice_interventions": [i for i in interventions if i["channel"] == "voice"],
        "interventions": interventions, "goal_history": goal_history(repo, sid),
        "subtasks": sorted((e["data"] for e in repo.list_entities(sid, "subtask", limit=200)), key=lambda s: s.get("position", 0)),
        "blockers": summary.get("blockers", []), "drift_periods": summary.get("drift_periods", []),
    }

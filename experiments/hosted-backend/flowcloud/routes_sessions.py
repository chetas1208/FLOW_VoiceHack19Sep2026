"""Session lifecycle, idempotent ingestion and read models."""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, ValidationError

from ..flow import remote_models as rm
from . import db, views
from .core import (ApiError, Cloud, Principal, cloud_of, command_out, device_principal, entity_out, event_out, limit,
                   not_found, principal)
from .observability import bind, span
from .repo import iso, now, utc
from .schemas import (EventBatch, EventIn, InterventionIn, ObservationBatch, ObservationIn, SegmentIn, SessionCreate,
                      StopRequest, SummaryIn, Strict, bounded_json)

router = APIRouter()
log = logging.getLogger("flow.sessions")
ENTITY_KINDS = {"task", "approval", "recommendation", "subtask", "goal_version", "chat", "runtime_state"}
TERMINAL = {"completed"}


# ---- access helpers ----------------------------------------------------------------------------
def own_session(cloud: Cloud, who: Principal, session_id: str) -> dict[str, Any]:
    session = cloud.repo.get_session(who.user_id, session_id)
    if not session:
        raise not_found("session")
    bind(session_id=session_id)
    return session


def writable_session(cloud: Cloud, who: Principal, session_id: str) -> dict[str, Any]:
    session = own_session(cloud, who, session_id)
    if who.kind != "device" or session["device_id"] != who.device_id:
        raise ApiError(403, "forbidden", "only the owning device may write to this session")
    limit(cloud, f"ingest:{who.device_id}", 1200)
    return session


def _cursor_encode(row: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(f"{iso(row['started_at'])}|{row['id']}".encode()).decode()


def _cursor_decode(cursor: str | None) -> tuple[datetime, str] | None:
    if not cursor:
        return None
    try:
        started, _, sid = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromisoformat(started), sid
    except Exception as exc:
        raise ApiError(422, "validation_error", "invalid cursor") from exc


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(422, "validation_error", "invalid timestamp filter") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---- lifecycle ---------------------------------------------------------------------------------
@router.post("/v1/sessions", status_code=201)
def create_session(body: SessionCreate, request: Request, who: Principal = Depends(device_principal)):
    cloud = cloud_of(request)
    limit(cloud, f"session-create:{who.device_id}", 60)
    try:
        session, created = cloud.repo.create_session(who.user_id, who.device_id, body.id, body.goal, body.started_at, body.metadata)
    except PermissionError as exc:
        raise ApiError(409, "conflict", "session id already in use") from exc
    if not created and session["device_id"] != who.device_id:
        raise ApiError(409, "conflict", "session belongs to another device")
    if created:
        cloud.metrics.inc("flow_sessions_created_total")
        cloud.bus.publish(f"u:{who.user_id}", {"type": "session", "session": views.session_view(cloud.repo, session)})
    from fastapi.responses import JSONResponse
    return JSONResponse(views.session_view(cloud.repo, session), status_code=201 if created else 200)


@router.get("/v1/sessions")
def list_sessions(request: Request, status: str | None = None, device_id: str | None = None, since: str | None = None,
                  until: str | None = None, limit_: int = Query(25, alias="limit", ge=1, le=100),
                  cursor: str | None = None, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    rows = cloud.repo.list_sessions(who.user_id, status=status, device_id=device_id, since=_parse_time(since),
                                    until=_parse_time(until), limit=limit_ + 1, cursor=_cursor_decode(cursor))
    page = rows[:limit_]
    names = {d["id"]: d["name"] for d in cloud.repo.list_devices(who.user_id)}
    items = [views.session_out(r, names.get(r["device_id"]), views.runtime_state(cloud.repo, r["id"])) for r in page]
    return {"items": items, "next_cursor": _cursor_encode(page[-1]) if len(rows) > limit_ else None}


@router.get("/v1/sessions/{session_id}")
def get_session(session_id: str, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    return views.session_detail(cloud.repo, own_session(cloud, who, session_id))


@router.get("/v1/sessions/{session_id}/live")
def live(session_id: str, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    return views.live_view(cloud.repo, own_session(cloud, who, session_id))


@router.get("/v1/sessions/{session_id}/report")
def report(session_id: str, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    return views.build_report(cloud.repo, own_session(cloud, who, session_id))


@router.get("/v1/sessions/{session_id}/observations")
def list_observations(session_id: str, request: Request, after_sequence: int = Query(0, ge=0),
                      limit_: int = Query(200, alias="limit", ge=1, le=500), who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    own_session(cloud, who, session_id)
    rows = cloud.repo.list_observations(session_id, after_sequence, limit_)
    items = [{"id": r["id"], "sequence": r["sequence"], "timestamp": iso(r["client_timestamp"]),
              "received_at": iso(r["server_received_at"]), "activity": r["activity"], "category": r["category"],
              "goal_alignment": r["goal_alignment"], "progress_signal": r["progress_signal"], "confidence": r["confidence"],
              "task_phase": r["task_phase"], "application": r["application"], "activity_type": r["activity_type"],
              "source": r["source"], "blocker": r["blocker"]} for r in rows]
    return {"items": items, "next_after_sequence": items[-1]["sequence"] if len(items) == limit_ else None}


@router.get("/v1/sessions/{session_id}/events")
def list_events(session_id: str, request: Request, after: int = Query(0, ge=0),
                limit_: int = Query(500, alias="limit", ge=1, le=1000), who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    own_session(cloud, who, session_id)
    items = [event_out(r) for r in cloud.repo.list_events(session_id, after, limit_)]
    return {"items": items, "next_after": items[-1]["sequence"] if len(items) == limit_ else None}


@router.get("/v1/sessions/{session_id}/entities")
def list_entities(session_id: str, request: Request, kind: str | None = None, status: str | None = None,
                  limit_: int = Query(100, alias="limit", ge=1, le=500), who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    own_session(cloud, who, session_id)
    if kind and kind not in ENTITY_KINDS:
        raise ApiError(422, "validation_error", "unknown entity kind")
    return {"items": [entity_out(r) for r in cloud.repo.list_entities(session_id, kind, status, limit_)]}


@router.get("/v1/sessions/{session_id}/commands")
def session_commands(session_id: str, request: Request, limit_: int = Query(100, alias="limit", ge=1, le=200),
                     who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    own_session(cloud, who, session_id)
    return {"items": [command_out(r) for r in cloud.repo.list_commands(who.user_id, session_id, limit_)]}


@router.get("/v1/approvals")
def approvals(request: Request, status: str = "pending", who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    if status != "pending":
        raise ApiError(422, "validation_error", "only status=pending is supported")
    items = []
    for row in cloud.repo.pending_approvals(who.user_id):
        items.append({**entity_out(row), "session_id": row["session_id"]})
    return {"items": items}


# ---- ingestion ---------------------------------------------------------------------------------
def _sync(cloud: Cloud, session_id: str) -> dict[str, Any]:
    return {"observations": cloud.repo.sequence_state(db.observations, session_id),
            "events": cloud.repo.sequence_state(db.events, session_id)}


def _status_of(results: list[dict[str, Any]]) -> str:
    return "created" if any(r["status"] == "created" for r in results) else "duplicate"


@router.post("/v1/sessions/{session_id}/observations")
def add_observation(session_id: str, body: ObservationIn, request: Request, who: Principal = Depends(principal)):
    return _ingest_observations(request, session_id, [body], who, single=True)


@router.post("/v1/sessions/{session_id}/observations:batch")
def add_observation_batch(session_id: str, body: ObservationBatch, request: Request, who: Principal = Depends(principal)):
    return _ingest_observations(request, session_id, body.observations, who, single=False)


def _ingest_observations(request: Request, session_id: str, items: list[ObservationIn], who: Principal, single: bool):
    from fastapi.responses import JSONResponse
    cloud = cloud_of(request)
    writable_session(cloud, who, session_id)
    if len({i.sequence for i in items}) != len(items) or len({i.id for i in items}) != len(items):
        raise ApiError(422, "validation_error", "duplicate ids or sequences inside one batch")
    with span("ingest.observations", count=len(items)):
        results = cloud.repo.insert_observations(session_id, [i.row() for i in items])
    created = sum(r["status"] == "created" for r in results)
    cloud.metrics.inc("flow_observations_ingested_total", created)
    sync = _sync(cloud, session_id)
    if sync["observations"]["missing"]:
        log.warning("observation sequence gap", extra={"fields": {"missing": sync["observations"]["missing"][:10]}})
    if single:
        status = results[0]["status"]
        if status == "conflict":
            raise ApiError(409, "conflict", "sequence already used by another observation")
        return JSONResponse({"status": status, "id": results[0]["id"], "sequence": results[0]["sequence"], "sync": sync},
                            status_code=201 if status == "created" else 200)
    return {"results": results, "sync": sync}


@router.post("/v1/sessions/{session_id}/events")
def add_event(session_id: str, body: EventIn, request: Request, who: Principal = Depends(principal)):
    return _ingest_events(request, session_id, [body], who, single=True)


@router.post("/v1/sessions/{session_id}/events:batch")
def add_event_batch(session_id: str, body: EventBatch, request: Request, who: Principal = Depends(principal)):
    return _ingest_events(request, session_id, body.events, who, single=False)


def ingest_events(cloud: Cloud, session: dict[str, Any], items: list[EventIn]) -> list[dict[str, Any]]:
    """Shared by HTTP and the device WebSocket: persist, apply status effects, publish live."""
    sid = session["id"]
    results = cloud.repo.insert_events(sid, [i.row() for i in items])
    by_id = {i.id: i for i in items}
    for result in results:
        if result["status"] != "created":
            continue
        item = by_id[result["id"]]
        frame = {"event_id": item.id, "session_id": sid, "sequence": item.sequence, "type": item.type,
                 "timestamp": iso(utc(item.timestamp)), "received_at": iso(now()), "data": item.data}
        _apply_event_effects(cloud, session, item)
        cloud.bus.publish(f"s:{sid}", {"type": "event", "event": frame})
    cloud.metrics.inc("flow_events_ingested_total", sum(r["status"] == "created" for r in results))
    return results


def _apply_event_effects(cloud: Cloud, session: dict[str, Any], item: EventIn) -> None:
    repo, sid = cloud.repo, session["id"]
    status = {"session.paused": "paused", "session.resumed": "active", "session.completed": "completed"}.get(item.type)
    if status:
        repo.set_session_status(sid, status, item.sequence, utc(item.timestamp) if status == "completed" else None)
        cloud.bus.publish(f"u:{session['user_id']}", {"type": "session", "session": views.session_view(repo, repo.get_session(session["user_id"], sid))})
    elif item.type == "goal.updated" and isinstance(item.data.get("goal"), str):
        repo.set_session_runtime(sid, goal=item.data["goal"][:2000], goal_version=int(item.data.get("version") or 1))


def _ingest_events(request: Request, session_id: str, items: list[EventIn], who: Principal, single: bool):
    from fastapi.responses import JSONResponse
    cloud = cloud_of(request)
    session = writable_session(cloud, who, session_id)
    if len({i.sequence for i in items}) != len(items) or len({i.id for i in items}) != len(items):
        raise ApiError(422, "validation_error", "duplicate ids or sequences inside one batch")
    with span("ingest.events", count=len(items)):
        results = ingest_events(cloud, session, items)
    sync = _sync(cloud, session_id)
    if single:
        status = results[0]["status"]
        if status == "conflict":
            raise ApiError(409, "conflict", "sequence already used by another event")
        return JSONResponse({"status": status, "id": results[0]["id"], "sequence": results[0]["sequence"], "sync": sync},
                            status_code=201 if status == "created" else 200)
    return {"results": results, "sync": sync}


@router.post("/v1/sessions/{session_id}/interventions")
def add_intervention(session_id: str, body: InterventionIn, request: Request, who: Principal = Depends(principal)):
    from fastapi.responses import JSONResponse
    cloud = cloud_of(request)
    writable_session(cloud, who, session_id)
    status = cloud.repo.insert_intervention(session_id, body.row())
    return JSONResponse({"status": status, "id": body.id}, status_code=201 if status == "created" else 200)


@router.post("/v1/sessions/{session_id}/segments")
def add_segment(session_id: str, body: SegmentIn, request: Request, who: Principal = Depends(principal)):
    from fastapi.responses import JSONResponse
    cloud = cloud_of(request)
    writable_session(cloud, who, session_id)
    status = cloud.repo.upsert_segment(session_id, body.row())
    return JSONResponse({"status": status, "id": body.id}, status_code=201 if status == "created" else 200)


class EntityItem(Strict):
    kind: str
    id: str = Field(pattern=r"^[A-Za-z0-9_\-.:]{1,80}$")
    revision: int = Field(ge=1, le=1_000_000)
    data: dict[str, Any]


class EntityBatch(Strict):
    items: list[EntityItem] = Field(min_length=1, max_length=100)


_ENTITY_MODELS = {"task": rm.DelegatedTask, "approval": rm.ActionApproval, "recommendation": rm.ActionRecommendation,
                  "subtask": rm.Subtask, "goal_version": rm.GoalVersion}


def _validate_entity(item: EntityItem) -> str | None:
    if item.kind not in ENTITY_KINDS:
        raise ApiError(422, "validation_error", f"unknown entity kind {item.kind!r}")
    try:
        bounded_json(item.data, 32_768)
        model = _ENTITY_MODELS.get(item.kind)
        if model:
            parsed = model.from_dict(item.data)
            if item.kind == "goal_version":
                if item.id != str(parsed.version):
                    raise ValueError("goal_version id must equal its version")
            elif parsed.id != item.id:
                raise ValueError("entity id mismatch")
        elif item.kind == "runtime_state":
            rm.RuntimeStatus(item.data.get("status"))
        elif item.kind == "chat" and not isinstance(item.data.get("question"), str):
            raise ValueError("chat entries need a question")
    except (ValueError, TypeError, KeyError) as exc:
        raise ApiError(422, "validation_error", f"invalid {item.kind}: {exc}") from exc
    status = item.data.get("status")
    return str(status)[:24] if status is not None else None


@router.post("/v1/sessions/{session_id}/entities:batch")
def add_entities(session_id: str, body: EntityBatch, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    session = writable_session(cloud, who, session_id)
    validated = [(item, _validate_entity(item)) for item in body.items]
    results = []
    for item, status in validated:
        outcome = cloud.repo.upsert_entity(session_id, item.kind, item.id, item.revision, status, item.data)
        results.append({"kind": item.kind, "id": item.id, "status": outcome})
        if outcome in {"created", "updated"}:
            _entity_side_effects(cloud, session, item, status)
    return {"results": results}


def _entity_side_effects(cloud: Cloud, session: dict[str, Any], item: EntityItem, status: str | None) -> None:
    sid, user = session["id"], session["user_id"]
    if item.kind == "approval":
        cloud.bus.publish(f"u:{user}", {"type": "approval", "session_id": sid, "approval": item.data})
    elif item.kind == "runtime_state" and status and status != "completed":
        cloud.repo.set_session_runtime(sid, status=status, goal_version=item.data.get("goal_version"))
        cloud.bus.publish(f"u:{user}", {"type": "session", "session": views.session_view(cloud.repo, cloud.repo.get_session(user, sid))})
    elif item.kind == "goal_version":
        cloud.repo.set_session_runtime(sid, goal=str(item.data.get("goal", ""))[:2000] or None, goal_version=int(item.data["version"]))


@router.put("/v1/sessions/{session_id}/summary")
def put_summary(session_id: str, body: SummaryIn, request: Request, who: Principal = Depends(principal)):
    from fastapi.responses import JSONResponse
    cloud = cloud_of(request)
    writable_session(cloud, who, session_id)
    version, created = cloud.repo.add_summary(session_id, body.model_dump(mode="json"), "device")
    return JSONResponse({"status": "created" if created else "duplicate", "version": version}, status_code=201 if created else 200)


@router.post("/v1/sessions/{session_id}/stop")
def stop_session(session_id: str, request: Request, body: StopRequest | None = None, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    session = writable_session(cloud, who, session_id)
    body = body or StopRequest()
    ended = utc(body.ended_at) or now()
    already = session["status"] == "completed"
    session = cloud.repo.complete_session(session_id, ended)
    if body.summary is not None:
        cloud.repo.add_summary(session_id, body.summary.model_dump(mode="json"), "device")
    else:
        cloud.repo.enqueue_job("ensure_summary", {"session_id": session_id}, run_after=now().replace(microsecond=0) + __import__("datetime").timedelta(seconds=45),
                               dedupe_key=f"ensure_summary:{session_id}")
    if not already:
        cloud.bus.publish(f"u:{who.user_id}", {"type": "session", "session": views.session_view(cloud.repo, session)})
    return views.session_view(cloud.repo, session)

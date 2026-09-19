"""FastAPI router for FLOW, mounted into the existing local platform API."""

from __future__ import annotations

import asyncio
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import ActivityCategory, InterventionChannel, InterventionStatus, Observation
from .auth import CLIAuthRequest, local_token
from .config import web_endpoint
from .session_manager import InvalidTransition, SessionManager, SessionNotFound, _id

router = APIRouter(tags=["FLOW"])
_auth_requests: dict[str, dict[str, str]] = {}


class SessionCreate(BaseModel):
    goal: str = Field(min_length=1, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime | None = None
    source: str = Field(min_length=1, max_length=100)
    app_name: str | None = Field(default=None, max_length=300)
    window_title: str | None = Field(default=None, max_length=1000)
    activity_summary: str | None = Field(default=None, max_length=4000)
    category: ActivityCategory = ActivityCategory.UNKNOWN
    goal_alignment: float | None = Field(default=None, ge=0, le=1)
    progress_signal: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AuthStart(BaseModel):
    device_id: str = Field(min_length=1, max_length=200)


class AuthApprove(BaseModel):
    state: str = Field(min_length=1, max_length=200)


class AuthToken(BaseModel):
    state: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=200)
    code_verifier: str = Field(min_length=20, max_length=200)


@router.post("/v1/cli/auth/start")
def auth_start(payload: AuthStart):
    request = CLIAuthRequest.create(payload.device_id)
    _auth_requests[request.state] = {"device_id": payload.device_id, "challenge": request.challenge,
                                     "nonce": request.nonce, "code": ""}
    return {"state": request.state, "nonce": request.nonce, "authorization_url": request.authorization_url(web_endpoint())}


@router.post("/v1/cli/auth/approve")
def auth_approve(payload: AuthApprove):
    record = _auth_requests.get(payload.state)
    if not record:
        raise HTTPException(404, "authorization request not found")
    record["code"] = secrets.token_urlsafe(24)
    return {"code": record["code"], "state": payload.state}


@router.post("/v1/cli/auth/token")
def auth_token(payload: AuthToken):
    record = _auth_requests.pop(payload.state, None)
    if not record or not record["code"] or not secrets.compare_digest(record["code"], payload.code):
        raise HTTPException(400, "invalid authorization grant")
    import base64, hashlib
    challenge = base64.urlsafe_b64encode(hashlib.sha256(payload.code_verifier.encode()).digest()).rstrip(b"=").decode()
    if not secrets.compare_digest(challenge, record["challenge"]):
        raise HTTPException(400, "invalid PKCE verifier")
    return {"access_token": local_token(), "token_type": "Bearer", "expires_in": 3600,
            "device_id": record["device_id"]}


@router.get("/v1/me")
def me(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "authentication required")
    return {"id": "local-user", "device_count": 1}


def manager(request: Request) -> SessionManager:
    service = getattr(request.app.state, "flow_manager", None)
    return service or SessionManager()


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, SessionNotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, InvalidTransition):
        return HTTPException(409, str(exc))
    return HTTPException(422, str(exc))


def _response(service: SessionManager, session):
    return {**session.to_dict(), "metrics": service.metrics(session.id).to_dict()}


@router.post("/flow/sessions", status_code=201)
def create_session(payload: SessionCreate, request: Request):
    try:
        service = manager(request)
        return _response(service, service.start_session(payload.goal, payload.metadata))
    except (ValueError, SessionNotFound, InvalidTransition) as exc:
        raise _error(exc) from exc


@router.post("/v1/sessions", status_code=201)
def create_v1_session(payload: SessionCreate, request: Request):
    return create_session(payload, request)


@router.get("/flow/sessions")
def list_sessions(request: Request, status: str | None = None, limit: int = 50):
    try:
        from .models import SessionStatus
        parsed = SessionStatus(status) if status else None
        service = manager(request)
        return [_response(service, item) for item in service.list_sessions(parsed, limit)]
    except (ValueError, SessionNotFound, InvalidTransition) as exc:
        raise _error(exc) from exc


@router.get("/flow/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    try:
        service = manager(request)
        return service.report(session_id)
    except (ValueError, SessionNotFound, InvalidTransition) as exc:
        raise _error(exc) from exc


@router.get("/v1/sessions/{session_id}")
def get_v1_session(session_id: str, request: Request):
    return get_session(session_id, request)


def _transition(session_id: str, request: Request, operation):
    try:
        service = manager(request)
        return _response(service, operation(service, session_id))
    except (ValueError, SessionNotFound, InvalidTransition) as exc:
        raise _error(exc) from exc


@router.post("/flow/sessions/{session_id}/pause")
def pause_session(session_id: str, request: Request):
    return _transition(session_id, request, lambda service, sid: service.pause_session(sid))


@router.post("/flow/sessions/{session_id}/resume")
def resume_session(session_id: str, request: Request):
    return _transition(session_id, request, lambda service, sid: service.resume_session(sid))


@router.post("/flow/sessions/{session_id}/stop")
def stop_session(session_id: str, request: Request):
    return _transition(session_id, request, lambda service, sid: service.stop_session(sid))


@router.post("/v1/sessions/{session_id}/stop")
def stop_v1_session(session_id: str, request: Request):
    return stop_session(session_id, request)


@router.get("/flow/sessions/{session_id}/observations")
def observations(session_id: str, request: Request):
    try:
        return [item.to_dict() for item in manager(request).observations(session_id)]
    except (ValueError, SessionNotFound) as exc:
        raise _error(exc) from exc


@router.post("/flow/sessions/{session_id}/observations", status_code=201)
def add_observation(session_id: str, payload: ObservationCreate, request: Request):
    try:
        service = manager(request)
        item = Observation(_id("obs"), session_id, payload.timestamp or datetime.now().astimezone(), payload.source,
                           payload.app_name, payload.window_title, payload.activity_summary, payload.category,
                           payload.goal_alignment, payload.progress_signal, payload.confidence, payload.metadata)
        return service.add_observation(session_id, item).to_dict()
    except (ValueError, SessionNotFound, InvalidTransition) as exc:
        raise _error(exc) from exc


@router.post("/v1/sessions/{session_id}/observations", status_code=201)
def add_v1_observation(session_id: str, payload: ObservationCreate, request: Request):
    return add_observation(session_id, payload, request)


@router.get("/flow/sessions/{session_id}/interventions")
def interventions(session_id: str, request: Request):
    try:
        return [item.to_dict() for item in manager(request).interventions(session_id)]
    except (ValueError, SessionNotFound) as exc:
        raise _error(exc) from exc


@router.get("/flow/sessions/{session_id}/events")
def events(session_id: str, request: Request, after: int = 0):
    try:
        return [item.to_dict() for item in manager(request).events(session_id, after)]
    except (ValueError, SessionNotFound) as exc:
        raise _error(exc) from exc


@router.get("/flow", response_class=HTMLResponse)
def flow_dashboard(request: Request):
    sessions = manager(request).list_sessions(limit=50)
    rows = "".join(f"<tr><td><code>{item.id}</code></td><td>{item.goal}</td><td>{item.status.value}</td>"
                   f"<td><a href='/flow/session/{item.id}'>inspect</a></td></tr>" for item in sessions)
    return HTMLResponse("<!doctype html><html lang='en'><meta charset='utf-8'><title>FLOW</title>"
                        "<style>body{font:16px system-ui;max-width:1100px;margin:3rem auto;padding:0 1rem}"
                        "table{width:100%;border-collapse:collapse}td,th{padding:.7rem;border-bottom:1px solid #ddd;text-align:left}"
                        "code{font-size:.8rem}</style><h1>FLOW</h1><p>Local developer session observability.</p>"
                        "<table><tr><th>ID</th><th>Goal</th><th>Status</th><th></th></tr>" + rows + "</table></html>")


@router.get("/flow/session/{session_id}", response_class=HTMLResponse)
def flow_session_debug(session_id: str, request: Request):
    try:
        report = manager(request).report(session_id)
    except SessionNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    return HTMLResponse("<!doctype html><html lang='en'><meta charset='utf-8'><title>FLOW session</title>"
                        "<style>body{font:16px system-ui;max-width:1100px;margin:3rem auto;padding:0 1rem}pre{background:#f5f5f5;padding:1rem;overflow:auto}</style>"
                        f"<h1>FLOW session</h1><p><strong>{report['goal']}</strong></p><pre>{__import__('html').escape(__import__('json').dumps(report, indent=2))}</pre></html>")


@router.websocket("/ws/flow/sessions/{session_id}")
async def event_stream(websocket: WebSocket, session_id: str):
    await websocket.accept()
    service = getattr(websocket.app.state, "flow_manager", None) or SessionManager()
    try:
        service.get_session(session_id)
        after = int(websocket.query_params.get("after", "0"))
        for item in service.events(session_id, after):
            await websocket.send_json(item.to_dict())
        queue, close = service.hub.subscribe(session_id)
        try:
            while True:
                await websocket.send_json((await queue.get()).to_dict())
        finally:
            close()
    except (SessionNotFound, ValueError):
        await websocket.close(code=1008, reason="session not found")
    except WebSocketDisconnect:
        pass

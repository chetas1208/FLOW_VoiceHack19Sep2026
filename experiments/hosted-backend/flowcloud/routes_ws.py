"""WebSocket endpoints: device command channel and viewer streams (session and user)."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from ..flow import remote_models as rm
from . import views
from .core import (ApiError, Cloud, Principal, authenticate_token, command_out, event_out, presence_view)
from .repo import iso, now
from .routes_remote import apply_ack, publish_command
from .routes_sessions import ingest_events
from .schemas import EventIn

router = APIRouter()
log = logging.getLogger("flow.ws")
AUTH_TIMEOUT = 10.0
PING_SECONDS = 25.0
CLOSE_UNAUTHORIZED, CLOSE_FORBIDDEN, CLOSE_POLICY = 4401, 4403, 1008


def _origin_allowed(cloud: Cloud, websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return True
    allowed = cloud.settings.allowed_origins
    return origin in allowed if allowed else not cloud.settings.is_production


async def _authenticate(websocket: WebSocket, cloud: Cloud) -> tuple[Principal, dict[str, Any]] | None:
    """Header auth for native clients, or a first `auth` frame for browsers. Never a query-string token."""
    if not _origin_allowed(cloud, websocket):
        await websocket.close(code=CLOSE_POLICY, reason="origin not allowed")
        return None
    await websocket.accept()
    first: dict[str, Any] = {}
    header = websocket.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    try:
        if token is None:
            first = await asyncio.wait_for(websocket.receive_json(), AUTH_TIMEOUT)
            if first.get("type") != "auth" or not isinstance(first.get("token"), str):
                raise ApiError(401, "unauthorized", "auth frame required")
            token = first["token"]
        who = await asyncio.to_thread(authenticate_token, cloud, token)
        return who, first
    except (ApiError, asyncio.TimeoutError, ValueError, WebSocketDisconnect):
        try:
            await websocket.close(code=CLOSE_UNAUTHORIZED, reason="unauthorized")
        except RuntimeError:
            pass
        return None


# ---- device channel ----------------------------------------------------------------------------
async def _push_deliverable(cloud: Cloud, websocket: WebSocket, device_id: str, sent: set[str]) -> None:
    rows = await asyncio.to_thread(cloud.repo.deliverable_commands, device_id)
    for row in rows:
        if row["command_id"] in sent:
            continue
        updated = await asyncio.to_thread(cloud.repo.mark_delivered, row["command_id"])
        sent.add(row["command_id"])
        await websocket.send_json({"type": "command", "command": command_out(updated)})
        if row["status"] == "queued":
            publish_command(cloud, updated)


async def _announce_presence(cloud: Cloud, user_id: str, device_id: str) -> None:
    row = await asyncio.to_thread(cloud.repo.get_presence, device_id)
    view = presence_view(row)
    cloud.bus.publish(f"u:{user_id}", {"type": "presence", "device_id": device_id, "presence": view})
    for session_id in view["active_sessions"]:
        cloud.bus.publish(f"s:{session_id}", {"type": "presence", "device_id": device_id, "presence": view})


@router.websocket("/v1/ws/device")
async def device_channel(websocket: WebSocket) -> None:
    cloud: Cloud = websocket.app.state.cloud
    authed = await _authenticate(websocket, cloud)
    if not authed:
        return
    who, _ = authed
    if who.kind != "device":
        await websocket.close(code=CLOSE_FORBIDDEN, reason="device token required")
        return
    device_id, connection_id = who.device_id, uuid.uuid4().hex
    await asyncio.to_thread(cloud.repo.presence_seen, device_id, connection_id, {}, [], None, True)
    sub = await cloud.bus.subscribe(f"d:{device_id}")
    sent: set[str] = set()
    last_view: dict[str, Any] | None = None
    try:
        await websocket.send_json({"type": "ready", "server_time": iso(now())})
        await _announce_presence(cloud, who.user_id, device_id)
        await _push_deliverable(cloud, websocket, device_id, sent)

        async def inbound() -> None:
            nonlocal last_view
            last_check = time.monotonic()
            while True:
                frame = await websocket.receive_json()
                kind = frame.get("type")
                if kind in {"hello", "heartbeat"}:
                    health = frame.get("health") if isinstance(frame.get("health"), dict) else {}
                    active = [s for s in (frame.get("active_sessions") or []) if isinstance(s, str)][:20]
                    await asyncio.to_thread(cloud.repo.presence_seen, device_id, connection_id, health, active,
                                            frame.get("flow_version"), True)
                    view = presence_view(await asyncio.to_thread(cloud.repo.get_presence, device_id))
                    if view != last_view:
                        last_view = view
                        await _announce_presence(cloud, who.user_id, device_id)
                    if kind == "hello":
                        await _push_deliverable(cloud, websocket, device_id, sent)
                    if time.monotonic() - last_check > 30:
                        last_check = time.monotonic()
                        found = await asyncio.to_thread(cloud.repo.device_status, device_id)
                        if not found or found[0]["revoked_at"]:
                            await websocket.send_json({"type": "revoked"})
                            await websocket.close(code=CLOSE_UNAUTHORIZED)
                            return
                elif kind == "ack":
                    try:
                        await asyncio.to_thread(apply_ack, cloud, device_id, str(frame.get("command_id")),
                                                rm.CommandStatus(frame.get("status")), frame.get("result"))
                    except (ApiError, ValueError):
                        log.warning("rejected ack", extra={"fields": {"device_id": device_id}})
                elif kind == "events":
                    await _ingest_ws_events(cloud, who, frame)

        async def outbound() -> None:
            while True:
                message = await sub.get(PING_SECONDS)
                if message is None:
                    await websocket.send_json({"type": "ping"})
                    await asyncio.to_thread(cloud_sweep, cloud)
                    await _push_deliverable(cloud, websocket, device_id, sent)
                    continue
                if message.get("type") == "revoked":
                    await websocket.send_json({"type": "revoked"})
                    await websocket.close(code=CLOSE_UNAUTHORIZED)
                    return
                if message.get("type") == "command":
                    await _push_deliverable(cloud, websocket, device_id, sent)

        tasks = [asyncio.create_task(inbound()), asyncio.create_task(outbound())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, OverflowError)):
                raise exc
    except WebSocketDisconnect:
        pass
    finally:
        await sub.close()
        if await asyncio.to_thread(cloud.repo.presence_disconnect, device_id, connection_id):
            await _announce_presence(cloud, who.user_id, device_id)


def cloud_sweep(cloud: Cloud) -> None:
    for row in cloud.repo.expire_commands():
        publish_command(cloud, row)


async def _ingest_ws_events(cloud: Cloud, who: Principal, frame: dict[str, Any]) -> None:
    session_id = frame.get("session_id")
    raw = frame.get("events")
    if not isinstance(session_id, str) or not isinstance(raw, list) or not 0 < len(raw) <= 100:
        return
    session = await asyncio.to_thread(cloud.repo.get_session, who.user_id, session_id)
    if not session or session["device_id"] != who.device_id:
        return
    try:
        items = [EventIn.model_validate(item) for item in raw]
    except ValidationError:
        return
    await asyncio.to_thread(ingest_events, cloud, session, items)


# ---- viewer channels ---------------------------------------------------------------------------
async def _viewer_loop(websocket: WebSocket, cloud: Cloud, who: Principal, sub, handler) -> None:
    """Send frames until the token expires (4401), the socket closes, or the subscriber lags."""
    while True:
        remaining = who.expires_at - time.time()
        if remaining <= 0:
            await websocket.close(code=CLOSE_UNAUTHORIZED, reason="token expired")
            return
        try:
            message = await sub.get(min(PING_SECONDS, max(remaining, 0.1)))
        except OverflowError:
            await websocket.close(code=1013, reason="slow consumer; reconnect with last_sequence")
            return
        if message is None:
            await websocket.send_json({"type": "ping"})
            continue
        await handler(message)


@router.websocket("/v1/ws/sessions/{session_id}")
async def session_stream(websocket: WebSocket, session_id: str) -> None:
    cloud: Cloud = websocket.app.state.cloud
    authed = await _authenticate(websocket, cloud)
    if not authed:
        return
    who, first = authed
    session = await asyncio.to_thread(cloud.repo.get_session, who.user_id, session_id)
    if not session:
        await websocket.close(code=CLOSE_POLICY, reason="not found")
        return
    try:
        last = int(first.get("last_sequence", websocket.query_params.get("last_sequence", 0)))
    except (TypeError, ValueError):
        last = 0
    sub = await cloud.bus.subscribe(f"s:{session_id}")
    sent: set[int] = set()
    try:
        await websocket.send_json({"type": "ready", "session_id": session_id, "last_sequence": last})
        cursor = last
        while True:  # replay in pages after subscribing so no live event is missed
            rows = await asyncio.to_thread(cloud.repo.list_events, session_id, cursor, 500)
            for row in rows:
                await websocket.send_json({"type": "event", "event": event_out(row)})
                sent.add(row["sequence"])
                cursor = row["sequence"]
            if len(rows) < 500:
                break
        presence = presence_view(await asyncio.to_thread(cloud.repo.get_presence, session["device_id"]))
        await websocket.send_json({"type": "presence", "device_id": session["device_id"], "presence": presence})

        async def handle(message: dict[str, Any]) -> None:
            if message.get("type") == "event":
                sequence = message["event"]["sequence"]
                if sequence in sent or (sequence <= last):
                    return
                sent.add(sequence)
            await websocket.send_json(message)

        watcher = asyncio.create_task(_drain_client(websocket))
        pump = asyncio.create_task(_viewer_loop(websocket, cloud, who, sub, handle))
        done, pending = await asyncio.wait([watcher, pump], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                raise exc
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await sub.close()


@router.websocket("/v1/ws/user")
async def user_stream(websocket: WebSocket) -> None:
    cloud: Cloud = websocket.app.state.cloud
    authed = await _authenticate(websocket, cloud)
    if not authed:
        return
    who, _ = authed
    sub = await cloud.bus.subscribe(f"u:{who.user_id}")
    try:
        await websocket.send_json({"type": "ready"})

        async def handle(message: dict[str, Any]) -> None:
            await websocket.send_json(message)

        watcher = asyncio.create_task(_drain_client(websocket))
        pump = asyncio.create_task(_viewer_loop(websocket, cloud, who, sub, handle))
        done, pending = await asyncio.wait([watcher, pump], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, RuntimeError)):
                raise exc
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await sub.close()


async def _drain_client(websocket: WebSocket) -> None:
    while True:
        await websocket.receive_text()

"""Remote command channel: durable command ledger, acknowledgements and delivery."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from ..flow import remote_models as rm
from . import views
from .core import (ApiError, Cloud, Principal, cloud_of, command_out, limit, not_found, presence_view, principal)
from .repo import iso, now
from .routes_sessions import own_session
from .schemas import Strict, bounded_json

router = APIRouter()
log = logging.getLogger("flow.commands")
ID = re.compile(r"^[A-Za-z0-9_\-]{8,80}$")
WEB_MAX_PERMISSION = {rm.PermissionLevel.READ_ONLY, rm.PermissionLevel.SAFE_EXECUTE, rm.PermissionLevel.WRITE_PROJECT}


class CommandCreate(Strict):
    command_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{8,80}$")
    type: rm.CommandType
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_\-]{8,80}$")
    device_id: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)
    source: rm.CommandSource = rm.CommandSource.WEB


class CommandAck(Strict):
    status: rm.CommandStatus
    result: dict[str, Any] | None = None


def _text(payload: dict[str, Any], key: str, maximum: int, required: bool = True) -> str | None:
    value = payload.get(key)
    if value is None:
        if required:
            raise ApiError(422, "validation_error", f"payload.{key} is required")
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ApiError(422, "validation_error", f"payload.{key} must be a non-empty string up to {maximum} characters")
    return value


def _ident(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not re.match(r"^[A-Za-z0-9_\-.:]{1,80}$", value):
        raise ApiError(422, "validation_error", f"payload.{key} must be an id")
    return value


def validate_payload(kind: rm.CommandType, payload: dict[str, Any], source: rm.CommandSource) -> dict[str, Any]:
    bounded_json(payload, 8192)
    C = rm.CommandType
    try:
        if kind == C.START:
            _text(payload, "goal", 2000)
            if payload.get("permission_policy") is not None:
                rm.PermissionPolicy(payload["permission_policy"])
        elif kind == C.UPDATE_GOAL:
            _text(payload, "goal", 2000)
        elif kind == C.ASK:
            _text(payload, "question", 1000)
        elif kind == C.ADD_TASK:
            _text(payload, "instruction", 2000)
            level = rm.PermissionLevel(payload.get("permission_level", "safe_execute"))
            if level not in WEB_MAX_PERMISSION:
                raise ApiError(422, "validation_error", "that permission level cannot be requested remotely")
        elif kind == C.CANCEL_TASK:
            _ident(payload, "task_id")
        elif kind in {C.APPROVE_ACTION, C.DENY_ACTION}:
            _ident(payload, "approval_id")
        elif kind in {C.EXECUTE_RECOMMENDATION, C.DISMISS_RECOMMENDATION}:
            _ident(payload, "recommendation_id")
        elif kind == C.FEEDBACK_RECOMMENDATION:
            _ident(payload, "recommendation_id")
            if not isinstance(payload.get("helpful"), bool):
                raise ApiError(422, "validation_error", "payload.helpful must be boolean")
        elif kind == C.SET_PERMISSION_POLICY:
            rm.PermissionPolicy(payload.get("policy"))
        elif kind in {C.MUTE_VOICE}:
            minutes = payload.get("minutes")
            if minutes is not None and (not isinstance(minutes, int) or not 1 <= minutes <= 480):
                raise ApiError(422, "validation_error", "payload.minutes must be 1..480")
        elif kind == C.UPDATE_SUBTASKS:
            items = payload.get("subtasks")
            if not isinstance(items, list) or len(items) > 50:
                raise ApiError(422, "validation_error", "payload.subtasks must be a list of up to 50")
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("title"), str) or len(item["title"]) > 300:
                    raise ApiError(422, "validation_error", "invalid subtask")
                rm.SubtaskStatus(item.get("status", "todo"))
    except ValueError as exc:
        raise ApiError(422, "validation_error", f"invalid payload: {exc}") from exc
    return payload


def publish_command(cloud: Cloud, row: dict[str, Any]) -> None:
    out = command_out(row)
    if row.get("session_id"):
        cloud.bus.publish(f"s:{row['session_id']}", {"type": "command", "command": out})
    cloud.bus.publish(f"u:{row['user_id']}", {"type": "command", "command": out})


def sweep_expired(cloud: Cloud) -> None:
    for row in cloud.repo.expire_commands():
        publish_command(cloud, row)


@router.post("/v1/commands")
def create_command(body: CommandCreate, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    limit(cloud, f"commands:{who.user_id}", 240)
    repo = cloud.repo
    sweep_expired(cloud)
    kind = body.type
    source = rm.CommandSource.WEB if who.kind == "web" else (
        body.source if body.source != rm.CommandSource.WEB else rm.CommandSource.CLI)
    payload = validate_payload(kind, dict(body.payload), source)
    command_id = body.command_id or "cmd_" + secrets.token_hex(12)
    existing = repo.get_command(command_id, who.user_id)
    if existing:
        return JSONResponse(command_out(existing), status_code=200)

    session_id = body.session_id
    if kind in rm.DEVICE_COMMANDS:
        if not body.device_id:
            raise ApiError(422, "validation_error", "device_id is required for START")
        device = repo.get_device(body.device_id)
        if not device or device["user_id"] != who.user_id or device["revoked_at"]:
            raise not_found("device")
        device_id = device["id"]
        session_id = "ses_" + secrets.token_hex(12)
        payload = {**payload, "session_id": session_id}
    else:
        if not session_id:
            raise ApiError(422, "validation_error", "session_id is required")
        session = own_session(cloud, who, session_id)
        device_id = session["device_id"]
        if session["status"] == "completed":
            if kind == rm.CommandType.STOP:
                done = {"command_id": command_id, "user_id": who.user_id, "device_id": device_id, "session_id": session_id,
                        "source": source.value, "type": kind.value, "payload": payload, "status": "succeeded",
                        "result": {"note": "session already completed"}, "created_at": now(), "expires_at": now(),
                        "completed_at": now()}
                row, _ = repo.create_command(done)
                return JSONResponse(command_out(row), status_code=201)
            if kind != rm.CommandType.REQUEST_SUMMARY:
                raise ApiError(409, "conflict", "session is completed")
        if who.kind == "device" and who.device_id != device_id and kind in rm.DEVICE_COMMANDS:
            raise ApiError(403, "forbidden", "device mismatch")
    presence = presence_view(repo.get_presence(device_id))
    if presence["state"] == "offline" and kind not in rm.OFFLINE_QUEUEABLE:
        raise ApiError(409, "device_offline", "the device is offline; this command cannot be queued")
    created_at = now()
    values = {"command_id": command_id, "user_id": who.user_id, "device_id": device_id, "session_id": session_id,
              "source": source.value, "type": kind.value, "payload": payload, "status": "queued", "result": None,
              "created_at": created_at, "expires_at": created_at + timedelta(seconds=rm.COMMAND_TTL_SECONDS[kind]),
              "delivery_count": 0}
    try:
        row, created = repo.create_command(values)
    except PermissionError as exc:
        raise ApiError(409, "conflict", "command id already in use") from exc
    if created:
        cloud.metrics.inc("flow_commands_total", type=kind.value)
        if kind in {rm.CommandType.APPROVE_ACTION, rm.CommandType.DENY_ACTION, rm.CommandType.STOP,
                    rm.CommandType.EXECUTE_RECOMMENDATION, rm.CommandType.ADD_TASK}:
            repo.audit("command.created", user_id=who.user_id, device_id=device_id,
                       detail={"type": kind.value, "source": source.value, "session_id": session_id, "command_id": command_id})
        publish_command(cloud, row)
        cloud.bus.publish(f"d:{device_id}", {"type": "command", "command": command_out(row)})
    return JSONResponse(command_out(row), status_code=201 if created else 200)


@router.get("/v1/commands/{command_id}")
def get_command(command_id: str, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    sweep_expired(cloud)
    row = cloud.repo.get_command(command_id, who.user_id)
    if not row:
        raise not_found("command")
    return command_out(row)


@router.post("/v1/commands/{command_id}/ack")
def ack_command(command_id: str, body: CommandAck, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    if who.kind != "device":
        raise ApiError(403, "forbidden", "only the target device may acknowledge a command")
    return apply_ack(cloud, who.device_id, command_id, body.status, body.result)


def apply_ack(cloud: Cloud, device_id: str, command_id: str, status: rm.CommandStatus, result: dict[str, Any] | None) -> dict[str, Any]:
    if status not in {rm.CommandStatus.RUNNING, rm.CommandStatus.SUCCEEDED, rm.CommandStatus.FAILED, rm.CommandStatus.DENIED}:
        raise ApiError(422, "validation_error", "status must be running, succeeded, failed or denied")
    if result is not None:
        bounded_json(result, 32_768)
    row, changed = cloud.repo.ack_command(device_id, command_id, status.value, result)
    if row is None:
        raise not_found("command")
    if changed:
        publish_command(cloud, row)
    return command_out(row)

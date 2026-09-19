"""Shared application container, principals, errors and helpers for the cloud routes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import Request

from .identity import IdentityError, IdentityVerifier
from .observability import Metrics, bind
from .ratelimit import RateLimiter
from .realtime import RealtimeBus
from .repo import Repo, UserConflict, iso, now, utc
from .security import AccessTokenService, TokenError
from .settings import Settings

log = logging.getLogger("flow.cloud")
PRESENCE_TTL_SECONDS = 60


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def unauthorized(message: str = "authentication required") -> ApiError:
    return ApiError(401, "unauthorized", message, {"WWW-Authenticate": "Bearer"})


def not_found(what: str = "resource") -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


@dataclass(slots=True)
class Cloud:
    settings: Settings
    repo: Repo
    tokens: AccessTokenService
    identity: IdentityVerifier
    bus: RealtimeBus
    limiter: RateLimiter
    metrics: Metrics


@dataclass(frozen=True, slots=True)
class Principal:
    kind: str  # "device" | "web"
    user_id: str
    email: str
    expires_at: int
    device_id: str | None = None


def cloud_of(request: Request) -> Cloud:
    return request.app.state.cloud


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def limit(cloud: Cloud, key: str, per_minute: int) -> None:
    allowed = cloud.limiter.hit(key, max(1, int(per_minute * cloud.settings.rate_limit_multiplier)), 60)
    if not allowed:
        cloud.metrics.inc("flow_rate_limited_total", bucket=key.split(":")[0])
        raise ApiError(429, "rate_limited", "too many requests", {"Retry-After": "30"})


def authenticate_token(cloud: Cloud, token: str) -> Principal:
    repo = cloud.repo
    if cloud.tokens.peek_issuer(token) == cloud.settings.jwt_issuer:
        try:
            claims = cloud.tokens.verify(token)
        except TokenError as exc:
            raise unauthorized("invalid or expired token") from exc
        found = repo.device_status(claims.device_id)
        if not found:
            raise unauthorized("unknown device")
        device, user = found
        if device["revoked_at"] or user["disabled_at"] or device["user_id"] != claims.user_id:
            raise unauthorized("device authorization revoked")
        repo.touch_device(claims.device_id)
        bind(device_id=claims.device_id)
        return Principal("device", claims.user_id, user["email"], claims.expires_at, claims.device_id)
    try:
        identity = cloud.identity.verify(token)
    except IdentityError as exc:
        raise unauthorized("invalid or expired token") from exc
    try:
        user = repo.upsert_user(identity.issuer, identity.subject, identity.email, identity.name)
    except UserConflict as exc:
        raise ApiError(409, "conflict", "account conflict") from exc
    if user.get("disabled_at"):
        raise unauthorized("account disabled")
    return Principal("web", user["id"], user["email"], identity.expires_at)


def bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer ") or len(header) < 20:
        raise unauthorized()
    return header[7:].strip()


def principal(request: Request) -> Principal:
    cloud = cloud_of(request)
    found = authenticate_token(cloud, bearer(request))
    bind(user_id=found.user_id)
    return found


def device_principal(request: Request) -> Principal:
    found = principal(request)
    if found.kind != "device":
        raise ApiError(403, "forbidden", "a device token is required")
    return found


def presence_view(row: dict[str, Any] | None, at: datetime | None = None) -> dict[str, Any]:
    at = at or now()
    if not row or not row.get("connected") or not row.get("last_heartbeat_at"):
        return {"state": "offline", "last_heartbeat_at": iso(row["last_heartbeat_at"]) if row and row.get("last_heartbeat_at") else None,
                "health": (row or {}).get("health") or {}, "active_sessions": (row or {}).get("active_sessions") or []}
    fresh = at - utc(row["last_heartbeat_at"]) <= timedelta(seconds=PRESENCE_TTL_SECONDS)
    health = row.get("health") or {}
    degraded = any(str(v).lower() in {"error", "degraded", "unavailable"} for v in health.values() if isinstance(v, str))
    state = "offline" if not fresh else "degraded" if degraded else "online"
    return {"state": state, "last_heartbeat_at": iso(row["last_heartbeat_at"]), "health": health,
            "active_sessions": row.get("active_sessions") or []}


def device_out(device: dict[str, Any], presence: dict[str, Any] | None) -> dict[str, Any]:
    return {"id": device["id"], "name": device["name"], "os": device["os"], "architecture": device["architecture"],
            "flow_version": device["flow_version"], "created_at": iso(device["created_at"]),
            "last_seen_at": iso(device.get("last_seen_at")), "revoked_at": iso(device.get("revoked_at")),
            "presence": presence_view(presence)}


def session_out(session: dict[str, Any], device_name: str | None = None, runtime: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": session["id"], "goal": session["goal"], "status": session["status"], "device_id": session["device_id"],
            "device_name": device_name, "started_at": iso(session["started_at"]), "ended_at": iso(session.get("ended_at")),
            "updated_at": iso(session["updated_at"]), "goal_version": session.get("goal_version", 1),
            "runtime_state": runtime}


def event_out(row: dict[str, Any]) -> dict[str, Any]:
    return {"event_id": row["event_id"], "session_id": row["session_id"], "sequence": row["sequence"], "type": row["type"],
            "timestamp": iso(row["client_timestamp"]), "received_at": iso(row["server_received_at"]), "data": row["data"]}


def command_out(row: dict[str, Any]) -> dict[str, Any]:
    return {"command_id": row["command_id"], "type": row["type"], "user_id": row["user_id"], "device_id": row["device_id"],
            "source": row["source"], "session_id": row["session_id"], "payload": row["payload"], "status": row["status"],
            "result": row.get("result"), "created_at": iso(row["created_at"]), "expires_at": iso(row["expires_at"])}


def entity_out(row: dict[str, Any]) -> dict[str, Any]:
    return {"kind": row["kind"], "id": row["id"], "revision": row["revision"], "status": row.get("status"),
            "data": row["data"], "updated_at": iso(row["updated_at"])}

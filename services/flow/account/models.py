from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    email: str
    name: str | None = None


@dataclass(slots=True)
class Profile:
    user_id: str
    display_name: str | None = None
    timezone: str = "UTC"
    preferences: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Device:
    id: str
    user_id: str
    name: str
    os: str
    architecture: str
    flow_version: str
    created_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None


@dataclass(slots=True)
class Presence:
    device_id: str
    state: str
    last_heartbeat_at: datetime
    health: dict[str, Any] = field(default_factory=dict)
    active_sessions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CLIAuthRequest:
    id: str
    state: str
    challenge: str
    device: dict[str, str]
    scopes: tuple[str, ...]
    expires_at: datetime
    created_at: datetime
    user_id: str | None = None
    status: str = "pending"
    used_at: datetime | None = None
    code: str | None = None


@dataclass(slots=True)
class RefreshCredential:
    token_hash: str
    family_id: str
    user_id: str
    device_id: str
    issued_at: datetime
    expires_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None

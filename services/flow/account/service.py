from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt

from .models import AuthenticatedUser, CLIAuthRequest, Device, Presence, Profile, RefreshCredential
from .pkce import valid_verifier
from .store import AccountStore


class AccountError(RuntimeError):
    status = 400


class NotFound(AccountError):
    status = 404


class Unauthorized(AccountError):
    status = 401


class Conflict(AccountError):
    status = 409


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AccountService:
    """FLOW control-plane state machine; Neon Auth is the identity authority."""

    def __init__(self, store: AccountStore | None = None, *, signing_key: str,
                 access_ttl: timedelta = timedelta(minutes=10), refresh_ttl: timedelta = timedelta(days=30)) -> None:
        if not signing_key or len(signing_key) < 32:
            raise ValueError("account signing key must contain at least 32 characters")
        self.store = store or AccountStore()
        self.signing_key = signing_key
        self.access_ttl, self.refresh_ttl = access_ttl, refresh_ttl

    def ensure_profile(self, user: AuthenticatedUser) -> Profile:
        with self.store.lock:
            profile = self.store.profiles.get(user.id)
            if profile is None:
                profile = Profile(user_id=user.id, display_name=user.name)
                self.store.profiles[user.id] = profile
            return profile

    def start_cli_request(self, *, challenge: str, state: str, device: dict[str, str],
                          scopes: tuple[str, ...] = ("profile", "devices", "heartbeat"),
                          ttl: timedelta = timedelta(minutes=5)) -> CLIAuthRequest:
        if not challenge or not state or not device.get("id"):
            raise ValueError("challenge, state, and device id are required")
        now = _now()
        user_code = "-".join("".join(secrets.choice("ABCDEFGHJKMNPQRSTUVWXYZ23456789") for _ in range(size))
                              for size in (4, 4))
        request = CLIAuthRequest("car_" + uuid4().hex, state, challenge, device, scopes, now + ttl, now,
                                user_code=user_code)
        with self.store.lock:
            self.store.requests[request.id] = request
        return request

    def approve_cli_request(self, request_id: str, user: AuthenticatedUser) -> CLIAuthRequest:
        with self.store.lock:
            request = self._request(request_id)
            if request.status != "pending" or request.expires_at <= _now():
                raise Conflict("authorization request is no longer pending")
            request.user_id, request.status, request.code = user.id, "approved", secrets.token_urlsafe(32)
            self.ensure_profile(user)
            return request

    def deny_cli_request(self, request_id: str, user_id: str) -> None:
        with self.store.lock:
            request = self._request(request_id)
            if request.user_id not in (None, user_id):
                raise NotFound("authorization request not found")
            if request.status != "pending":
                raise Conflict("authorization request is no longer pending")
            request.user_id, request.status = user_id, "denied"

    def exchange_code(self, *, request_id: str, code: str, verifier: str) -> dict[str, Any]:
        with self.store.lock:
            request = self._request(request_id)
            if request.expires_at <= _now():
                request.status = "expired"
                raise Unauthorized("authorization request expired")
            if request.status != "approved" or request.used_at is not None or not request.code:
                raise Unauthorized("authorization code is invalid or already used")
            if not secrets.compare_digest(request.code, code) or not valid_verifier(verifier, request.challenge):
                raise Unauthorized("PKCE verification failed")
            user_id = request.user_id
            if not user_id:
                raise Unauthorized("authorization request has no account")
            request.used_at, request.status = _now(), "consumed"
            device = self._upsert_device(user_id, request.device)
            return self._issue(user_id, device.id, request.scopes)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        with self.store.lock:
            credential = self.store.credentials.get(_hash(refresh_token))
            if credential is None or credential.revoked_at or credential.expires_at <= _now():
                raise Unauthorized("refresh token is invalid or expired")
            if credential.rotated_at is not None:
                self._revoke_family(credential.family_id)
                raise Unauthorized("refresh token reuse detected")
            credential.rotated_at = _now()
            return self._issue(credential.user_id, credential.device_id, ("profile", "devices", "heartbeat"),
                               family_id=credential.family_id)

    def logout(self, refresh_token: str) -> None:
        with self.store.lock:
            credential = self.store.credentials.get(_hash(refresh_token))
            if credential is not None:
                self._revoke_family(credential.family_id)

    def revoke_device(self, user_id: str, device_id: str) -> None:
        with self.store.lock:
            device = self.store.devices.get(device_id)
            if device is None or device.user_id != user_id:
                raise NotFound("device not found")
            device.revoked_at = _now()
            for credential in self.store.credentials.values():
                if credential.device_id == device_id:
                    credential.revoked_at = _now()

    def heartbeat(self, user_id: str, device_id: str, health: dict[str, Any], sessions: list[str]) -> Presence:
        with self.store.lock:
            device = self.store.devices.get(device_id)
            if device is None or device.user_id != user_id or device.revoked_at:
                raise Unauthorized("device is not active")
            now = _now()
            device.last_seen_at = now
            presence = Presence(device_id, "online", now, dict(health), list(sessions))
            self.store.presence[device_id] = presence
            return presence

    def devices(self, user_id: str) -> list[Device]:
        with self.store.lock:
            return list(self.store.user_devices(user_id))

    def _request(self, request_id: str) -> CLIAuthRequest:
        request = self.store.requests.get(request_id)
        if request is None:
            raise NotFound("authorization request not found")
        return request

    def _upsert_device(self, user_id: str, data: dict[str, str]) -> Device:
        device_id = data["id"]
        device = self.store.devices.get(device_id)
        if device and device.user_id != user_id:
            raise Conflict("device id belongs to another account")
        if device is None:
            device = Device(device_id, user_id, data.get("name", "FLOW device"), data.get("os", "unknown"),
                            data.get("architecture", "unknown"), data.get("flow_version", "unknown"), _now())
            self.store.devices[device_id] = device
        if device.revoked_at:
            raise Unauthorized("device has been revoked")
        return device

    def _issue(self, user_id: str, device_id: str, scopes: tuple[str, ...], *, family_id: str | None = None) -> dict[str, Any]:
        now = _now()
        access = jwt.encode({"sub": user_id, "device_id": device_id, "scope": " ".join(scopes),
                             "iat": now, "exp": now + self.access_ttl}, self.signing_key, algorithm="HS256")
        raw_refresh = secrets.token_urlsafe(48)
        credential = RefreshCredential(_hash(raw_refresh), family_id or "fam_" + uuid4().hex, user_id, device_id,
                                       now, now + self.refresh_ttl)
        self.store.credentials[credential.token_hash] = credential
        return {"access_token": access, "token_type": "Bearer", "expires_in": int(self.access_ttl.total_seconds()),
                "refresh_token": raw_refresh, "user_id": user_id, "device_id": device_id}

    def _revoke_family(self, family_id: str) -> None:
        for credential in self.store.credentials.values():
            if credential.family_id == family_id:
                credential.revoked_at = _now()

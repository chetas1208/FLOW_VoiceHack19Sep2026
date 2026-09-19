"""CLI device authorization, token issuance, refresh rotation and revocation."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from .core import ApiError, Cloud, Principal, unauthorized
from .repo import DeviceConflict, iso, now, utc
from .schemas import AuthRequestCreate, AuthTokenRequest, RefreshRequest
from .security import hash_token, new_id, new_refresh_token, new_user_code, verify_pkce

log = logging.getLogger("flow.auth")
MAX_PENDING_PER_DEVICE_10MIN = 10


def _oauth(code: str, message: str = "", status: int = 400) -> ApiError:
    return ApiError(status, code, message or code)


def start_request(cloud: Cloud, body: AuthRequestCreate, ip: str) -> dict[str, Any]:
    repo, settings = cloud.repo, cloud.settings
    recent = repo.recent_auth_request_count(body.device.device_id, now() - timedelta(minutes=10))
    if recent >= MAX_PENDING_PER_DEVICE_10MIN:
        repo.audit("auth.suspicious_repeated_requests", ip=ip, device_id=body.device.device_id, detail={"count": recent})
        raise ApiError(429, "rate_limited", "too many authorization requests for this device", {"Retry-After": "300"})
    request_id = new_id("car")
    expires = now() + timedelta(seconds=settings.auth_request_ttl_seconds)
    user_code = new_user_code()
    repo.create_auth_request({
        "id": request_id, "device_id": body.device.device_id, "device_name": body.device.name,
        "device_os": body.device.os, "device_arch": body.device.architecture, "flow_version": body.device.flow_version,
        "code_challenge": body.code_challenge, "state": body.state, "nonce": body.nonce, "user_code": user_code,
        "status": "pending", "created_at": now(), "expires_at": expires})
    repo.audit("auth.request_created", ip=ip, device_id=body.device.device_id)
    return {"auth_request_id": request_id, "user_code": user_code, "expires_at": iso(expires),
            "authorization_url": f"{settings.web_url.rstrip('/')}/cli/auth?request={request_id}",
            "interval": settings.poll_interval_seconds}


def _live_request(cloud: Cloud, request_id: str) -> dict[str, Any]:
    row = cloud.repo.get_auth_request(request_id)
    if not row:
        raise ApiError(404, "not_found", "authorization request not found")
    if row["status"] in {"pending", "approved"} and row["expires_at"] <= now():
        cloud.repo.set_auth_request_status(request_id, "expired", from_status=row["status"])
        row["status"] = "expired"
    return row


def describe_request(cloud: Cloud, request_id: str) -> dict[str, Any]:
    row = _live_request(cloud, request_id)
    return {"id": row["id"], "status": row["status"], "user_code": row["user_code"], "expires_at": iso(row["expires_at"]),
            "device": {"name": row["device_name"], "os": row["device_os"], "architecture": row["device_arch"],
                       "flow_version": row["flow_version"]}}


def approve_request(cloud: Cloud, request_id: str, who: Principal, approve: bool, ip: str) -> dict[str, Any]:
    if who.kind != "web":
        raise ApiError(403, "forbidden", "approval requires a signed-in web session")
    row = _live_request(cloud, request_id)
    target = "approved" if approve else "denied"
    if row["status"] == target and row["user_id"] == who.user_id:
        return {"status": target}
    if row["status"] != "pending":
        raise ApiError(409, "conflict", f"authorization request is {row['status']}")
    if not cloud.repo.set_auth_request_status(request_id, target, from_status="pending", user_id=who.user_id):
        raise ApiError(409, "conflict", "authorization request changed")
    cloud.repo.audit("device.authorization_approved" if approve else "login.denied", user_id=who.user_id,
                     device_id=row["device_id"], ip=ip)
    return {"status": target}


def _issue(cloud: Cloud, user: dict[str, Any], device: dict[str, Any], family_id: str) -> dict[str, Any]:
    settings = cloud.settings
    refresh = new_refresh_token()
    refresh_expires = now() + timedelta(seconds=settings.refresh_ttl_seconds)
    cloud.repo.create_refresh_token(user["id"], device["id"], family_id, hash_token(refresh), refresh_expires)
    access, exp = cloud.tokens.issue(user["id"], device["id"])
    return {"access_token": access, "token_type": "Bearer", "expires_in": settings.access_ttl_seconds,
            "refresh_token": refresh, "refresh_expires_in": settings.refresh_ttl_seconds,
            "user": {"id": user["id"], "email": user["email"]}, "device": {"id": device["id"], "name": device["name"]}}


def exchange(cloud: Cloud, body: AuthTokenRequest, ip: str) -> dict[str, Any]:
    repo = cloud.repo
    row = _live_request(cloud, body.auth_request_id)
    if row["device_id"] != body.device_id or not verify_pkce(body.code_verifier, row["code_challenge"]):
        repo.audit("auth.invalid_grant", device_id=body.device_id, ip=ip, detail={"request": body.auth_request_id})
        raise _oauth("invalid_grant", "invalid authorization grant")
    status = row["status"]
    if status == "pending":
        polled = row.get("last_polled_at")
        repo.touch_auth_poll(row["id"])
        if polled and (now() - polled).total_seconds() < max(1, cloud.settings.poll_interval_seconds - 1):
            raise _oauth("slow_down", "polling too fast")
        raise _oauth("authorization_pending", "waiting for approval")
    if status == "denied":
        raise _oauth("access_denied", "the request was denied")
    if status == "expired":
        raise _oauth("expired_token", "the request expired")
    if status == "consumed":
        repo.audit("auth.replay_attempt", user_id=row.get("user_id"), device_id=body.device_id, ip=ip)
        raise _oauth("invalid_grant", "authorization already used")
    if not repo.set_auth_request_status(row["id"], "consumed", from_status="approved"):
        raise _oauth("invalid_grant", "authorization already used")
    user = repo.get_user(row["user_id"])
    if not user or user.get("disabled_at"):
        raise _oauth("access_denied", "account unavailable")
    try:
        device = repo.upsert_device(user["id"], row["device_id"], row["device_name"], row["device_os"],
                                    row["device_arch"], row["flow_version"])
    except DeviceConflict as exc:
        repo.audit("auth.device_conflict", user_id=user["id"], device_id=row["device_id"], ip=ip)
        raise ApiError(409, "conflict", "device id belongs to another account") from exc
    repo.revoke_device_tokens(device["id"])
    tokens = _issue(cloud, user, device, new_id("fam"))
    repo.audit("device.authorized", user_id=user["id"], device_id=device["id"], ip=ip)
    return {**tokens, "state": row["state"], "nonce": row["nonce"]}


def refresh(cloud: Cloud, body: RefreshRequest, ip: str) -> dict[str, Any]:
    repo = cloud.repo
    record = repo.get_refresh_by_hash(hash_token(body.refresh_token))
    if not record or record["device_id"] != body.device_id:
        repo.audit("auth.refresh_rejected", device_id=body.device_id, ip=ip)
        raise _oauth("invalid_grant", "invalid refresh token", 401)
    if record["rotated_at"] or record["revoked_at"]:
        repo.revoke_family(record["family_id"])
        repo.audit("refresh.reuse_detected", user_id=record["user_id"], device_id=record["device_id"], ip=ip,
                   detail={"family": record["family_id"]})
        raise _oauth("invalid_grant", "refresh token was already used", 401)
    if record["expires_at"] <= now():
        raise _oauth("invalid_grant", "refresh token expired", 401)
    found = repo.device_status(record["device_id"])
    if not found or found[0]["revoked_at"] or found[1]["disabled_at"]:
        repo.revoke_family(record["family_id"])
        raise _oauth("invalid_grant", "device authorization revoked", 401)
    device, _ = found
    user = repo.get_user(record["user_id"])
    new_refresh = new_refresh_token()
    expires = now() + timedelta(seconds=cloud.settings.refresh_ttl_seconds)
    if not repo.rotate_refresh(record["id"], record["user_id"], record["device_id"], record["family_id"],
                               hash_token(new_refresh), expires):
        repo.revoke_family(record["family_id"])
        repo.audit("refresh.reuse_detected", user_id=record["user_id"], device_id=record["device_id"], ip=ip)
        raise _oauth("invalid_grant", "refresh token was already used", 401)
    access, _ = cloud.tokens.issue(record["user_id"], record["device_id"])
    repo.audit("refresh.rotated", user_id=record["user_id"], device_id=record["device_id"], ip=ip)
    return {"access_token": access, "token_type": "Bearer", "expires_in": cloud.settings.access_ttl_seconds,
            "refresh_token": new_refresh, "refresh_expires_in": cloud.settings.refresh_ttl_seconds,
            "user": {"id": user["id"], "email": user["email"]}, "device": {"id": device["id"], "name": device["name"]}}


def logout(cloud: Cloud, refresh_token: str) -> None:
    record = cloud.repo.get_refresh_by_hash(hash_token(refresh_token))
    if record:
        cloud.repo.revoke_family(record["family_id"])
        cloud.repo.audit("device.logout", user_id=record["user_id"], device_id=record["device_id"])


def revoke_device(cloud: Cloud, who: Principal, device_id: str, ip: str) -> None:
    device = cloud.repo.get_device(device_id)
    if not device or device["user_id"] != who.user_id:
        raise ApiError(404, "not_found", "device not found")
    if who.kind == "device" and who.device_id != device_id:
        raise ApiError(403, "forbidden", "a device may only revoke itself")
    cloud.repo.revoke_device(who.user_id, device_id)
    cloud.repo.audit("device.revoked", user_id=who.user_id, device_id=device_id, ip=ip)
    cloud.bus.publish(f"d:{device_id}", {"type": "revoked"})

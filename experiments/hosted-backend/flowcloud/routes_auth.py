"""Authentication, device management and health routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

from . import auth_service
from .core import (ApiError, Cloud, Principal, client_ip, cloud_of, device_out, limit, principal)
from .identity import IdentityError, LocalIdentityVerifier
from .repo import iso
from .schemas import AuthRequestCreate, AuthTokenRequest, DevLogin, LogoutRequest, RefreshRequest

router = APIRouter()


@router.post("/v1/cli/auth/requests", status_code=201)
def create_auth_request(body: AuthRequestCreate, request: Request):
    cloud = cloud_of(request)
    ip = client_ip(request, cloud.settings)
    limit(cloud, f"auth-start:{ip}", 20)
    return auth_service.start_request(cloud, body, ip)


@router.post("/v1/cli/auth/token")
def exchange_token(body: AuthTokenRequest, request: Request):
    cloud = cloud_of(request)
    ip = client_ip(request, cloud.settings)
    limit(cloud, f"auth-token:{ip}", 90)
    return auth_service.exchange(cloud, body, ip)


@router.get("/v1/cli/auth/requests/{request_id}")
def get_auth_request(request_id: str, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    limit(cloud, f"auth-describe:{who.user_id}", 60)
    return auth_service.describe_request(cloud, request_id)


@router.post("/v1/cli/auth/requests/{request_id}/approve")
def approve_auth_request(request_id: str, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    limit(cloud, f"auth-approve:{who.user_id}", 20)
    return auth_service.approve_request(cloud, request_id, who, True, client_ip(request, cloud.settings))


@router.post("/v1/cli/auth/requests/{request_id}/deny")
def deny_auth_request(request_id: str, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    return auth_service.approve_request(cloud, request_id, who, False, client_ip(request, cloud.settings))


@router.post("/v1/auth/refresh")
def refresh(body: RefreshRequest, request: Request):
    cloud = cloud_of(request)
    ip = client_ip(request, cloud.settings)
    limit(cloud, f"refresh:{body.device_id}", 30)
    limit(cloud, f"refresh-ip:{ip}", 120)
    return auth_service.refresh(cloud, body, ip)


@router.post("/v1/auth/logout", status_code=204)
def logout(body: LogoutRequest, request: Request):
    cloud = cloud_of(request)
    limit(cloud, f"logout:{client_ip(request, cloud.settings)}", 30)
    auth_service.logout(cloud, body.refresh_token)
    return Response(status_code=204)


@router.post("/v1/dev/login")
def dev_login(body: DevLogin, request: Request):
    cloud = cloud_of(request)
    verifier = cloud.identity
    if not isinstance(verifier, LocalIdentityVerifier):
        raise ApiError(404, "not_found", "not found")
    limit(cloud, f"dev-login:{client_ip(request, cloud.settings)}", 60)
    return {"access_token": verifier.issue(body.email)}


@router.get("/v1/me")
def me(who: Principal = Depends(principal)):
    result = {"id": who.user_id, "email": who.email, "principal": who.kind}
    if who.device_id:
        result["device_id"] = who.device_id
    return result


@router.get("/v1/devices")
def list_devices(request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    devices = cloud.repo.list_devices(who.user_id)
    presence = cloud.repo.presence_map([d["id"] for d in devices])
    return {"items": [device_out(d, presence.get(d["id"])) for d in devices]}


@router.delete("/v1/devices/{device_id}", status_code=204)
def delete_device(device_id: str, request: Request, who: Principal = Depends(principal)):
    cloud = cloud_of(request)
    auth_service.revoke_device(cloud, who, device_id, client_ip(request, cloud.settings))
    return Response(status_code=204)


# ---- health / metrics --------------------------------------------------------------------------
@router.get("/health/live")
def live():
    return {"status": "ok"}


@router.get("/health/ready")
def ready(request: Request):
    cloud = cloud_of(request)
    try:
        cloud.repo.ping()
        cloud.settings.validate()
    except Exception as exc:  # readiness only reflects the database and critical config
        return JSONResponse({"status": "unavailable", "reason": type(exc).__name__}, status_code=503)
    return {"status": "ready"}


@router.get("/health")
def health(request: Request):
    return ready(request)


@router.get("/metrics")
def metrics(request: Request):
    cloud = cloud_of(request)
    token = cloud.settings.metrics_token
    if token and request.headers.get("authorization") != f"Bearer {token}":
        raise ApiError(401, "unauthorized", "metrics token required")
    gauges = {"flow_jobs_pending": cloud.repo.job_depth()}
    return PlainTextResponse(cloud.metrics.render(gauges))

"""FastAPI adapter for a deployed account control plane.

The host application must set ``request.state.account_user`` from its Neon
Auth/Better Auth session. This adapter never accepts an email or password as a
substitute for that authenticated identity.
"""

from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .models import AuthenticatedUser
from .service import AccountError, AccountService, Unauthorized


class CLIRequestIn(BaseModel):
    state: str = Field(min_length=16, max_length=200)
    code_challenge: str = Field(min_length=40, max_length=100)
    device: dict[str, str]


class TokenIn(BaseModel):
    request_id: str
    code: str
    code_verifier: str


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20)


def router_for(service: AccountService) -> APIRouter:
    router = APIRouter(tags=["FLOW account"])

    def user(request: Request) -> AuthenticatedUser:
        value = getattr(request.state, "account_user", None)
        if not isinstance(value, AuthenticatedUser):
            raise HTTPException(401, "authenticated account required")
        return value

    def handle(exc: AccountError) -> HTTPException:
        return HTTPException(exc.status, str(exc))

    @router.post("/v1/cli/auth/requests", status_code=201)
    def start(payload: CLIRequestIn):
        item = service.start_cli_request(challenge=payload.code_challenge, state=payload.state, device=payload.device)
        return {"request_id": item.id, "user_code": item.user_code, "state": item.state,
                "verification_uri": "/cli/authorize", "verification_uri_complete": f"/cli/authorize?request={item.id}",
                "expires_in": int((item.expires_at - item.created_at).total_seconds()), "poll_interval": 3,
                "expires_at": item.expires_at}

    @router.get("/v1/cli/auth/requests/{request_id}")
    def request_status(request_id: str):
        item = service.store.requests.get(request_id)
        if item is None:
            raise HTTPException(404, "authorization request not found")
        if item.status == "pending" and item.expires_at <= datetime.now(timezone.utc):
            item.status = "expired"
        return {"request_id": item.id, "status": item.status, "user_code": item.user_code, "device": item.device,
                "code": item.code if item.status == "approved" else None, "expires_at": item.expires_at}

    @router.post("/v1/cli/auth/requests/{request_id}/approve")
    def approve(request_id: str, request: Request):
        try:
            item = service.approve_cli_request(request_id, user(request))
            return {"status": item.status}
        except AccountError as exc:
            raise handle(exc) from exc

    @router.post("/v1/cli/auth/token")
    def token(payload: TokenIn):
        try:
            return service.exchange_code(request_id=payload.request_id, code=payload.code, verifier=payload.code_verifier)
        except AccountError as exc:
            raise handle(exc) from exc

    router.add_api_route("/api/cli/auth/start", start, methods=["POST"], status_code=201)
    router.add_api_route("/api/cli/auth/token", token, methods=["POST"])

    @router.post("/v1/auth/refresh")
    def refresh(payload: RefreshIn):
        try:
            return service.refresh(payload.refresh_token)
        except AccountError as exc:
            raise handle(exc) from exc

    @router.post("/v1/auth/logout", status_code=204)
    def logout(payload: RefreshIn):
        service.logout(payload.refresh_token)
        return None

    @router.get("/v1/me")
    def me(request: Request):
        current = user(request)
        service.ensure_profile(current)
        return {"id": current.id, "email": current.email, "name": current.name}

    @router.get("/v1/devices")
    def devices(request: Request):
        return {"items": [{"id": d.id, "name": d.name, "os": d.os, "architecture": d.architecture,
                           "flow_version": d.flow_version, "created_at": d.created_at, "last_seen_at": d.last_seen_at,
                           "revoked_at": d.revoked_at} for d in service.devices(user(request).id)]}

    @router.delete("/v1/devices/{device_id}", status_code=204)
    def revoke(device_id: str, request: Request):
        try:
            service.revoke_device(user(request).id, device_id)
        except AccountError as exc:
            raise handle(exc) from exc
        return None

    return router

from datetime import timedelta

import jwt
import pytest

from services.flow.account.models import AuthenticatedUser
from services.flow.account.pkce import challenge_for, create_verifier
from services.flow.account.service import AccountService, Conflict, NotFound, Unauthorized


def make_service():
    return AccountService(signing_key="x" * 40, access_ttl=timedelta(minutes=1))


def authorize(service):
    verifier = create_verifier()
    request = service.start_cli_request(challenge=challenge_for(verifier), state="state", device={"id": "dev-1", "name": "laptop"})
    service.approve_cli_request(request.id, AuthenticatedUser("user-1", "one@example.test"))
    return request, verifier


def test_pkce_exchange_is_one_time_and_claims_are_scoped():
    service = make_service()
    request, verifier = authorize(service)
    tokens = service.exchange_code(request_id=request.id, code=request.code, verifier=verifier)
    claims = jwt.decode(tokens["access_token"], "x" * 40, algorithms=["HS256"])
    assert claims["sub"] == "user-1" and claims["device_id"] == "dev-1"
    with pytest.raises(Unauthorized, match="already used"):
        service.exchange_code(request_id=request.id, code=request.code, verifier=verifier)


def test_wrong_verifier_does_not_consume_code():
    service = make_service()
    request, _ = authorize(service)
    with pytest.raises(Unauthorized, match="PKCE"):
        service.exchange_code(request_id=request.id, code=request.code, verifier=create_verifier())
    assert request.status == "approved"


def test_expired_request_and_cross_user_device_are_rejected():
    service = make_service()
    request, verifier = authorize(service)
    service.exchange_code(request_id=request.id, code=request.code, verifier=verifier)

    expired = service.start_cli_request(challenge=challenge_for(verifier), state="expired", device={"id": "dev-2"})
    service.approve_cli_request(expired.id, AuthenticatedUser("user-1", "one@example.test"))
    expired.expires_at = expired.created_at - timedelta(seconds=1)
    with pytest.raises(Unauthorized, match="expired"):
        service.exchange_code(request_id=expired.id, code=expired.code, verifier=verifier)

    other = service.start_cli_request(challenge=challenge_for(verifier), state="other", device={"id": "dev-1"})
    service.approve_cli_request(other.id, AuthenticatedUser("user-2", "two@example.test"))
    with pytest.raises(Conflict, match="another account"):
        service.exchange_code(request_id=other.id, code=other.code, verifier=verifier)


def test_refresh_rotation_and_reuse_revoke_family():
    service = make_service()
    request, verifier = authorize(service)
    first = service.exchange_code(request_id=request.id, code=request.code, verifier=verifier)
    second = service.refresh(first["refresh_token"])
    assert second["refresh_token"] != first["refresh_token"]
    with pytest.raises(Unauthorized, match="reuse"):
        service.refresh(first["refresh_token"])
    with pytest.raises(Unauthorized):
        service.refresh(second["refresh_token"])


def test_revoked_device_cannot_heartbeat():
    service = make_service()
    request, verifier = authorize(service)
    service.exchange_code(request_id=request.id, code=request.code, verifier=verifier)
    service.revoke_device("user-1", "dev-1")
    with pytest.raises(Unauthorized, match="active"):
        service.heartbeat("user-1", "dev-1", {}, [])

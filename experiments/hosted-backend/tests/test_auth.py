import secrets
import time

import pytest

from services.flowcloud.security import pkce_challenge


def start(client, device_id="dev_abcdefgh12345", verifier=None):
    verifier = verifier or secrets.token_urlsafe(48)
    r = client.post("/v1/cli/auth/requests", json={
        "device": {"device_id": device_id, "name": "Chetas MacBook", "os": "darwin", "architecture": "arm64", "flow_version": "0.2.0"},
        "code_challenge": pkce_challenge(verifier), "state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24)})
    assert r.status_code == 201, r.text
    return r.json(), verifier, device_id


def exchange(client, request_id, device_id, verifier):
    return client.post("/v1/cli/auth/token", json={"auth_request_id": request_id, "device_id": device_id, "code_verifier": verifier})


def test_full_device_authorization_flow(client, alice):
    body, verifier, device_id = start(client)
    assert "code" not in body["authorization_url"] and verifier not in body["authorization_url"]
    assert body["authorization_url"] == f"http://web.test/cli/auth?request={body['auth_request_id']}"
    assert len(body["user_code"]) == 9
    pending = exchange(client, body["auth_request_id"], device_id, verifier)
    assert pending.status_code == 400 and pending.json()["error"] == "authorization_pending"
    info = client.get(f"/v1/cli/auth/requests/{body['auth_request_id']}", headers=alice.web).json()
    assert info["device"]["name"] == "Chetas MacBook" and info["user_code"] == body["user_code"]
    assert client.post(f"/v1/cli/auth/requests/{body['auth_request_id']}/approve", headers=alice.web).status_code == 200
    done = exchange(client, body["auth_request_id"], device_id, verifier)
    assert done.status_code == 200
    tokens = done.json()
    assert tokens["user"]["email"] == "alice@example.com" and tokens["expires_in"] == 900
    me = client.get("/v1/me", headers={"Authorization": "Bearer " + tokens["access_token"]}).json()
    assert me["principal"] == "device" and me["device_id"] == device_id


def test_authorization_is_one_time(client, alice):
    body, verifier, device_id = start(client)
    client.post(f"/v1/cli/auth/requests/{body['auth_request_id']}/approve", headers=alice.web)
    assert exchange(client, body["auth_request_id"], device_id, verifier).status_code == 200
    replay = exchange(client, body["auth_request_id"], device_id, verifier)
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"


def test_wrong_pkce_verifier_and_wrong_device_rejected(client, alice):
    body, verifier, device_id = start(client)
    client.post(f"/v1/cli/auth/requests/{body['auth_request_id']}/approve", headers=alice.web)
    assert exchange(client, body["auth_request_id"], device_id, secrets.token_urlsafe(48)).json()["error"] == "invalid_grant"
    assert exchange(client, body["auth_request_id"], "dev_otherdevice1234", verifier).json()["error"] == "invalid_grant"
    assert exchange(client, body["auth_request_id"], device_id, verifier).status_code == 200


def test_denied_and_expired_requests(client, alice, app):
    body, verifier, device_id = start(client)
    client.post(f"/v1/cli/auth/requests/{body['auth_request_id']}/deny", headers=alice.web)
    assert exchange(client, body["auth_request_id"], device_id, verifier).json()["error"] == "access_denied"
    body, verifier, device_id = start(client, "dev_expiring123456")
    from services.flowcloud import db
    from sqlalchemy import update
    from datetime import datetime, timezone, timedelta
    with app.state.cloud.repo.engine.begin() as conn:
        conn.execute(update(db.cli_auth_requests).where(db.cli_auth_requests.c.id == body["auth_request_id"]).values(
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    assert exchange(client, body["auth_request_id"], device_id, verifier).json()["error"] == "expired_token"
    assert client.post(f"/v1/cli/auth/requests/{body['auth_request_id']}/approve", headers=alice.web).status_code == 409


def test_approval_requires_web_identity_not_a_device_token(client, alice):
    device = alice.authorize_device()
    body, _, _ = start(client, "dev_second1234567")
    r = client.post(f"/v1/cli/auth/requests/{body['auth_request_id']}/approve", headers=device.headers)
    assert r.status_code == 403
    assert client.post(f"/v1/cli/auth/requests/{body['auth_request_id']}/approve").status_code == 401


def test_polling_too_fast_gets_slow_down(client):
    body, verifier, device_id = start(client)
    assert exchange(client, body["auth_request_id"], device_id, verifier).json()["error"] == "authorization_pending"
    assert exchange(client, body["auth_request_id"], device_id, verifier).json()["error"] == "slow_down"


def test_refresh_rotates_and_reuse_revokes_family(client, alice, app):
    device = alice.authorize_device()
    first = device.tokens["refresh_token"]
    r1 = client.post("/v1/auth/refresh", json={"refresh_token": first, "device_id": device.device_id})
    assert r1.status_code == 200 and r1.json()["refresh_token"] != first
    second = r1.json()["refresh_token"]
    replay = client.post("/v1/auth/refresh", json={"refresh_token": first, "device_id": device.device_id})
    assert replay.status_code == 401 and replay.json()["error"] == "invalid_grant"
    after = client.post("/v1/auth/refresh", json={"refresh_token": second, "device_id": device.device_id})
    assert after.status_code == 401, "reuse must revoke the whole family"
    events = {e["event"] for e in app.state.cloud.repo.audit_events()}
    assert {"refresh.reuse_detected", "refresh.rotated", "device.authorized"} <= events


def test_refresh_tokens_are_hashed_at_rest_and_device_bound(client, alice, app):
    device = alice.authorize_device()
    from services.flowcloud import db
    from sqlalchemy import select
    with app.state.cloud.repo.engine.connect() as conn:
        stored = [r.token_hash for r in conn.execute(select(db.refresh_tokens))]
    assert stored and device.tokens["refresh_token"] not in stored
    assert all(len(h) == 64 for h in stored)
    wrong = client.post("/v1/auth/refresh", json={"refresh_token": device.tokens["refresh_token"], "device_id": "dev_notmydevice123"})
    assert wrong.status_code == 401


def test_logout_revokes_refresh_token(client, alice):
    device = alice.authorize_device()
    assert client.post("/v1/auth/logout", json={"refresh_token": device.tokens["refresh_token"]}).status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": device.tokens["refresh_token"], "device_id": device.device_id}).status_code == 401


def test_device_revocation_blocks_refresh_and_uploads(client, alice):
    device = alice.authorize_device()
    session_id = device.create_session()
    assert client.get("/v1/devices", headers=alice.web).json()["items"][0]["id"] == device.device_id
    assert client.delete(f"/v1/devices/{device.device_id}", headers=alice.web).status_code == 204
    assert client.post("/v1/auth/refresh", json={"refresh_token": device.tokens["refresh_token"], "device_id": device.device_id}).status_code == 401
    r = client.post(f"/v1/sessions/{session_id}/events", headers=device.headers, json={
        "id": "evt_00000001", "sequence": 1, "type": "session.started", "timestamp": "2026-09-19T10:00:00Z", "data": {}})
    assert r.status_code == 401
    listed = client.get("/v1/devices", headers=alice.web).json()["items"][0]
    assert listed["revoked_at"] is not None


def test_reauthorizing_a_revoked_device_works(client, alice):
    device = alice.authorize_device(device_id="dev_reauthorize123")
    client.delete(f"/v1/devices/{device.device_id}", headers=alice.web)
    again = alice.authorize_device(device_id="dev_reauthorize123")
    assert client.get("/v1/me", headers=again.headers).status_code == 200


def test_device_id_cannot_be_hijacked_by_another_account(client, alice, bob):
    alice.authorize_device(device_id="dev_victimdevice123")
    body, verifier, device_id = start(client, "dev_victimdevice123")
    client.post(f"/v1/cli/auth/requests/{body['auth_request_id']}/approve", headers=bob.web)
    r = exchange(client, body["auth_request_id"], device_id, verifier)
    assert r.status_code == 409


def test_only_owner_or_self_can_revoke(client, alice, bob):
    device = alice.authorize_device()
    assert client.delete(f"/v1/devices/{device.device_id}", headers=bob.web).status_code == 404
    other = alice.authorize_device(device_id="dev_otheralice12345")
    assert client.delete(f"/v1/devices/{other.device_id}", headers=device.headers).status_code == 403
    assert client.delete(f"/v1/devices/{device.device_id}", headers=device.headers).status_code == 204


def test_expired_and_forged_access_tokens_rejected(client, alice, app):
    from services.flowcloud.security import AccessTokenService
    device = alice.authorize_device()
    svc = AccessTokenService(app.state.cloud.settings)
    old, _ = svc.issue(device.tokens["user"]["id"], device.device_id, now=time.time() - 3600)
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {old}"}).status_code == 401
    import jwt
    forged = jwt.encode({"iss": "flow-cloud", "aud": "flow-api", "sub": "usr_x", "did": device.device_id, "typ": "access",
                         "iat": int(time.time()), "exp": int(time.time()) + 600, "jti": "x"}, "wrong-secret-wrong-secret-1234567890", algorithm="HS256", headers={"kid": "k1"})
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    none_alg = jwt.encode({"iss": "flow-cloud"}, None, algorithm="none")
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {none_alg}"}).status_code == 401


def test_repeated_auth_requests_for_one_device_are_throttled_and_audited(client, app):
    codes = [start(client, "dev_spammydevice123")[0] and 201 for _ in range(10)]
    r = client.post("/v1/cli/auth/requests", json={
        "device": {"device_id": "dev_spammydevice123", "name": "x", "os": "darwin", "architecture": "arm64", "flow_version": "0.2.0"},
        "code_challenge": pkce_challenge("a" * 50), "state": secrets.token_urlsafe(24), "nonce": secrets.token_urlsafe(24)})
    assert r.status_code == 429
    assert any(e["event"] == "auth.suspicious_repeated_requests" for e in app.state.cloud.repo.audit_events())


def test_dev_login_absent_in_remote_mode(tmp_path):
    from fastapi.testclient import TestClient
    from services.flowcloud.app import create_app
    from services.flowcloud.identity import OIDCIdentityVerifier
    from cloud_helpers import make_settings as _settings
    settings = _settings(tmp_path, auth_mode="remote", oidc_issuer="https://idp.test/", oidc_audience="flow-web")
    app = create_app(settings, cloud=None)
    with TestClient(app) as c:
        assert isinstance(app.state.cloud.identity, OIDCIdentityVerifier)
        assert c.post("/v1/dev/login", json={"email": "a@b.co"}).status_code == 404

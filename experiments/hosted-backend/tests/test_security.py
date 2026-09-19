import secrets
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from cloud_helpers import event, make_settings, observation
from services.flowcloud.app import create_app
from services.flowcloud.settings import ConfigError, Settings


# ---- tenant isolation ----------------------------------------------------------------------------
@pytest.fixture()
def seeded(client, alice, bob):
    a, b = alice.authorize_device(), bob.authorize_device()
    sid = a.create_session("alice private goal")
    client.post(f"/v1/sessions/{sid}/observations", headers=a.headers, json=observation(1))
    client.post(f"/v1/sessions/{sid}/events", headers=a.headers, json=event(1, "session.started"))
    return a, b, sid


@pytest.mark.parametrize("suffix", ["", "/live", "/report", "/observations", "/events", "/entities", "/commands"])
def test_user_b_cannot_read_user_a_session(client, bob, seeded, suffix):
    _, _, sid = seeded
    assert client.get(f"/v1/sessions/{sid}{suffix}", headers=bob.web).status_code == 404
    other_device = client.get(f"/v1/sessions/{sid}{suffix}", headers=seeded[1].headers)
    assert other_device.status_code == 404


def test_user_b_cannot_write_user_a_session(client, seeded):
    a, b, sid = seeded
    assert client.post(f"/v1/sessions/{sid}/observations", headers=b.headers, json=observation(2)).status_code == 404
    assert client.post(f"/v1/sessions/{sid}/events", headers=b.headers, json=event(2)).status_code == 404
    assert client.post(f"/v1/sessions/{sid}/stop", headers=b.headers, json={}).status_code == 404
    assert client.put(f"/v1/sessions/{sid}/summary", headers=b.headers, json={"goal": "x", "duration_seconds": 1}).status_code == 404


def test_lists_only_show_own_sessions_and_devices(client, alice, bob, seeded):
    a, b, sid = seeded
    assert client.get("/v1/sessions", headers=bob.web).json()["items"] == []
    assert [s["id"] for s in client.get("/v1/sessions", headers=alice.web).json()["items"]] == [sid]
    assert [d["id"] for d in client.get("/v1/devices", headers=bob.web).json()["items"]] == [b.device_id]


def test_user_b_cannot_command_user_a_device_or_session(client, bob, seeded):
    a, b, sid = seeded
    assert client.post("/v1/commands", headers=bob.web, json={"type": "STOP", "session_id": sid, "payload": {}}).status_code == 404
    assert client.post("/v1/commands", headers=bob.web, json={"type": "START", "device_id": a.device_id, "payload": {"goal": "x"}}).status_code == 404
    assert client.post("/v1/commands", headers=b.headers, json={"type": "PAUSE", "session_id": sid, "payload": {}}).status_code == 404


def test_user_b_cannot_read_or_ack_user_a_command(client, alice, bob, seeded):
    a, b, sid = seeded
    made = client.post("/v1/commands", headers=alice.web, json={"type": "PAUSE", "session_id": sid, "payload": {}}).json()
    assert client.get(f"/v1/commands/{made['command_id']}", headers=bob.web).status_code == 404
    assert client.post(f"/v1/commands/{made['command_id']}/ack", headers=b.headers, json={"status": "succeeded"}).status_code == 404
    reuse = client.post("/v1/commands", headers=bob.web, json={"type": "PAUSE", "session_id": "ses_bobs0000001", "command_id": made["command_id"], "payload": {}})
    assert reuse.status_code in (404, 409)


def test_user_b_cannot_approve_user_a_task(client, alice, bob, seeded):
    a, b, sid = seeded
    approval = {"id": "appr_00000001", "session_id": sid, "task_id": "task_00000001", "action": {"tool": "run_tests"},
                "risk": "low", "status": "pending", "requested_at": "2026-09-19T10:00:00Z", "revision": 1}
    client.post(f"/v1/sessions/{sid}/entities:batch", headers=a.headers, json={"items": [
        {"kind": "approval", "id": "appr_00000001", "revision": 1, "data": approval}]})
    assert client.get("/v1/approvals", headers=bob.web).json()["items"] == []
    r = client.post("/v1/commands", headers=bob.web, json={"type": "APPROVE_ACTION", "session_id": sid, "payload": {"approval_id": "appr_00000001"}})
    assert r.status_code == 404


def test_user_b_cannot_revoke_user_a_device_or_approve_its_login(client, alice, bob, seeded):
    a, _, _ = seeded
    assert client.delete(f"/v1/devices/{a.device_id}", headers=bob.web).status_code == 404
    assert client.get("/v1/devices", headers=alice.web).json()["items"][0]["revoked_at"] is None


def test_websockets_enforce_ownership_and_authentication(client, alice, bob, seeded):
    a, b, sid = seeded
    token_b = bob.web["Authorization"][7:]
    with client.websocket_connect(f"/v1/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "auth", "token": token_b})
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 1008
    with client.websocket_connect(f"/v1/ws/sessions/{sid}?token={alice.web['Authorization'][7:]}") as ws:
        ws.send_json({"type": "hello"})
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 4401, "query-string tokens must not authenticate"
    with client.websocket_connect(f"/v1/ws/sessions/{sid}") as ws:
        ws.send_json({"type": "auth", "token": "garbage.token.value"})
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 4401
    with client.websocket_connect("/v1/ws/device") as ws:
        ws.send_json({"type": "auth", "token": token_b})
        with pytest.raises(WebSocketDisconnect) as info:
            ws.receive_json()
        assert info.value.code == 4403, "a web token cannot open the device channel"


def test_websocket_origin_is_checked_in_production_like_config(tmp_path):
    settings = make_settings(tmp_path, allowed_origins=("https://app.flow.ai",))
    app = create_app(settings)
    with TestClient(app) as c:
        actor_token = c.post("/v1/dev/login", json={"email": "o@example.com"}).json()["access_token"]
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/v1/ws/user", headers={"Origin": "https://evil.example"}) as ws:
                ws.send_json({"type": "auth", "token": actor_token}); ws.receive_json()
        with c.websocket_connect("/v1/ws/user", headers={"Origin": "https://app.flow.ai"}) as ws:
            ws.send_json({"type": "auth", "token": actor_token})
            assert ws.receive_json()["type"] == "ready"


def test_websocket_closes_when_token_expires(client, alice, seeded, monkeypatch):
    a, _, sid = seeded
    import services.flowcloud.routes_ws as ws_module
    from services.flowcloud.identity import LocalIdentityVerifier
    token = client.app.state.cloud.identity.issue("alice@example.com", ttl=2)
    with client.websocket_connect("/v1/ws/user") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "ready"
        end = time.time() + 8
        with pytest.raises(WebSocketDisconnect) as info:
            while time.time() < end:
                ws.receive_json()
        assert info.value.code == 4401


# ---- rate limiting, validation, errors -------------------------------------------------------------
def test_rate_limits_apply_to_auth_endpoints(tmp_path):
    settings = make_settings(tmp_path, rate_limit_multiplier=0.1)
    with TestClient(create_app(settings)) as c:
        statuses = [c.post("/v1/auth/refresh", json={"refresh_token": "x" * 30, "device_id": "dev_ratelimited1"}).status_code for _ in range(6)]
        assert 429 in statuses and statuses[0] == 401
        r = c.post("/v1/auth/refresh", json={"refresh_token": "x" * 30, "device_id": "dev_ratelimited1"})
        assert r.status_code == 429 and "retry-after" in r.headers


def test_errors_are_json_and_carry_request_ids(client):
    r = client.get("/v1/sessions/ses_missing0001", headers={"Authorization": "Bearer nope-nope-nope-nope"})
    assert r.status_code == 401 and r.json()["error"] == "unauthorized" and r.headers["x-request-id"]
    r = client.post("/v1/cli/auth/requests", json={"device": {}}, headers={"X-Request-ID": "trace-12345678"})
    assert r.status_code == 422 and r.headers["x-request-id"] == "trace-12345678" and r.json()["error"] == "validation_error"


def test_secrets_never_logged(client, alice, capsys, caplog):
    import logging
    caplog.set_level(logging.DEBUG)
    device = alice.authorize_device()
    client.post("/v1/auth/refresh", json={"refresh_token": device.tokens["refresh_token"], "device_id": device.device_id})
    text = caplog.text + capsys.readouterr().out
    assert device.tokens["refresh_token"] not in text and device.tokens["access_token"] not in text


def test_metrics_endpoint_and_health(client, alice):
    alice.authorize_device()
    text = client.get("/metrics").text
    assert "flow_http_requests_total" in text and "flow_jobs_pending" in text
    assert client.get("/health/ready").json() == {"status": "ready"}


# ---- production configuration guard ----------------------------------------------------------------
def test_production_refuses_local_auth_mode_and_weak_config():
    good = dict(env="production", auth_mode="remote", database_url="postgresql://u:p@db/flow", redis_url="redis://r",
                jwt_keys={"k": "s" * 40}, oidc_issuer="https://idp/", oidc_audience="flow")
    Settings(**good).validate()
    with pytest.raises(ConfigError, match="local"):
        Settings(**{**good, "auth_mode": "local"}).validate()
    with pytest.raises(ConfigError, match="32"):
        Settings(**{**good, "jwt_keys": {"k": "short"}}).validate()
    with pytest.raises(ConfigError, match="PostgreSQL"):
        Settings(**{**good, "database_url": "sqlite:///x.db"}).validate()
    with pytest.raises(ConfigError, match="REDIS_URL"):
        Settings(**{**good, "redis_url": None}).validate()
    with pytest.raises(ConfigError, match="OIDC"):
        Settings(**{**good, "oidc_issuer": None}).validate()
    with pytest.raises(ConfigError, match="https"):
        Settings(**{**good, "web_url": "http://x"}).validate()


def test_from_env_defaults_are_fail_closed(monkeypatch):
    for key in ("FLOW_ENV", "FLOW_AUTH_MODE", "DATABASE_URL", "FLOW_JWT_SECRET", "FLOW_JWT_KEYS", "REDIS_URL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env().validate()
    monkeypatch.setenv("FLOW_ENV", "development"); monkeypatch.setenv("FLOW_AUTH_MODE", "local")
    assert Settings.from_env().validate().ephemeral_secret


# ---- OIDC ---------------------------------------------------------------------------------------------
def test_oidc_web_tokens_verified_against_provider_key(tmp_path):
    from services.flowcloud.identity import OIDCIdentityVerifier
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = make_settings(tmp_path, auth_mode="remote", oidc_issuer="https://idp.test/", oidc_audience="flow-web")
    verifier = OIDCIdentityVerifier(settings, key_resolver=lambda token: key.public_key())
    app = create_app(settings)
    app.state.cloud.identity = verifier

    def mint(**claims):
        base = {"iss": "https://idp.test/", "aud": "flow-web", "sub": "auth0|123", "email": "Chetas@Example.com", "email_verified": True,
                "exp": int(time.time()) + 600, "iat": int(time.time())}
        base.update(claims)
        return jwt.encode(base, key, algorithm="RS256")

    with TestClient(app) as c:
        ok = c.get("/v1/me", headers={"Authorization": f"Bearer {mint()}"})
        assert ok.status_code == 200 and ok.json()["email"] == "chetas@example.com"
        for bad in (mint(aud="other"), mint(iss="https://evil/"), mint(exp=int(time.time()) - 600), mint(email_verified=False)):
            assert c.get("/v1/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode({"iss": "https://idp.test/", "aud": "flow-web", "sub": "x", "email": "a@b.co", "exp": int(time.time()) + 60}, other_key, algorithm="RS256")
        assert c.get("/v1/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
        hs = jwt.encode({"iss": "https://idp.test/", "aud": "flow-web", "sub": "x", "email": "a@b.co", "exp": int(time.time()) + 60}, "secret", algorithm="HS256")
        assert c.get("/v1/me", headers={"Authorization": f"Bearer {hs}"}).status_code == 401, "no alg confusion"
        second = c.get("/v1/me", headers={"Authorization": f"Bearer {mint(sub='auth0|other', email='chetas@example.com')}"})
        assert second.status_code == 409, "same email under a different subject must not merge accounts"


def test_migrations_match_metadata_and_downgrade(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.runtime.migration import MigrationContext
    from services.flowcloud import db, migrate
    url = f"sqlite:///{tmp_path}/m.sqlite3"
    migrate.upgrade(url)
    assert migrate.current_revision(url) == migrate.head_revision()
    engine = db.make_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), db.metadata)
    assert diff == [], diff
    from alembic import command
    command.downgrade(migrate.alembic_config(url), "base")
    assert migrate.current_revision(url) is None

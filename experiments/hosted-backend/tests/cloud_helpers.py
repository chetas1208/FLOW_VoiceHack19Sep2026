import secrets

from fastapi.testclient import TestClient

from services.flowcloud.settings import Settings


def make_settings(tmp_path, **overrides) -> Settings:
    """Uses FLOW_TEST_DATABASE_URL / FLOW_TEST_REDIS_URL when set so the suite can run on Postgres + Redis."""
    import os
    url = os.getenv("FLOW_TEST_DATABASE_URL") or f"sqlite:///{tmp_path}/cloud.sqlite3"
    base = dict(env="test", auth_mode="local", database_url=url, redis_url=os.getenv("FLOW_TEST_REDIS_URL") or None,
                jwt_keys={"k1": secrets.token_urlsafe(48)}, web_url="http://web.test", api_url="http://api.test")
    base.update(overrides)
    return Settings(**base).validate()


class Actor:
    """A signed-in web user plus helpers to authorize devices through the real protocol."""

    def __init__(self, client: TestClient, email: str) -> None:
        self.client, self.email = client, email
        self.web = {"Authorization": "Bearer " + client.post("/v1/dev/login", json={"email": email}).json()["access_token"]}

    def authorize_device(self, name: str = "Test Mac", device_id: str | None = None) -> "Device":
        from services.flowcloud.security import pkce_challenge
        device_id = device_id or "dev_" + secrets.token_urlsafe(12)
        verifier = secrets.token_urlsafe(48)
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        started = self.client.post("/v1/cli/auth/requests", json={
            "device": {"device_id": device_id, "name": name, "os": "darwin", "architecture": "arm64", "flow_version": "0.2.0"},
            "code_challenge": pkce_challenge(verifier), "code_challenge_method": "S256", "state": state, "nonce": nonce})
        assert started.status_code == 201, started.text
        request_id = started.json()["auth_request_id"]
        approved = self.client.post(f"/v1/cli/auth/requests/{request_id}/approve", headers=self.web)
        assert approved.status_code == 200, approved.text
        token = self.client.post("/v1/cli/auth/token", json={"auth_request_id": request_id, "device_id": device_id,
                                                              "code_verifier": verifier})
        assert token.status_code == 200, token.text
        return Device(self.client, device_id, token.json())


class Device:
    def __init__(self, client: TestClient, device_id: str, tokens: dict) -> None:
        self.client, self.device_id, self.tokens = client, device_id, tokens

    @property
    def headers(self) -> dict:
        return {"Authorization": "Bearer " + self.tokens["access_token"]}

    def create_session(self, goal: str = "Finish authentication", session_id: str | None = None) -> str:
        session_id = session_id or "ses_" + secrets.token_hex(10)
        r = self.client.post("/v1/sessions", headers=self.headers, json={
            "id": session_id, "goal": goal, "started_at": "2026-09-19T10:00:00Z", "metadata": {}})
        assert r.status_code in (200, 201), r.text
        return session_id


def observation(sequence: int, **extra) -> dict:
    body = {"id": f"obs_{sequence:08d}", "sequence": sequence, "timestamp": "2026-09-19T10:00:%02dZ" % (sequence % 60),
            "activity": "Debugging JWT expiry tests", "category": "core_task", "goal_alignment": 0.9,
            "progress_signal": 0.5, "confidence": 0.9, "task_phase": "debugging", "application": "VS Code"}
    body.update(extra)
    return body


def event(sequence: int, type_: str = "observation.created", **data) -> dict:
    return {"id": f"evt_{sequence:08d}", "sequence": sequence, "type": type_,
            "timestamp": "2026-09-19T10:00:%02dZ" % (sequence % 60), "data": data}

"""HTTP client for the deployed FLOW account control plane."""

from __future__ import annotations

from typing import Any

import httpx
import time

from ..auth import CLIAuthRequest
from ..credentials import SecretStore
from ..device import metadata
from ..config import config_dir, web_endpoint
from .pkce import authorization_url


class AccountClientError(RuntimeError):
    pass


class AccountClient:
    def __init__(self, base_url: str | None = None, *, secrets: SecretStore, client: httpx.Client | None = None) -> None:
        self.base_url = (base_url or web_endpoint()).rstrip("/")
        self.secrets = secrets
        self.http = client or httpx.Client(timeout=20, follow_redirects=False)
        self.user_code: str | None = None

    def start_login(self) -> tuple[CLIAuthRequest, str, str]:
        request = CLIAuthRequest.create()
        response = self._post("/api/cli/auth/requests", {
            "state": request.state, "code_challenge": request.challenge, "device": metadata(config_dir()),
        }, auth=False)
        request_id = self._text(response, "request_id")
        return request, request_id, authorization_url(self.base_url, request_id, request.state)

    def exchange(self, request_id: str, request: CLIAuthRequest) -> dict[str, Any]:
        result = self._post("/api/cli/auth/token", {"request_id": request_id, "code_verifier": request.verifier}, auth=False)
        self._save_tokens(result)
        return result

    def wait_for_approval(self, request_id: str, request: CLIAuthRequest, *, timeout: float = 300) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            body = self._get_public(f"/api/cli/auth/requests/{request_id}")
            status = body.get("status")
            if status == "approved":
                return self.exchange(request_id, request)
            if status in {"denied", "expired", "consumed"}:
                raise AccountClientError(f"authorization request {status}")
            time.sleep(1)
        raise AccountClientError("timed out waiting for browser authorization")

    def refresh(self) -> dict[str, Any]:
        token = self.secrets.get("account_refresh_token")
        if not token:
            raise AccountClientError("FLOW is not signed in")
        result = self._post("/api/cli/auth/refresh", {"refresh_token": token}, auth=False)
        self._save_tokens(result)
        return result

    def logout(self) -> None:
        token = self.secrets.get("account_refresh_token")
        if token:
            try:
                self._post("/api/cli/auth/logout", {"refresh_token": token}, auth=False)
            finally:
                self.secrets.delete("account_access_token")
                self.secrets.delete("account_refresh_token")

    def whoami(self) -> dict[str, Any]:
        return self._get("/api/cli/me")

    def devices(self) -> dict[str, Any]:
        return self._get("/api/cli/devices")

    def heartbeat(self, health: dict[str, str], active_sessions: list[str] | None = None) -> dict[str, Any]:
        return self._post("/api/cli/heartbeat", {"health": health, "active_sessions": active_sessions or []})

    def _get(self, path: str) -> dict[str, Any]:
        token = self.secrets.get("account_access_token")
        response = self.http.get(self.base_url + path, headers=self._headers(token))
        return self._decode(response)

    def _get_public(self, path: str) -> dict[str, Any]:
        return self._decode(self.http.get(self.base_url + path))

    def _post(self, path: str, body: dict[str, Any], *, auth: bool = True) -> dict[str, Any]:
        token = self.secrets.get("account_access_token") if auth else None
        response = self.http.post(self.base_url + path, json=body, headers=self._headers(token))
        return self._decode(response)

    @staticmethod
    def _headers(token: str | None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"} if token else {}

    def _save_tokens(self, result: dict[str, Any]) -> None:
        access, refresh = result.get("access_token"), result.get("refresh_token")
        if not isinstance(access, str) or not isinstance(refresh, str):
            raise AccountClientError("account service returned incomplete credentials")
        self.secrets.set("account_access_token", access)
        self.secrets.set("account_refresh_token", refresh)

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise AccountClientError(f"account service returned HTTP {response.status_code}") from exc
        if not response.is_success:
            raise AccountClientError(str(body.get("message", body.get("detail", "account request failed"))))
        if not isinstance(body, dict):
            raise AccountClientError("account service returned an invalid response")
        return body

    @staticmethod
    def _text(body: dict[str, Any], name: str) -> str:
        value = body.get(name)
        if not isinstance(value, str) or not value:
            raise AccountClientError(f"account response omitted {name}")
        return value

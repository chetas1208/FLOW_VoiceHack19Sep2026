"""Typed cloud client: bearer auth with transparent refresh, retry of transient failures only.

Errors: ``CloudUnauthorized`` (sign in again), ``CloudUnavailable`` (transient, retry later), ``CloudRejected``
(permanent 4xx). Every ingest call is idempotent by client-chosen id, so retrying is always safe.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from ..config import FLOW_VERSION, api_endpoint
from ..credentials import CredentialStore
from ..profiles import require_secure_url
from .errors import CloudError, CloudRejected, CloudUnauthorized, CloudUnavailable, UNAUTHORIZED_HELP
from .tokens import TokenManager

TRANSIENT_STATUS = {408, 425, 429}


class CloudClient:
    def __init__(self, credentials: CredentialStore, endpoint: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None, *, retries: int = 2, timeout: float = 10.0,
                 lock_path: str | Path | None = None, tokens: TokenManager | None = None,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> None:
        self.credentials = credentials
        self.endpoint = require_secure_url((endpoint or api_endpoint()).rstrip("/"))
        self.transport, self.retries, self.timeout, self._sleep = transport, retries, timeout, sleep
        self.tokens = tokens or TokenManager(credentials, self.endpoint, transport=transport, lock_path=lock_path,
                                             timeout=timeout)
        self._http_by_loop: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}

    # ---- transport -----------------------------------------------------------------------------
    def _http(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        client = self._http_by_loop.get(loop)
        if client is None or client.is_closed:
            client = self._http_by_loop[loop] = httpx.AsyncClient(
                base_url=self.endpoint, timeout=httpx.Timeout(self.timeout, connect=5.0), transport=self.transport,
                headers={"X-Flow-Client-Version": FLOW_VERSION, "User-Agent": f"flow-cli/{FLOW_VERSION}"})
        return client

    async def aclose(self) -> None:
        clients, self._http_by_loop = list(self._http_by_loop.values()), {}
        for client in clients:
            if not client.is_closed:
                try:
                    await client.aclose()
                except RuntimeError:  # belonged to a loop that is already gone
                    pass

    async def __aenter__(self) -> "CloudClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def _send(self, method: str, path: str, body: Any, params: dict | None, token: str | None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        try:
            return await self._http().request(method, path, json=body, params=params, headers=headers)
        except httpx.HTTPError as exc:  # timeouts, connection failures, protocol errors
            raise CloudUnavailable(f"FLOW cloud unreachable ({type(exc).__name__})") from exc

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        if response.status_code < 400:
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise CloudError("FLOW cloud returned invalid JSON", status=response.status_code) from exc
        try:
            body = response.json()
            body = body if isinstance(body, dict) else {}
        except ValueError:
            body = {}
        code, message, request_id = body.get("error"), body.get("message") or f"FLOW API returned {response.status_code}", body.get("request_id")
        if response.status_code == 401:
            raise CloudUnauthorized(UNAUTHORIZED_HELP, status=401, code=code, request_id=request_id)
        if response.status_code in TRANSIENT_STATUS or response.status_code >= 500:
            try:
                retry_after = float(response.headers.get("Retry-After", ""))
            except ValueError:
                retry_after = None
            raise CloudUnavailable(message, retry_after=retry_after, status=response.status_code, code=code, request_id=request_id)
        raise CloudRejected(message, status=response.status_code, code=code, request_id=request_id)

    async def _once(self, method: str, path: str, body: Any, params: dict | None, auth: bool) -> Any:
        token = await self.tokens.access_token() if auth else None
        response = await self._send(method, path, body, params, token)
        if response.status_code == 401 and auth:
            token = await self.tokens.refresh(stale=token)  # single-flight; raises CloudUnauthorized if it cannot
            response = await self._send(method, path, body, params, token)
        return self._decode(response)

    async def _request(self, method: str, path: str, *, json: Any = None, params: dict | None = None,
                       auth: bool = True, retries: int | None = None) -> Any:
        attempts = (self.retries if retries is None else retries) + 1
        for attempt in range(attempts):
            try:
                return await self._once(method, path, json, params, auth)
            except CloudUnavailable as exc:
                if attempt + 1 >= attempts:
                    raise
                delay = exc.retry_after if exc.retry_after is not None else min(2.0, 0.2 * (2 ** attempt))
                await self._sleep(min(delay, 30.0))
        raise CloudUnavailable()  # pragma: no cover

    # ---- device authorization (public endpoints) -----------------------------------------------
    async def start_device_auth(self, device: dict[str, str], code_challenge: str, state: str, nonce: str) -> dict[str, Any]:
        return await self._request("POST", "/v1/cli/auth/requests", auth=False, retries=1, json={
            "device": {key: device[key] for key in ("device_id", "name", "os", "architecture", "flow_version")},
            "code_challenge": code_challenge, "code_challenge_method": "S256", "state": state, "nonce": nonce})

    async def poll_device_token(self, auth_request_id: str, device_id: str, code_verifier: str) -> dict[str, Any]:
        """Raises ``CloudRejected`` with ``.code`` in authorization_pending|slow_down|access_denied|expired_token|invalid_grant."""
        return await self._request("POST", "/v1/cli/auth/token", auth=False, retries=0, json={
            "auth_request_id": auth_request_id, "device_id": device_id, "code_verifier": code_verifier})

    async def logout(self, refresh_token: str) -> None:
        await self._request("POST", "/v1/auth/logout", auth=False, retries=0, json={"refresh_token": refresh_token})

    # ---- identity / devices --------------------------------------------------------------------
    async def whoami(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/me")

    async def list_devices(self) -> list[dict[str, Any]]:
        return (await self._request("GET", "/v1/devices")).get("items", [])

    async def revoke_device(self, device_id: str) -> None:
        await self._request("DELETE", f"/v1/devices/{device_id}")

    # ---- session ingest ------------------------------------------------------------------------
    async def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/v1/sessions", json=payload)

    async def post_observation(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/observations", json=payload)

    async def post_observations(self, session_id: str, observations: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/observations:batch", json={"observations": observations})

    async def post_event(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/events", json=payload)

    async def post_events(self, session_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/events:batch", json={"events": events})

    async def post_intervention(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/interventions", json=payload)

    async def post_segment(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/segments", json=payload)

    async def post_entities(self, session_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/entities:batch", json={"items": items})

    async def put_summary(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("PUT", f"/v1/sessions/{session_id}/summary", json=payload)

    async def stop_session(self, session_id: str, ended_at: str | None = None,
                           summary: dict[str, Any] | None = None) -> dict[str, Any]:
        body = {key: value for key, value in (("ended_at", ended_at), ("summary", summary)) if value is not None}
        return await self._request("POST", f"/v1/sessions/{session_id}/stop", json=body)

    # ---- reads ---------------------------------------------------------------------------------
    async def list_sessions(self, *, status: str | None = None, device_id: str | None = None, since: str | None = None,
                            until: str | None = None, limit: int = 50, cursor: str | None = None) -> dict[str, Any]:
        params = {key: value for key, value in (("status", status), ("device_id", device_id), ("since", since),
                                               ("until", until), ("limit", limit), ("cursor", cursor)) if value is not None}
        return await self._request("GET", "/v1/sessions", params=params)

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/sessions/{session_id}")

    # ---- commands (remote control) -------------------------------------------------------------
    async def create_command(self, command_type: str, *, session_id: str | None = None, device_id: str | None = None,
                             payload: dict[str, Any] | None = None, source: str = "cli",
                             command_id: str | None = None) -> dict[str, Any]:
        body = {"type": command_type, "payload": payload or {}, "source": source}
        for key, value in (("session_id", session_id), ("device_id", device_id), ("command_id", command_id)):
            if value:
                body[key] = value
        return await self._request("POST", "/v1/commands", json=body)

    async def get_command(self, command_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v1/commands/{command_id}")

    async def list_session_commands(self, session_id: str, limit: int = 50) -> dict[str, Any]:
        return await self._request("GET", f"/v1/sessions/{session_id}/commands", params={"limit": limit})

    async def ack_command(self, command_id: str, status: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"status": status}
        if result is not None:
            body["result"] = result
        return await self._request("POST", f"/v1/commands/{command_id}/ack", json=body)

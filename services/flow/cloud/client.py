"""Small cloud boundary; local SQLite remains the source of truth in dev mode."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import api_endpoint
from ..credentials import CredentialStore


class CloudError(RuntimeError):
    pass


class CloudClient:
    def __init__(self, credentials: CredentialStore, endpoint: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.credentials, self.endpoint = credentials, (endpoint or api_endpoint()).rstrip("/")
        self.transport = transport

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = self.credentials.get_token()
        headers = {"X-Flow-Client-Version": "0.2.0", **kwargs.pop("headers", {})}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(base_url=self.endpoint, timeout=10, transport=self.transport) as client:
                    response = await client.request(method, path, headers=headers, **kwargs)
                if response.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(.1 * (2 ** attempt)); continue
                if response.status_code >= 400:
                    raise CloudError(f"FLOW API returned {response.status_code}")
                return response.json() if response.content else {}
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise CloudError("FLOW cloud request failed") from exc
                await asyncio.sleep(.1 * (2 ** attempt))
            except ValueError as exc:
                raise CloudError("FLOW cloud returned invalid JSON") from exc
        raise CloudError("FLOW cloud request failed")

    async def create_session(self, goal: str, idempotency_key: str | None = None) -> dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return await self._request("POST", "/v1/sessions", json={"goal": goal}, headers=headers)

    async def upload_observation(self, session_id: str, observation: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/observations",
                                   json=observation, headers={"Idempotency-Key": observation["id"]})

    async def stop_session(self, session_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/v1/sessions/{session_id}/stop")

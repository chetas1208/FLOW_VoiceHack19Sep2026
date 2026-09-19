"""Small optional HTTP cloud boundary."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import local_api_endpoint


class CloudError(RuntimeError):
    pass


class CloudClient:
    def __init__(self, credentials: Any, endpoint: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.credentials, self.endpoint, self.transport = credentials, (endpoint or local_api_endpoint()).rstrip("/"), transport

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        token = self.credentials.get_token()
        headers = {"X-Flow-Client-Version": "0.2.0", **kwargs.pop("headers", {})}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(base_url=self.endpoint, timeout=10, transport=self.transport) as client:
                response = await client.request(method, path, headers=headers, **kwargs)
            if response.status_code >= 400:
                raise CloudError(f"FLOW API returned {response.status_code}")
            return response.json() if response.content else {}
        except httpx.HTTPError as exc:
            raise CloudError("FLOW cloud request failed") from exc
        except ValueError as exc:
            raise CloudError("FLOW cloud returned invalid JSON") from exc

"""Helpers shared by the command modules (no NAME, so it is not registered as a command)."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from typing import Any, Awaitable, TypeVar

from ..cloud.client import CloudClient
from ..config import api_endpoint, config_dir, data_dir
from ..credentials import CredentialStore, default_credential_store
from ..store import FlowStore

T = TypeVar("T")


def credential_store() -> CredentialStore:
    return default_credential_store(config_dir())


def make_client(store: CredentialStore | None = None, **kwargs: Any) -> CloudClient:
    return CloudClient(store or credential_store(), endpoint=api_endpoint(), **kwargs)


def existing_flow_store() -> FlowStore | None:
    """The local store if one exists; read-only commands must not create ``.local-runs`` as a side effect."""
    return FlowStore(data_dir()) if (data_dir() / "flow.sqlite3").exists() else None


def run_client(client: CloudClient, coro_factory) -> Any:
    """Run ``coro_factory(client)`` to completion and always close the client's connections."""
    async def go():
        try:
            return await coro_factory(client)
        finally:
            await client.aclose()
    return asyncio.run(go())


def error(message: str) -> None:
    print(f"flow: {message}", file=sys.stderr)


def ago(iso_value: str | None, now: datetime | None = None) -> str:
    if not iso_value:
        return "never"
    try:
        then = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    except ValueError:
        return iso_value
    then = then if then.tzinfo else then.replace(tzinfo=timezone.utc)
    seconds = int(((now or datetime.now(timezone.utc)) - then).total_seconds())
    if seconds < 5:
        return "just now"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60}m ago"
    if seconds < 172800:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def cloud_state_line(status: dict[str, Any]) -> str:
    state = status["state"]
    return {"connected": "connected", "offline": "offline (will retry)", "unauthorized": "unauthorized (run flow login)",
            "signed_out": "not signed in (local only; run flow login to sync)", "disabled": "disabled (FLOW_CLOUD_SYNC=off)",
            "stopped": "signed in, sync worker not running", "idle": "connected (no uploads yet)"}.get(state, state)

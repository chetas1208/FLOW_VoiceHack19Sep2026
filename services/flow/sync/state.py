"""Sync enablement and the shared sync status the CLI shows (written by the worker, read by ``flow status``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import api_endpoint, cloud_sync_disabled, config_dir
from ..credentials import CredentialStore, default_credential_store
from ..store import FlowStore

SYNC_STATE_KEY = "worker"
HEARTBEAT_STALE_SECONDS = 30.0
UNAUTHORIZED_MESSAGE = "Device authorization expired or revoked. Run flow login."


def cloud_sync_enabled(credentials: CredentialStore | None = None) -> bool:
    """Sync is on only while signed in (credentials for the active API) and not disabled by ``FLOW_CLOUD_SYNC=off``.

    Local-first: with no login every FLOW feature keeps working and nothing is queued for upload.
    """
    if cloud_sync_disabled():
        return False
    try:
        bundle = (credentials or default_credential_store(config_dir())).load_bundle()
        if not bundle or not bundle.get("access_token"):
            return False
        bound = bundle.get("api_url")
        return not bound or bound.rstrip("/") == api_endpoint().rstrip("/")
    except Exception:  # noqa: BLE001 - an unreadable keychain means "not signed in", never a crash
        return False


def _parse(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def read_sync_status(store: FlowStore, credentials: CredentialStore | None = None,
                     now: datetime | None = None) -> dict[str, Any]:
    """Combine credentials, the worker's persisted state and the outbox counters into one display record.

    ``state`` is one of ``signed_out``, ``connected``, ``offline``, ``unauthorized``, ``stopped`` (signed in but
    no worker is running, e.g. the daemon is stopped), ``idle`` (worker running, nothing sent yet) or ``disabled``.
    """
    from .outbox import SyncOutbox
    now = now or datetime.now(timezone.utc)
    stats = SyncOutbox(store).stats()
    worker = store.get_state(SYNC_STATE_KEY)
    if cloud_sync_disabled():
        state = "disabled"
    elif not cloud_sync_enabled(credentials):
        state = "signed_out"
    else:
        beat = _parse(worker.get("heartbeat_at"))
        alive = beat is not None and now - beat < timedelta(seconds=HEARTBEAT_STALE_SECONDS)
        state = worker.get("state", "idle") if alive else "stopped"
    return {"state": state, "last_sync_at": worker.get("last_sync_at"), "message": worker.get("message"),
            "last_error": worker.get("last_error") or stats.get("last_error"), "pending": stats["pending_total"],
            "failed": stats["failed"], "synced": stats["synced"], "oldest_pending_at": stats["oldest_pending_at"],
            "worker_running": state not in {"stopped", "signed_out", "disabled"}}

"""Push daemon/session state to the account control plane so the web app stays in sync."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ..credentials import default_secret_store
from .client import AccountClient, AccountClientError

if TYPE_CHECKING:
    from ..daemon import FlowDaemon

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_S = 45.0


def build_daemon_health(daemon: FlowDaemon) -> dict[str, str]:
    """Health keys must match the web control plane ``cleanHealth`` allowlist."""
    running = daemon.session_id is not None
    health: dict[str, str] = {
        "daemon": "running",
        "agent": "active" if running else "idle",
        "model": "ready_on_demand",
        "observer": "not_configured",
    }
    if daemon.runtime is not None:
        try:
            report = daemon.runtime.report()
            runtime = report.get("runtime") if isinstance(report, dict) else {}
            if isinstance(runtime, dict):
                obs = runtime.get("observer")
                if isinstance(obs, str) and obs:
                    health["observer"] = obs
        except Exception:  # noqa: BLE001
            health["observer"] = "starting"
    session = _current_session_dict(daemon)
    if session:
        health["session_id"] = str(session.get("id") or "")[:120]
        health["session_status"] = str(session.get("status") or "active")[:32]
        goal = str(session.get("goal") or "").strip()
        if goal:
            health["session_goal"] = goal[:200]
    return health


def active_session_ids(daemon: FlowDaemon) -> list[str]:
    if daemon.session_id:
        return [daemon.session_id]
    return []


def _current_session_dict(daemon: FlowDaemon) -> dict[str, Any] | None:
    if not daemon.session_id:
        return None
    try:
        session = daemon.manager.get_session(daemon.session_id)
        return session.to_dict()
    except Exception:  # noqa: BLE001
        return {"id": daemon.session_id, "status": "active", "goal": ""}


def push_heartbeat(daemon: FlowDaemon) -> bool:
    """Best-effort heartbeat; returns False when not signed in or unreachable."""
    store = default_secret_store()
    if not store.get("account_access_token"):
        return False
    client = AccountClient(secrets=store)
    health = build_daemon_health(daemon)
    sessions = active_session_ids(daemon)
    try:
        client.heartbeat(health, sessions)
        return True
    except AccountClientError as exc:
        if "expired" in str(exc).lower() or "401" in str(exc):
            try:
                client.refresh()
                client.heartbeat(health, sessions)
                return True
            except AccountClientError:
                log.warning("account heartbeat failed after refresh: %s", exc)
                return False
        log.warning("account heartbeat failed: %s", exc)
        return False


async def heartbeat_loop(daemon: FlowDaemon, interval: float = HEARTBEAT_INTERVAL_S) -> None:
    """Background task: keep web presence aligned with local daemon + session."""
    while True:
        try:
            push_heartbeat(daemon)
        except Exception:  # noqa: BLE001
            log.exception("unexpected heartbeat error")
        await asyncio.sleep(interval)

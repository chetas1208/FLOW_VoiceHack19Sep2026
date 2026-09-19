"""Health/presence snapshot sent in the device ``hello`` and every heartbeat.

The cloud marks a device ``degraded`` when any health value is ``error``, ``degraded`` or ``unavailable``, so these
words are used only when something really is broken or missing; ``idle``/``ready``/``muted`` are healthy.
"""

from __future__ import annotations

from typing import Any, Protocol

COMPONENTS = ("observer", "vision", "voice", "agent", "daemon")
_SEVERITY = {"error": 4, "unavailable": 3, "degraded": 3, "recovering": 2, "starting": 1}


class HostLike(Protocol):
    sessions: dict[str, Any]

    def component_health(self) -> dict[str, str]: ...


def _worst(values: list[str], default: str) -> str:
    if not values:
        return default
    return max(values, key=lambda value: _SEVERITY.get(value, 0))


def build_health(host: HostLike | None) -> dict[str, str]:
    """{observer, vision, voice, agent, daemon} for the whole daemon (worst state across active sessions)."""
    if host is None:
        return {"observer": "idle", "vision": "not_loaded", "voice": "not_loaded", "agent": "idle", "daemon": "ok"}
    health = dict(host.component_health())
    health.setdefault("daemon", "ok")
    return {name: str(health.get(name, "unknown")) for name in COMPONENTS}


def active_session_ids(host: HostLike | None) -> list[str]:
    if host is None:
        return []
    return [sid for sid in host.sessions][:20]


def presence_snapshot(host: HostLike | None, flow_version: str, device_id: str | None = None) -> dict[str, Any]:
    """Body shared by ``hello`` and ``heartbeat`` frames (the caller adds ``type``)."""
    snapshot: dict[str, Any] = {"flow_version": flow_version, "active_sessions": active_session_ids(host),
                                "health": build_health(host)}
    if device_id:
        snapshot["device_id"] = device_id
    return snapshot

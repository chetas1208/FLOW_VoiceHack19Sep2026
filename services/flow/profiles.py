"""Deployment settings shared by the daemon and CLI.

FLOW has no hosted backend: the daemon on the user's Mac is the API. All that is configurable is where the
static web app lives, which port the daemon listens on, and which browser origins may call it.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

DEFAULT_WEB_URL = "https://app.flow.ai"
DEFAULT_LOCAL_PORT = 8765
DEFAULT_DEV_ORIGIN = "http://localhost:5173"


def web_url() -> str:
    """``FLOW_WEB_URL``: the (static) web app that pairs with the daemon."""
    return (os.getenv("FLOW_WEB_URL") or DEFAULT_WEB_URL).strip().rstrip("/")


def local_port() -> int:
    """``FLOW_LOCAL_PORT`` (default 8765)."""
    raw = os.getenv("FLOW_LOCAL_PORT", str(DEFAULT_LOCAL_PORT)).strip()
    try:
        port = int(raw)
    except ValueError as exc:
        raise ValueError(f"FLOW_LOCAL_PORT must be an integer, got {raw!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError("FLOW_LOCAL_PORT must be between 1 and 65535")
    return port


def bind_host() -> str:
    """The daemon binds loopback unless ``FLOW_BIND_HOST`` explicitly says otherwise."""
    return (os.getenv("FLOW_BIND_HOST") or "127.0.0.1").strip()


def local_origin() -> str:
    return f"http://127.0.0.1:{local_port()}"


def normalize_origin(value: str) -> str | None:
    """``scheme://host[:port]`` with no path or trailing slash; ``None`` for anything that is not a plain origin."""
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"} \
            or parsed.params or parsed.query or parsed.fragment:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{port}"


def allowed_origins() -> tuple[str, ...]:
    """Browser origins allowed to call the daemon: ``FLOW_ALLOWED_ORIGINS`` (comma separated; ``*`` is never
    honoured) or the defaults (web app + Vite dev server), always plus the daemon's own origin for ``/ui``."""
    configured = os.getenv("FLOW_ALLOWED_ORIGINS")
    raw = [item for item in (configured or "").split(",") if item.strip()] or [web_url(), DEFAULT_DEV_ORIGIN]
    port = local_port()
    origins: list[str] = []
    for item in [*raw, f"http://127.0.0.1:{port}", f"http://localhost:{port}"]:
        origin = normalize_origin(item)
        if origin and origin not in origins:
            origins.append(origin)
    return tuple(origins)

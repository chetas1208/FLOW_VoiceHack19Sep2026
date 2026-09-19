"""Local-first FLOW configuration."""

import os
from pathlib import Path

from . import profiles

FLOW_VERSION = "0.2.0"


def data_dir() -> Path:
    return Path(os.getenv("FLOW_DATA_DIR", os.getenv("QA_DATA_DIR", ".local-runs"))).resolve()


def store_screenshots() -> bool:
    return os.getenv("FLOW_STORE_SCREENSHOTS", "false").lower() in {"1", "true", "yes"}


def screenshot_retention_seconds() -> int:
    try:
        return max(0, int(os.getenv("FLOW_SCREENSHOT_RETENTION_SECONDS", "0")))
    except ValueError:
        return 0


def config_dir() -> Path:
    return Path(os.getenv("FLOW_CONFIG_DIR", str(Path.home() / ".config" / "flow"))).expanduser()


def local_port() -> int:
    return profiles.local_port()


def local_api_endpoint() -> str:
    """Where the daemon serves its API (loopback by default)."""
    return profiles.local_origin()


def web_endpoint() -> str:
    """The static web app (``FLOW_WEB_URL``, default https://app.flow.ai)."""
    return profiles.web_url()


def allowed_origins() -> tuple[str, ...]:
    return profiles.allowed_origins()


def drift_seconds() -> float:
    """Sustained-drift threshold for real sessions (the scorer default is a test-friendly 2 s)."""
    try:
        return max(0.0, float(os.getenv("FLOW_DRIFT_SECONDS", "120")))
    except ValueError:
        return 120.0

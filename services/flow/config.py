"""Local-first FLOW configuration."""

import os
from pathlib import Path

from . import profiles

FLOW_VERSION = "0.2.0"


def _flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def data_dir() -> Path:
    return Path(os.getenv("FLOW_DATA_DIR", os.getenv("QA_DATA_DIR", ".local-runs"))).resolve()


def store_screenshots() -> bool:
    return _flag("FLOW_STORE_SCREENSHOTS")


def screenshot_retention_seconds() -> int:
    try:
        return max(0, int(os.getenv("FLOW_SCREENSHOT_RETENTION_SECONDS", "0")))
    except ValueError:
        return 0


def config_dir() -> Path:
    return Path(os.getenv("FLOW_CONFIG_DIR", str(Path.home() / ".config" / "flow"))).expanduser()


def api_endpoint() -> str:
    """Cloud API base URL: ``FLOW_API_URL`` or the active profile's."""
    return profiles.api_url()


def web_endpoint() -> str:
    return profiles.web_url()


def local_api_endpoint() -> str:
    """The local developer API (``services.platform``), not the FLOW cloud."""
    return os.getenv("FLOW_LOCAL_API_URL", "http://127.0.0.1:8080").rstrip("/")


def auth_mode() -> str:
    return profiles.resolve_auth_mode()


def cloud_sync_disabled() -> bool:
    """Kill switch: ``FLOW_CLOUD_SYNC=off`` keeps FLOW purely local even when signed in."""
    return os.getenv("FLOW_CLOUD_SYNC", "auto").strip().lower() in {"0", "off", "false", "no"}


def sync_window_titles() -> bool:
    return _flag("FLOW_SYNC_WINDOW_TITLES")


def sync_evidence() -> bool:
    return _flag("FLOW_SYNC_EVIDENCE")


def drift_seconds() -> float:
    """Sustained-drift threshold for real sessions (the scorer default is a test-friendly 2 s)."""
    try:
        return max(0.0, float(os.getenv("FLOW_DRIFT_SECONDS", "120")))
    except ValueError:
        return 120.0

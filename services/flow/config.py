"""Local-first FLOW configuration."""

import os
from pathlib import Path


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


def api_endpoint() -> str:
    return os.getenv("FLOW_API_URL", "http://127.0.0.1:8080")


def web_endpoint() -> str:
    return os.getenv("FLOW_WEB_URL", "https://app.flow.ai")

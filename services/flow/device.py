"""Stable FLOW device identity without collecting hardware identifiers."""

from __future__ import annotations

import json
import secrets
import socket
import sys
from pathlib import Path


def device_id(config_dir: Path) -> str:
    path = config_dir / "device.json"
    try:
        return json.loads(path.read_text())["device_id"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        config_dir.mkdir(parents=True, exist_ok=True)
        value = "dev_" + secrets.token_urlsafe(18)
        path.write_text(json.dumps({"device_id": value}))
        path.chmod(0o600)
        return value


def metadata(config_dir: Path) -> dict[str, str]:
    return {"device_id": device_id(config_dir), "os": sys.platform,
            "hostname": socket.gethostname(), "flow_version": "0.2.0"}

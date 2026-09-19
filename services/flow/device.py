"""Stable FLOW device identity without collecting hardware identifiers (no serial numbers, UUIDs or MACs)."""

from __future__ import annotations

import json
import os
import platform
import secrets
import socket
import subprocess
import tempfile
from pathlib import Path

from .config import FLOW_VERSION


def device_id(config_dir: Path) -> str:
    path = config_dir / "device.json"
    try:
        return json.loads(path.read_text())["device_id"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        config_dir.mkdir(parents=True, exist_ok=True)
        value = "dev_" + secrets.token_urlsafe(18)
        fd, tmp = tempfile.mkstemp(dir=config_dir, prefix=".device.")
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(json.dumps({"device_id": value}))
        try:  # first writer wins, so two processes never disagree about the id
            os.link(tmp, path)
        except FileExistsError:
            pass
        except OSError:  # filesystems without hard links
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        try:
            return json.loads(path.read_text())["device_id"]
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return value


def device_name() -> str:
    """Human name: the macOS Computer Name (``scutil``), otherwise the hostname."""
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(["scutil", "--get", "ComputerName"], capture_output=True, text=True,
                                    timeout=3, check=False)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()[:200]
        except (OSError, subprocess.SubprocessError):
            pass
    return (socket.gethostname() or "unknown-host")[:200]


def os_label() -> str:
    if platform.system() == "Darwin":
        return f"macOS {platform.mac_ver()[0]}".strip()
    return platform.system() or "unknown"


def metadata(config_dir: Path) -> dict[str, str]:
    return {"device_id": device_id(config_dir), "name": device_name(), "os": os_label()[:50],
            "architecture": (platform.machine() or "unknown")[:50], "flow_version": FLOW_VERSION}

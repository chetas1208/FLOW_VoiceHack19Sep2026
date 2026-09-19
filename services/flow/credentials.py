"""Credential storage with a safe test backend and optional macOS Keychain."""

from __future__ import annotations

import getpass
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Protocol


class CredentialStore(Protocol):
    def save_token(self, token: str, refresh_token: str | None = None) -> None: ...
    def get_token(self) -> str | None: ...
    def get_refresh_token(self) -> str | None: ...
    def delete_token(self) -> None: ...


class MemoryCredentialStore:
    def __init__(self) -> None:
        self._token: str | None = None
        self._refresh: str | None = None

    def save_token(self, token: str, refresh_token: str | None = None) -> None:
        self._token, self._refresh = token, refresh_token

    def get_token(self) -> str | None:
        return self._token

    def get_refresh_token(self) -> str | None:
        return self._refresh

    def delete_token(self) -> None:
        self._token = self._refresh = None


class FileCredentialStore:
    """Test/development fallback; production macOS uses Keychain."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def save_token(self, token: str, refresh_token: str | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"token": token, "refresh_token": refresh_token}))
        os.chmod(self.path, 0o600)

    def _read(self) -> dict[str, str | None]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def get_token(self) -> str | None:
        return self._read().get("token")

    def get_refresh_token(self) -> str | None:
        return self._read().get("refresh_token")

    def delete_token(self) -> None:
        self.path.unlink(missing_ok=True)


class MacKeychainCredentialStore:
    service = "ai.flow.cli"

    def _run(self, *args: str, input: str | None = None) -> str | None:
        result = subprocess.run(["security", *args], input=input, text=True,
                                capture_output=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def save_token(self, token: str, refresh_token: str | None = None) -> None:
        self.delete_token()
        payload = json.dumps({"token": token, "refresh_token": refresh_token})
        self._run("add-generic-password", "-a", getpass.getuser(), "-s", self.service, "-w", payload, "-U")

    def get_token(self) -> str | None:
        raw = self._run("find-generic-password", "-a", getpass.getuser(), "-s", self.service, "-w")
        try:
            return json.loads(raw)["token"] if raw else None
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    def get_refresh_token(self) -> str | None:
        raw = self._run("find-generic-password", "-a", getpass.getuser(), "-s", self.service, "-w")
        try:
            return json.loads(raw).get("refresh_token") if raw else None
        except (json.JSONDecodeError, TypeError):
            return None

    def delete_token(self) -> None:
        self._run("delete-generic-password", "-a", getpass.getuser(), "-s", self.service)


def default_credential_store(config_dir: Path | None = None) -> CredentialStore:
    if platform.system() == "Darwin":
        return MacKeychainCredentialStore()
    return FileCredentialStore((config_dir or Path.home() / ".config" / "flow") / "credentials.json")

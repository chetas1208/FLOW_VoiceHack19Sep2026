"""Credential storage.

The secret material is a single JSON *bundle*::

    {access_token, access_expires_at, refresh_token, refresh_expires_at, user{id,email}, device_id, api_url}

Backends, strongest first:

* ``KeyringCredentialStore`` - the ``keyring`` package: macOS Keychain through the Security framework
  (nothing secret ever appears on a command line), or a usable Linux Secret Service.
* ``MacKeychainCredentialStore`` - the ``security`` CLI, only when ``keyring`` is unusable. Weaker: the
  secret passes through a helper process (kept off argv by feeding ``security -i`` on stdin).
* ``FileCredentialStore`` - a 0600 file, the Linux fallback (``flow doctor`` warns about it) and the test backend.

Non-secret account facts (email, device name, API URL) live in ``account.json`` (0600). Bearer and refresh
tokens are **never** written to ``config.json`` or ``account.json``.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

SERVICE = "ai.flow.cli"
ACCOUNT_KEYS = ("email", "user_id", "device_name", "device_id", "api_url", "logged_in_at")


class CredentialStoreError(RuntimeError):
    pass


class CredentialStore(Protocol):
    def save_token(self, token: str, refresh_token: str | None = None) -> None: ...
    def get_token(self) -> str | None: ...
    def get_refresh_token(self) -> str | None: ...
    def delete_token(self) -> None: ...
    def load_bundle(self) -> dict[str, Any] | None: ...
    def save_bundle(self, bundle: dict[str, Any]) -> None: ...


# ---- bundle helpers -----------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def new_bundle(response: dict[str, Any], *, device_id: str, api_url: str, now: datetime | None = None) -> dict[str, Any]:
    """Build a bundle from a ``/v1/cli/auth/token`` or ``/v1/auth/refresh`` response."""
    now = now or _now()
    user = response.get("user") or {}
    bundle: dict[str, Any] = {
        "access_token": response["access_token"],
        "access_expires_at": (now + timedelta(seconds=int(response.get("expires_in", 900)))).isoformat(),
        "refresh_token": response.get("refresh_token"),
        "user": {"id": user.get("id"), "email": user.get("email")},
        "device_id": device_id, "api_url": api_url.rstrip("/")}
    if response.get("refresh_expires_in"):
        bundle["refresh_expires_at"] = (now + timedelta(seconds=int(response["refresh_expires_in"]))).isoformat()
    return bundle


def access_is_fresh(bundle: dict[str, Any], skew: float = 60.0, now: datetime | None = None) -> bool:
    """True if the access token is usable for at least ``skew`` more seconds (no expiry recorded = static token)."""
    if not bundle.get("access_token"):
        return False
    expires = parse_time(bundle.get("access_expires_at"))
    return expires is None or (expires - (now or _now())).total_seconds() > skew


# ---- shared implementation ----------------------------------------------------------------------
class _BundleStore:
    backend = "abstract"
    secure = True
    description = ""

    def _read_raw(self) -> dict[str, Any] | None:  # pragma: no cover - interface
        raise NotImplementedError

    def _write_raw(self, bundle: dict[str, Any]) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def _delete_raw(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def load_bundle(self) -> dict[str, Any] | None:
        raw = self._read_raw()
        if not isinstance(raw, dict):
            return None
        if "access_token" not in raw and "token" in raw:  # pre-bundle layout
            raw = {"access_token": raw["token"], "refresh_token": raw.get("refresh_token")}
        return raw or None

    def save_bundle(self, bundle: dict[str, Any]) -> None:
        self._write_raw(dict(bundle))

    def save_token(self, token: str, refresh_token: str | None = None) -> None:
        self.save_bundle({"access_token": token, "refresh_token": refresh_token})

    def get_token(self) -> str | None:
        return (self.load_bundle() or {}).get("access_token")

    def get_refresh_token(self) -> str | None:
        return (self.load_bundle() or {}).get("refresh_token")

    def delete_token(self) -> None:
        self._delete_raw()

    clear = delete_token


class MemoryCredentialStore(_BundleStore):
    backend, description = "memory", "in-process memory (tests)"

    def __init__(self) -> None:
        self._bundle: dict[str, Any] | None = None

    def _read_raw(self):
        return dict(self._bundle) if self._bundle else None

    def _write_raw(self, bundle):
        self._bundle = bundle

    def _delete_raw(self):
        self._bundle = None


def _atomic_private_write(path: Path, data: str) -> None:
    """Write ``data`` to ``path`` with mode 0600 via an atomic rename (never briefly world-readable)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


class FileCredentialStore(_BundleStore):
    """0600 JSON file. Test/development backend and the Linux fallback when no keyring is usable."""

    backend, secure = "file", False
    description = "0600 file (weaker than an OS keychain)"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def _read_raw(self):
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def _write_raw(self, bundle):
        _atomic_private_write(self.path, json.dumps(bundle))

    def _delete_raw(self):
        self.path.unlink(missing_ok=True)


class KeyringCredentialStore(_BundleStore):
    """``keyring`` package: macOS Keychain via the Security framework, or a Linux Secret Service."""

    backend = "keyring"

    def __init__(self, service: str = SERVICE, username: str | None = None, keyring_module: Any = None) -> None:
        self.service = service
        self.username = username or _username()
        if keyring_module is None:
            import keyring as keyring_module  # noqa: PLW0127
        self._keyring = keyring_module

    @property
    def description(self) -> str:  # type: ignore[override]
        return "macOS Keychain (Security framework)" if platform.system() == "Darwin" else "OS keyring"

    def _read_raw(self):
        try:
            raw = self._keyring.get_password(self.service, self.username)
        except Exception:  # noqa: BLE001 - a locked/unavailable keychain reads as "no credentials"
            return None
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return None

    def _write_raw(self, bundle):
        try:
            self._keyring.set_password(self.service, self.username, json.dumps(bundle))
        except Exception as exc:  # noqa: BLE001
            raise CredentialStoreError(f"could not write to the system keychain: {exc}") from exc

    def _delete_raw(self):
        try:
            self._keyring.delete_password(self.service, self.username)
        except Exception:  # noqa: BLE001 - nothing stored, or already gone
            pass


class MacKeychainCredentialStore(_BundleStore):
    """``security`` CLI fallback (weaker than ``keyring``).

    Secrets are never placed on argv: commands are fed to ``security -i`` on stdin with the payload
    hex-encoded (``-X``). The payload is still handled by a helper process, hence "weaker".
    """

    backend, secure = "security-cli", False
    description = "macOS Keychain via the `security` CLI (weaker fallback; install the `keyring` package)"

    def __init__(self, service: str = SERVICE, username: str | None = None) -> None:
        self.service, self.username = service, username or _username()

    def _run(self, *args: str) -> str | None:
        result = subprocess.run(["security", *args], text=True, capture_output=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None

    def _interactive(self, command: str) -> bool:
        result = subprocess.run(["security", "-i"], input=command + "\n", text=True, capture_output=True, check=False)
        return result.returncode == 0

    def _read_raw(self):
        raw = self._run("find-generic-password", "-a", self.username, "-s", self.service, "-w")
        if not raw:
            return None
        try:  # `-w` prints hex when the stored bytes are not printable
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                return json.loads(bytes.fromhex(raw).decode())
            except (ValueError, json.JSONDecodeError):
                return None

    def _write_raw(self, bundle):
        payload = json.dumps(bundle).encode().hex()
        if not self._interactive(f"add-generic-password -a {_q(self.username)} -s {_q(self.service)} -X {payload} -U"):
            raise CredentialStoreError("could not write to the macOS Keychain with the security CLI")

    def _delete_raw(self):
        self._run("delete-generic-password", "-a", self.username, "-s", self.service)


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _username() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return "flow"


def keyring_usable() -> bool:
    """A real keyring backend (not the ``fail``/``null`` placeholders) is available."""
    try:
        import keyring
        from keyring.backends import fail
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or type(backend).__module__.endswith(".null"):
            return False
        return float(backend.priority) > 0
    except Exception:  # noqa: BLE001 - not installed, or no viable backend on this host
        return False


def default_credential_store(config_dir: Path | None = None) -> CredentialStore:
    """Pick the strongest available backend. ``FLOW_CREDENTIAL_BACKEND`` (keyring|security|file) forces one."""
    directory = Path(config_dir) if config_dir else Path.home() / ".config" / "flow"
    forced = os.getenv("FLOW_CREDENTIAL_BACKEND", "auto").strip().lower()
    if forced == "file":
        return FileCredentialStore(directory / "credentials.json")
    if forced == "security":
        return MacKeychainCredentialStore()
    if forced == "keyring" or keyring_usable():
        return KeyringCredentialStore()
    if platform.system() == "Darwin":
        return MacKeychainCredentialStore()
    return FileCredentialStore(directory / "credentials.json")


# ---- non-secret account info --------------------------------------------------------------------
def account_path(config_dir: Path) -> Path:
    return Path(config_dir) / "account.json"


def save_account(config_dir: Path, info: dict[str, Any]) -> None:
    """Persist non-secret account facts. Only whitelisted keys are written; tokens can never land here."""
    clean = {key: info[key] for key in ACCOUNT_KEYS if info.get(key) is not None}
    _atomic_private_write(account_path(config_dir), json.dumps(clean, indent=2))


def load_account(config_dir: Path) -> dict[str, Any]:
    try:
        data = json.loads(account_path(config_dir).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def clear_account(config_dir: Path) -> None:
    account_path(config_dir).unlink(missing_ok=True)

"""Secure storage for the daemon's long-term secrets.

FLOW has no accounts and no cloud tokens. The daemon owns two secrets that must survive restarts and must never
sit in a world-readable file or on a command line:

* ``identity_ed25519`` - the private half of the daemon's Ed25519 identity (browsers pin its fingerprint);
* ``jwt_signing_secret`` - the HMAC key that signs the short-lived access tokens it issues to paired browsers.

Backends, strongest first:

* ``KeyringSecretStore`` - the ``keyring`` package: the macOS Keychain through the Security framework (or a usable
  Linux Secret Service). Secrets go straight to the OS API; nothing is ever passed on argv.
* ``FileSecretStore`` - a 0600 JSON file in a 0700 directory, written atomically. The Linux/headless fallback;
  ``flow doctor`` reports it as weaker than a keychain.
* ``MemorySecretStore`` - tests.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import secrets
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

try:  # POSIX only; FLOW targets macOS and Linux
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

SERVICE = "ai.flow.daemon"
IDENTITY_KEY = "identity_ed25519"
SIGNING_KEY = "jwt_signing_secret"


class SecretStoreError(RuntimeError):
    pass


class SecretStore(Protocol):
    backend: str
    secure: bool
    description: str

    def get(self, name: str) -> str | None: ...
    def set(self, name: str, value: str) -> None: ...
    def delete(self, name: str) -> None: ...


class MemorySecretStore:
    backend, secure, description = "memory", False, "in-process memory (tests)"

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def set(self, name: str, value: str) -> None:
        self._values[name] = value

    def delete(self, name: str) -> None:
        self._values.pop(name, None)


class _LegacyCredentialMixin:
    """Compatibility surface for the original CLI token bundle API."""

    def load_bundle(self) -> dict[str, Any] | None:
        value = self.get("credential_bundle")
        if not value:
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def save_bundle(self, bundle: dict[str, Any]) -> None:
        self.set("credential_bundle", json.dumps(bundle, sort_keys=True))

    def save_token(self, token: str, refresh_token: str | None = None) -> None:
        self.save_bundle({"access_token": token, "refresh_token": refresh_token})

    def get_token(self) -> str | None:
        return (self.load_bundle() or {}).get("access_token")

    def get_refresh_token(self) -> str | None:
        return (self.load_bundle() or {}).get("refresh_token")

    def delete_token(self) -> None:
        self.delete("credential_bundle")

    clear = delete_token


def atomic_private_write(path: Path, data: str) -> None:
    """Write ``data`` to ``path`` (mode 0600, parent 0700) through an atomic rename: never briefly readable by others."""
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


class FileSecretStore:
    backend, secure = "file", False
    description = "0600 file (weaker than an OS keychain)"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, name: str) -> str | None:
        value = self._read().get(name)
        return value if isinstance(value, str) else None

    def set(self, name: str, value: str) -> None:
        values = self._read()
        values[name] = value
        atomic_private_write(self.path, json.dumps(values))

    def delete(self, name: str) -> None:
        values = self._read()
        if values.pop(name, None) is not None:
            if values:
                atomic_private_write(self.path, json.dumps(values))
            else:
                self.path.unlink(missing_ok=True)


class KeyringSecretStore:
    """``keyring``: macOS Keychain via the Security framework (or a Linux Secret Service)."""

    backend, secure = "keyring", True

    def __init__(self, service: str = SERVICE, keyring_module: Any = None) -> None:
        self.service = service
        if keyring_module is None:
            import keyring as keyring_module  # noqa: PLW0127
        self._keyring = keyring_module

    @property
    def description(self) -> str:  # type: ignore[override]
        return "macOS Keychain (Security framework)" if platform.system() == "Darwin" else "OS keyring"

    def get(self, name: str) -> str | None:
        try:
            return self._keyring.get_password(self.service, name)
        except Exception as exc:  # noqa: BLE001 - a locked keychain must not look like "no secret" and trigger re-keying
            raise SecretStoreError(f"could not read {name!r} from the system keychain: {exc}") from exc

    def set(self, name: str, value: str) -> None:
        try:
            self._keyring.set_password(self.service, name, value)
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreError(f"could not write {name!r} to the system keychain: {exc}") from exc

    def delete(self, name: str) -> None:
        try:
            self._keyring.delete_password(self.service, name)
        except Exception:  # noqa: BLE001 - already absent
            pass


# Public aliases retained for callers written against the first FLOW CLI.
class MemoryCredentialStore(_LegacyCredentialMixin, MemorySecretStore):
    pass


class FileCredentialStore(_LegacyCredentialMixin, FileSecretStore):
    pass


def keyring_usable() -> bool:
    """A real keyring backend (not the ``fail``/``null`` placeholders) is available on this host."""
    try:
        import keyring
        from keyring.backends import fail
        backend = keyring.get_keyring()
        if isinstance(backend, fail.Keyring) or type(backend).__module__.endswith(".null"):
            return False
        return float(backend.priority) > 0
    except Exception:  # noqa: BLE001 - not installed, or no viable backend
        return False


def default_secret_store(config_dir: Path | None = None) -> SecretStore:
    """Strongest available backend. ``FLOW_SECRET_BACKEND`` (``keyring`` | ``file``) forces one."""
    directory = Path(config_dir) if config_dir else Path.home() / ".config" / "flow"
    forced = os.getenv("FLOW_SECRET_BACKEND", "auto").strip().lower()
    if forced == "file":
        return FileSecretStore(directory / "secrets.json")
    if forced == "keyring" or keyring_usable():
        return KeyringSecretStore()
    return FileSecretStore(directory / "secrets.json")


def describe_secret_store(store: SecretStore) -> dict[str, Any]:
    return {"backend": store.backend, "secure": store.secure, "description": store.description}


# ---- get-or-create (race-safe across the CLI and the daemon) ------------------------------------
class _FileLock:
    def __init__(self, path: Path, timeout: float = 10.0) -> None:
        self.path, self.timeout, self._fd = path, timeout, None

    def __enter__(self) -> "_FileLock":
        if fcntl is None:  # pragma: no cover
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    raise SecretStoreError("timed out waiting for the FLOW secrets lock") from None
                time.sleep(0.02)

    def __exit__(self, *exc: Any) -> None:
        if self._fd is not None:
            os.close(self._fd)  # closing drops the flock
            self._fd = None


def get_or_create_secret(store: SecretStore, name: str, factory: Callable[[], str],
                         lock_path: Path | None = None) -> str:
    """Return the stored secret or create it exactly once, even if two FLOW processes start together."""
    existing = store.get(name)
    if existing:
        return existing
    from .config import config_dir
    with _FileLock(lock_path or config_dir() / "secrets.lock"):
        existing = store.get(name)  # somebody else may have created it while we waited
        if existing:
            return existing
        value = factory()
        store.set(name, value)
        return value


def signing_secret(store: SecretStore, lock_path: Path | None = None) -> bytes:
    """The daemon's 256-bit HMAC key for access-token JWTs."""
    encoded = get_or_create_secret(store, SIGNING_KEY, lambda: base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
                                   lock_path)
    return base64.urlsafe_b64decode(encoded.encode())


@dataclass(frozen=True, slots=True)
class DaemonIdentity:
    """Long-term Ed25519 identity. ``fingerprint`` = lowercase hex SHA-256 of the raw 32-byte public key."""
    private_key: Any
    public_key_raw: bytes
    fingerprint: str

    @property
    def fingerprint_display(self) -> str:
        return ":".join(self.fingerprint[i:i + 4] for i in range(0, len(self.fingerprint), 4)).upper()

    def sign(self, message: bytes) -> bytes:
        return self.private_key.sign(message)


def load_or_create_identity(store: SecretStore, lock_path: Path | None = None) -> DaemonIdentity:
    """Load the daemon's Ed25519 identity, generating and persisting it on first use (needs ``cryptography``)."""
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:  # pragma: no cover
        raise SecretStoreError("the `cryptography` package is required for the daemon identity") from exc

    def create() -> str:
        raw = Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        return base64.urlsafe_b64encode(raw).decode()

    encoded = get_or_create_secret(store, IDENTITY_KEY, create, lock_path)
    key = Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(encoded.encode()))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return DaemonIdentity(key, public, hashlib.sha256(public).hexdigest())

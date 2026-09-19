"""Access-token lifecycle: refresh before expiry and on 401 without ever double-spending a rotating refresh token.

Refresh tokens rotate: presenting a spent one revokes the whole family. So a refresh must be

* single-flight inside a process (``asyncio.Lock``), and
* exclusive across processes (an ``fcntl`` file lock; the daemon and the CLI share ``credentials.lock``), and
* preceded by a re-read of the stored credentials, because the other process may have just rotated them.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import weakref
from pathlib import Path
from typing import Any

import httpx

from ..credentials import CredentialStore, CredentialStoreError, access_is_fresh, new_bundle
from .errors import CloudError, CloudRejected, CloudUnauthorized, CloudUnavailable

try:  # POSIX only; FLOW targets macOS and Linux
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]


class ProcessLock:
    """Async-friendly exclusive advisory lock on a file (polls instead of blocking the event loop)."""

    def __init__(self, path: str | Path, timeout: float = 30.0) -> None:
        self.path, self.timeout = Path(path), timeout
        self._fd: int | None = None

    async def __aenter__(self) -> "ProcessLock":
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
                    self._fd = None
                    raise CloudUnavailable("timed out waiting for the credential lock held by another FLOW process") from None
                await asyncio.sleep(0.05)

    async def __aexit__(self, *exc: Any) -> None:
        if self._fd is not None and fcntl is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


class TokenManager:
    def __init__(self, credentials: CredentialStore, api_url: str, *, transport: httpx.AsyncBaseTransport | None = None,
                 lock_path: str | Path | None = None, timeout: float = 10.0, skew: float = 60.0) -> None:
        self.credentials, self.api_url = credentials, api_url.rstrip("/")
        self.transport, self.timeout, self.skew = transport, timeout, skew
        if lock_path is None:
            from ..config import config_dir
            lock_path = config_dir() / "credentials.lock"
        self.lock_path = Path(lock_path)
        self._locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()

    # ---- state ---------------------------------------------------------------------------------
    def _lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = self._locks.get(loop)
        if lock is None:
            lock = self._locks[loop] = asyncio.Lock()
        return lock

    def load(self) -> dict[str, Any]:
        bundle = self.credentials.load_bundle()
        if not bundle or not bundle.get("access_token"):
            raise CloudUnauthorized("Not signed in. Run flow login.")
        bound = bundle.get("api_url")
        if bound and bound.rstrip("/") != self.api_url:  # never present a token to a host it was not issued by
            raise CloudUnauthorized(f"Stored credentials are for {bound}, not {self.api_url}. Run flow login.")
        return bundle

    def has_credentials(self) -> bool:
        try:
            self.load()
            return True
        except CloudUnauthorized:
            return False

    def fingerprint(self) -> str | None:
        """Changes whenever credentials are replaced (login/refresh); lets a paused worker notice a new login."""
        bundle = self.credentials.load_bundle()
        if not bundle:
            return None
        raw = f"{bundle.get('access_token')}|{bundle.get('refresh_token')}|{bundle.get('refresh_invalid')}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ---- tokens --------------------------------------------------------------------------------
    async def access_token(self) -> str:
        bundle = self.load()
        if bundle.get("refresh_invalid"):
            raise CloudUnauthorized()
        if access_is_fresh(bundle, self.skew):
            return bundle["access_token"]
        return await self.refresh()

    async def refresh(self, stale: str | None = None) -> str:
        """Return a valid access token, refreshing at most once no matter how many callers ask concurrently.

        ``stale`` is the token a caller just saw rejected (401); if storage already holds a different one,
        somebody else refreshed and we simply use theirs.
        """
        async with self._lock():
            async with ProcessLock(self.lock_path):
                bundle = self.load()  # re-read under the lock
                current = bundle["access_token"]
                if stale is not None and current != stale and access_is_fresh(bundle, 5.0):
                    return current
                if stale is None and access_is_fresh(bundle, self.skew):
                    return current
                if bundle.get("refresh_invalid") or not bundle.get("refresh_token"):
                    raise CloudUnauthorized()
                return await self._exchange(bundle)

    async def _exchange(self, bundle: dict[str, Any]) -> str:
        device_id = bundle.get("device_id") or ""
        try:
            async with httpx.AsyncClient(base_url=self.api_url, timeout=self.timeout, transport=self.transport) as http:
                response = await http.post("/v1/auth/refresh",
                                           json={"refresh_token": bundle["refresh_token"], "device_id": device_id})
        except httpx.HTTPError as exc:  # never retried here: the request may have been processed (token rotated)
            raise CloudUnavailable(f"could not reach FLOW to refresh credentials: {type(exc).__name__}") from exc
        if response.status_code in (400, 401, 403):
            # invalid_grant / revoked device / reuse detected: this credential is dead. Remember it so nobody
            # keeps presenting a spent refresh token, until `flow login` replaces the bundle.
            try:
                self.credentials.save_bundle({**bundle, "refresh_invalid": True})
            except CredentialStoreError:
                pass
            raise CloudUnauthorized()
        if response.status_code == 429 or response.status_code >= 500:
            raise CloudUnavailable(f"FLOW returned {response.status_code} while refreshing credentials")
        if response.status_code >= 400:
            raise CloudRejected(f"FLOW rejected the credential refresh ({response.status_code})", status=response.status_code)
        try:
            fresh = new_bundle(response.json(), device_id=device_id or bundle.get("device_id", ""), api_url=self.api_url)
        except (ValueError, KeyError) as exc:
            raise CloudError("FLOW returned an invalid refresh response") from exc
        fresh["user"] = fresh["user"] if fresh["user"].get("id") else bundle.get("user", fresh["user"])
        if not fresh.get("refresh_token"):
            fresh["refresh_token"] = bundle["refresh_token"]
        try:
            self.credentials.save_bundle(fresh)  # persisted before the lock is released and before first use
        except CredentialStoreError as exc:
            raise CloudError(f"refreshed credentials could not be saved: {exc}") from exc
        return fresh["access_token"]

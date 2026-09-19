"""Device authorization: PKCE request construction and the ``flow login`` orchestration.

The cloud (``services/flowcloud``) is the only authority: it issues the user code, waits for a signed-in web
user to approve, and exchanges the PKCE verifier for tokens. This module holds no server logic.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import secrets
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from .cloud.client import CloudClient
from .cloud.errors import CloudRejected, CloudUnavailable
from .credentials import CredentialStore, new_bundle, parse_time, save_account
from .device import metadata as device_metadata


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


@dataclass(frozen=True, slots=True)
class CLIAuthRequest:
    state: str
    nonce: str
    verifier: str
    challenge: str
    device_id: str

    @classmethod
    def create(cls, device_id: str) -> "CLIAuthRequest":
        verifier = _b64(secrets.token_bytes(32))
        return cls(secrets.token_urlsafe(24), secrets.token_urlsafe(24), verifier,
                   _b64(hashlib.sha256(verifier.encode()).digest()), device_id)

    def authorization_url(self, web_endpoint: str) -> str:
        return web_endpoint.rstrip("/") + "/cli/auth?" + urlencode({
            "state": self.state, "nonce": self.nonce, "code_challenge": self.challenge,
            "code_challenge_method": "S256", "device_id": self.device_id})


def local_token() -> str:
    return "local_" + secrets.token_urlsafe(24)


# ---- real device authorization (RFC 8628 style, PKCE + state + nonce) ---------------------------



class LoginError(Exception):
    """A user-facing reason the login did not complete."""


async def device_login(client: CloudClient, credentials: CredentialStore, config_dir: Path, *,
                       open_browser: bool = True, echo: Callable[[str], None] = print,
                       opener: Callable[[str], Any] = webbrowser.open, sleep=asyncio.sleep,
                       poll_interval: float | None = None, timeout: float | None = None) -> dict[str, Any]:
    """Run the browser-approved login and store the resulting credentials. Returns the stored bundle.

    ``poll_interval``/``timeout`` override what the cloud advertises (tests use tiny values). Nothing is stored
    unless the token response echoes both our ``state`` and ``nonce``.
    """
    device = device_metadata(config_dir)
    request = CLIAuthRequest.create(device["device_id"])
    try:
        started = await client.start_device_auth(device, request.challenge, request.state, request.nonce)
    except CloudUnavailable as exc:
        raise LoginError(f"Could not reach FLOW at {client.endpoint}: {exc}") from exc
    except CloudRejected as exc:
        raise LoginError(f"FLOW refused the login request: {exc}") from exc
    url, code = started["authorization_url"], started["user_code"]
    echo(f"\nOpen this URL to authorize this device:\n\n  {url}\n\nConfirmation code: {code}\n"
         "Check that the code shown in your browser matches before approving.")
    if open_browser:
        try:
            opener(url)
        except Exception:  # noqa: BLE001 - headless machine: the URL above is enough
            pass
    else:
        echo("(--no-browser: open the URL yourself)")
    echo("Waiting for approval...")
    interval = float(poll_interval if poll_interval is not None else started.get("interval", 2))
    expires = parse_time(started.get("expires_at"))
    budget = timeout if timeout is not None else (
        max(1.0, (expires - datetime.now(timezone.utc)).total_seconds()) if expires else 600.0)
    waited = 0.0
    while True:
        await sleep(interval)
        waited += interval
        try:
            token = await client.poll_device_token(started["auth_request_id"], device["device_id"], request.verifier)
            break
        except CloudRejected as exc:
            if exc.code == "authorization_pending":
                pass
            elif exc.code == "slow_down":
                interval += 5.0 if poll_interval is None else interval
            elif exc.code == "access_denied":
                raise LoginError("Authorization was denied in the browser.") from exc
            elif exc.code == "expired_token":
                raise LoginError("The login request expired. Run flow login again.") from exc
            else:
                raise LoginError(f"Login failed ({exc.code or exc.status}): {exc}") from exc
        except CloudUnavailable:
            pass  # transient: keep polling until the request expires
        if waited >= budget:
            raise LoginError("Timed out waiting for browser approval. Run flow login again.")
    if not (secrets.compare_digest(str(token.get("state", "")), request.state)
            and secrets.compare_digest(str(token.get("nonce", "")), request.nonce)):
        raise LoginError("The authorization response did not match this request (state/nonce). Nothing was stored.")
    device_id = (token.get("device") or {}).get("id") or device["device_id"]
    bundle = new_bundle(token, device_id=device_id, api_url=client.endpoint)
    credentials.save_bundle(bundle)
    save_account(config_dir, {
        "email": bundle["user"].get("email"), "user_id": bundle["user"].get("id"),
        "device_name": (token.get("device") or {}).get("name") or device["name"], "device_id": device_id,
        "api_url": client.endpoint, "logged_in_at": datetime.now(timezone.utc).isoformat()})
    return bundle

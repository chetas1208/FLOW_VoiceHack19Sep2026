"""PKCE and one-time CLI authorization helpers."""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import urlencode


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def create_verifier() -> str:
    return _b64(secrets.token_bytes(32))


def challenge_for(verifier: str) -> str:
    return _b64(hashlib.sha256(verifier.encode("ascii")).digest())


def valid_verifier(verifier: str, challenge: str) -> bool:
    return secrets.compare_digest(challenge_for(verifier), challenge)


def authorization_url(base_url: str, request_id: str, state: str, *,
                     redirect_uri: str = "http://127.0.0.1:8765/callback",
                     client_id: str = "flow-cli") -> str:
    query = urlencode({"request": request_id, "state": state, "client_id": client_id,
                       "redirect_uri": redirect_uri})
    return f"{base_url.rstrip('/')}/cli/authorize?{query}"

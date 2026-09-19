"""Local-development auth protocol and PKCE request construction."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode


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

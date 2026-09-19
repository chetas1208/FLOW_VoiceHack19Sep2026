"""Small PKCE helper used by the local CLI login flow.

The verifier is kept in memory by the caller.  Only the derived challenge is
safe to place in an authorization URL.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class CLIAuthRequest:
    state: str
    verifier: str
    challenge: str

    @classmethod
    def create(cls, state: str | None = None) -> "CLIAuthRequest":
        verifier = _b64(secrets.token_bytes(32))
        return cls(state or secrets.token_urlsafe(24), verifier,
                   _b64(hashlib.sha256(verifier.encode("ascii")).digest()))

    def authorization_url(self, base_url: str, *, redirect_uri: str = "http://127.0.0.1:8765/callback",
                          client_id: str = "flow-cli", scope: str = "openid profile") -> str:
        params = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
                  "scope": scope, "state": self.state, "code_challenge": self.challenge,
                  "code_challenge_method": "S256"}
        return f"{base_url.rstrip('/')}/authorize?{urlencode(params)}"

"""Token primitives: hashed opaque refresh tokens, signed short-lived access tokens, PKCE."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt

from .settings import Settings

REFRESH_PREFIX = "flowr_"
_VERIFIER = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class TokenError(Exception):
    pass


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def new_refresh_token() -> str:
    return REFRESH_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Refresh tokens carry 256 bits of entropy, so an unsalted SHA-256 is sufficient at rest."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_user_code() -> str:
    raw = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def verify_pkce(verifier: str, challenge: str) -> bool:
    if not _VERIFIER.match(verifier or ""):
        return False
    return hmac.compare_digest(pkce_challenge(verifier), challenge)


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: str
    device_id: str
    jti: str
    expires_at: int


class AccessTokenService:
    ALGORITHM = "HS256"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def issue(self, user_id: str, device_id: str, now: float | None = None) -> tuple[str, int]:
        issued = int(now if now is not None else time.time())
        expires = issued + self.settings.access_ttl_seconds
        claims = {"iss": self.settings.jwt_issuer, "aud": self.settings.jwt_audience, "sub": user_id,
                  "did": device_id, "typ": "access", "iat": issued, "nbf": issued, "exp": expires, "jti": uuid.uuid4().hex}
        kid = self.settings.active_kid
        token = jwt.encode(claims, self.settings.jwt_keys[kid], algorithm=self.ALGORITHM, headers={"kid": kid})
        return token, expires

    def verify(self, token: str) -> AccessClaims:
        try:
            header = jwt.get_unverified_header(token)
            secret = self.settings.jwt_keys.get(header.get("kid", ""))
            if secret is None or header.get("alg") != self.ALGORITHM:
                raise TokenError("unknown signing key")
            claims: dict[str, Any] = jwt.decode(
                token, secret, algorithms=[self.ALGORITHM], audience=self.settings.jwt_audience,
                issuer=self.settings.jwt_issuer, leeway=5,
                options={"require": ["exp", "iat", "sub", "aud", "iss", "jti"]})
        except jwt.PyJWTError as exc:
            raise TokenError("invalid access token") from exc
        if claims.get("typ") != "access" or not claims.get("did"):
            raise TokenError("not a device access token")
        return AccessClaims(claims["sub"], claims["did"], claims["jti"], int(claims["exp"]))

    def peek_issuer(self, token: str) -> str | None:
        try:
            return jwt.decode(token, options={"verify_signature": False}).get("iss")
        except jwt.PyJWTError:
            return None

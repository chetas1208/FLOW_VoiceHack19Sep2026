"""Web-user identity verification. Remote mode trusts only the configured OIDC provider."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import jwt

from .settings import Settings

LOCAL_ISSUER = "flow-local-dev"


class IdentityError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class WebIdentity:
    issuer: str
    subject: str
    email: str
    name: str | None
    expires_at: int


class IdentityVerifier(Protocol):
    issuer: str
    def verify(self, token: str) -> WebIdentity: ...


class LocalIdentityVerifier:
    """Development only; constructed exclusively when FLOW_AUTH_MODE=local outside production."""

    issuer = LOCAL_ISSUER

    def __init__(self, settings: Settings) -> None:
        if settings.is_production or settings.auth_mode != "local":
            raise IdentityError("local identity is disabled for this configuration")
        self.settings = settings

    def issue(self, email: str, ttl: int = 3600) -> str:
        now = int(time.time())
        claims = {"iss": LOCAL_ISSUER, "aud": "flow-web", "sub": email.lower(), "email": email.lower(),
                  "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
        kid = self.settings.active_kid
        return jwt.encode(claims, self.settings.jwt_keys[kid], algorithm="HS256", headers={"kid": kid})

    def verify(self, token: str) -> WebIdentity:
        try:
            kid = jwt.get_unverified_header(token).get("kid", "")
            secret = self.settings.jwt_keys.get(kid)
            if not secret:
                raise IdentityError("unknown key")
            claims = jwt.decode(token, secret, algorithms=["HS256"], audience="flow-web", issuer=LOCAL_ISSUER,
                                leeway=5, options={"require": ["exp", "sub", "email"]})
        except jwt.PyJWTError as exc:
            raise IdentityError("invalid web token") from exc
        return WebIdentity(LOCAL_ISSUER, claims["sub"], claims["email"], None, int(claims["exp"]))


class OIDCIdentityVerifier:
    """Verifies IdP-issued JWTs (Auth0, Clerk, Cognito, Supabase, ...) against the provider's JWKS."""

    ALGORITHMS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]

    def __init__(self, settings: Settings, key_resolver: Callable[[str], Any] | None = None) -> None:
        if not (settings.oidc_issuer and settings.oidc_audience):
            raise IdentityError("OIDC issuer and audience are required")
        self.issuer, self.audience = settings.oidc_issuer, settings.oidc_audience
        jwks_url = settings.oidc_jwks_url or self.issuer.rstrip("/") + "/.well-known/jwks.json"
        self._client = None if key_resolver else jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=5)
        self._resolver = key_resolver or (lambda token: self._client.get_signing_key_from_jwt(token).key)

    def verify(self, token: str) -> WebIdentity:
        try:
            key = self._resolver(token)
            claims = jwt.decode(token, key, algorithms=self.ALGORITHMS, audience=self.audience, issuer=self.issuer,
                                leeway=10, options={"require": ["exp", "sub", "iss", "aud"]})
        except (jwt.PyJWTError, OSError) as exc:
            raise IdentityError("invalid identity token") from exc
        email = claims.get("email")
        if not isinstance(email, str) or "@" not in email or claims.get("email_verified") is False:
            raise IdentityError("identity token has no verified email")
        return WebIdentity(self.issuer, str(claims["sub"]), email.lower(), claims.get("name"), int(claims["exp"]))

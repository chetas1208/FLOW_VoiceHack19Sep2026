"""Environment-driven cloud settings with fail-closed production validation."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field, replace

from ..flow.profiles import DEFAULT_PROFILE, PROFILES

PRODUCTION_ENVS = {"production", "staging"}
MIN_SECRET_BYTES = 32


class ConfigError(RuntimeError):
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _keys(raw: str | None) -> dict[str, str]:
    """`kid1:secret1,kid2:secret2`; the first entry signs, all entries verify."""
    keys: dict[str, str] = {}
    for item in (raw or "").split(","):
        if item.strip():
            kid, _, secret = item.strip().partition(":")
            if not kid or not secret:
                raise ConfigError("FLOW_JWT_KEYS entries must look like kid:secret")
            keys[kid] = secret
    return keys


@dataclass(frozen=True, slots=True)
class Settings:
    env: str = "production"
    auth_mode: str = "remote"
    database_url: str = ""
    redis_url: str | None = None
    jwt_keys: dict[str, str] = field(default_factory=dict)
    jwt_issuer: str = "flow-cloud"
    jwt_audience: str = "flow-api"
    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 30 * 24 * 3600
    auth_request_ttl_seconds: int = 600
    poll_interval_seconds: int = 2
    api_url: str = "https://api.flow.ai"
    web_url: str = "https://app.flow.ai"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    allowed_origins: tuple[str, ...] = ()
    trust_proxy: bool = False
    max_body_bytes: int = 65_536
    max_batch_body_bytes: int = 1_048_576
    max_batch_items: int = 100
    rate_limit_multiplier: float = 1.0
    metrics_token: str | None = None
    log_level: str = "INFO"
    ephemeral_secret: bool = False

    @property
    def is_production(self) -> bool:
        return self.env in PRODUCTION_ENVS

    @property
    def active_kid(self) -> str:
        return next(iter(self.jwt_keys))

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.getenv("FLOW_ENV", "production").strip().lower()
        auth_mode = os.getenv("FLOW_AUTH_MODE", "remote").strip().lower()
        keys = _keys(os.getenv("FLOW_JWT_KEYS"))
        single = os.getenv("FLOW_JWT_SECRET")
        if single and not keys:
            keys = {"k1": single}
        ephemeral = False
        if not keys and env not in PRODUCTION_ENVS:
            keys, ephemeral = {"dev": secrets.token_urlsafe(48)}, True
        profile = PROFILES.get(env, PROFILES[DEFAULT_PROFILE])
        settings = cls(
            env=env, auth_mode=auth_mode,
            database_url=os.getenv("DATABASE_URL", ""), redis_url=os.getenv("REDIS_URL") or None,
            jwt_keys=keys, jwt_issuer=os.getenv("FLOW_JWT_ISSUER", "flow-cloud"),
            jwt_audience=os.getenv("FLOW_JWT_AUDIENCE", "flow-api"),
            access_ttl_seconds=_int("FLOW_ACCESS_TTL_SECONDS", 900),
            refresh_ttl_seconds=_int("FLOW_REFRESH_TTL_SECONDS", 30 * 24 * 3600),
            auth_request_ttl_seconds=_int("FLOW_AUTH_REQUEST_TTL_SECONDS", 600),
            api_url=os.getenv("FLOW_API_URL", profile.api_url), web_url=os.getenv("FLOW_WEB_URL", profile.web_url),
            oidc_issuer=os.getenv("FLOW_OIDC_ISSUER") or None, oidc_audience=os.getenv("FLOW_OIDC_AUDIENCE") or None,
            oidc_jwks_url=os.getenv("FLOW_OIDC_JWKS_URL") or None,
            allowed_origins=tuple(item.strip() for item in os.getenv("FLOW_ALLOWED_ORIGINS", "").split(",") if item.strip()),
            trust_proxy=_bool("FLOW_TRUST_PROXY"), max_body_bytes=_int("FLOW_MAX_BODY_BYTES", 65_536),
            max_batch_body_bytes=_int("FLOW_MAX_BATCH_BODY_BYTES", 1_048_576),
            metrics_token=os.getenv("FLOW_METRICS_TOKEN") or None,
            log_level=os.getenv("FLOW_LOG_LEVEL", "INFO").upper(), ephemeral_secret=ephemeral)
        if not settings.database_url:
            settings = replace(settings, database_url=_default_database_url(env))
        return settings

    def validate(self) -> "Settings":
        if self.auth_mode not in {"local", "remote"}:
            raise ConfigError("FLOW_AUTH_MODE must be local or remote")
        if self.auth_mode == "local" and self.is_production:
            raise ConfigError("FLOW_AUTH_MODE=local is forbidden when FLOW_ENV is production or staging")
        if self.auth_mode == "remote" and not (self.oidc_issuer and self.oidc_audience):
            raise ConfigError("FLOW_AUTH_MODE=remote requires FLOW_OIDC_ISSUER and FLOW_OIDC_AUDIENCE")
        if not self.jwt_keys:
            raise ConfigError("FLOW_JWT_SECRET or FLOW_JWT_KEYS is required")
        if self.is_production:
            if any(len(secret.encode()) < MIN_SECRET_BYTES for secret in self.jwt_keys.values()):
                raise ConfigError(f"JWT signing secrets must be at least {MIN_SECRET_BYTES} bytes")
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ConfigError("production requires a PostgreSQL DATABASE_URL")
            if not self.redis_url:
                raise ConfigError("production requires REDIS_URL for rate limiting and realtime fanout")
            if not self.web_url.startswith("https://") or not self.api_url.startswith("https://"):
                raise ConfigError("production FLOW_API_URL and FLOW_WEB_URL must use https")
        return self


def _default_database_url(env: str) -> str:
    return "" if env in PRODUCTION_ENVS else "sqlite:///./.local-runs/flow-cloud.sqlite3"

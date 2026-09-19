"""Named endpoint profiles. Endpoints are never hard-coded outside this table."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    api_url: str
    web_url: str
    auth_mode: str


PROFILES = {
    "local": Profile("local", "http://127.0.0.1:8080", "http://127.0.0.1:3000", "local"),
    "development": Profile("development", "http://127.0.0.1:8080", "http://127.0.0.1:3000", "local"),
    "staging": Profile("staging", "https://api.staging.flow.ai", "https://app.staging.flow.ai", "remote"),
    "production": Profile("production", "https://api.flow.ai", "https://app.flow.ai", "remote"),
}
DEFAULT_PROFILE = "production"
AUTH_MODES = ("local", "remote")
_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def active_profile() -> Profile:
    name = os.getenv("FLOW_PROFILE", DEFAULT_PROFILE).strip().lower()
    if name not in PROFILES:
        raise ValueError(f"unknown FLOW_PROFILE {name!r}; expected one of {', '.join(PROFILES)}")
    return PROFILES[name]


def resolve_auth_mode(profile: Profile | None = None) -> str:
    """``FLOW_AUTH_MODE`` (local|remote), defaulting from the profile. Local auth is never allowed in production."""
    profile = profile or active_profile()
    mode = os.getenv("FLOW_AUTH_MODE", profile.auth_mode).strip().lower()
    if mode not in AUTH_MODES:
        raise ValueError(f"FLOW_AUTH_MODE must be one of {', '.join(AUTH_MODES)}")
    if mode == "local" and profile.name == "production":
        raise ValueError("FLOW_AUTH_MODE=local is not permitted with FLOW_PROFILE=production")
    return mode


def api_url(profile: Profile | None = None) -> str:
    return (os.getenv("FLOW_API_URL") or (profile or active_profile()).api_url).strip().rstrip("/")


def web_url(profile: Profile | None = None) -> str:
    return (os.getenv("FLOW_WEB_URL") or (profile or active_profile()).web_url).strip().rstrip("/")


def require_secure_url(url: str) -> str:
    """Bearer tokens only travel over TLS, except to a loopback development server."""
    parsed = urlparse(url)
    if parsed.scheme == "https" and parsed.hostname:
        return url
    if parsed.scheme == "http" and parsed.hostname in _LOOPBACK:
        return url
    raise ValueError(f"refusing to use {url!r}: FLOW endpoints must be https:// (http:// only for localhost)")

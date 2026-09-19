"""Typed cloud errors. Callers branch on the class, never on message text."""

from __future__ import annotations

UNAUTHORIZED_HELP = "Device authorization expired or revoked. Run flow login."


class CloudError(RuntimeError):
    """Base class (kept importable from ``services.flow.cloud`` for older callers)."""

    def __init__(self, message: str = "FLOW cloud request failed", *, status: int | None = None,
                 code: str | None = None, request_id: str | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.request_id = status, code, request_id


class CloudUnavailable(CloudError):
    """Transient: network failure, timeout, 5xx, 408/425/429. Safe to retry later; the data is fine."""

    def __init__(self, message: str = "FLOW cloud is unreachable", *, retry_after: float | None = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class CloudUnauthorized(CloudError):
    """The device has no valid credentials (never signed in, expired refresh token, revoked device)."""

    def __init__(self, message: str = UNAUTHORIZED_HELP, **kwargs) -> None:
        super().__init__(message, **kwargs)


class CloudRejected(CloudError):
    """Permanent 4xx: the cloud understood the request and will never accept it as sent."""

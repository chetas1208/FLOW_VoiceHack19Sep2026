"""Typed observer failures. All subclass RuntimeError so existing handlers keep working."""

from __future__ import annotations


class ObserverError(RuntimeError):
    code = "observer_error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint

    def to_dict(self) -> dict[str, str | None]:
        return {"code": self.code, "message": str(self), "hint": self.hint}


class PermissionDenied(ObserverError):
    code = "permission_denied"


class HelperMissing(ObserverError):
    code = "helper_missing"


class HelperUnsupported(ObserverError):
    """The helper exists but this macOS version cannot do the requested operation."""

    code = "helper_unsupported"


class CaptureTimeout(ObserverError):
    code = "timeout"


class CaptureFailed(ObserverError):
    code = "capture_failed"


class DisplayNotFound(CaptureFailed):
    code = "display_not_found"


class ObserverNotRunning(ObserverError):
    code = "not_running"

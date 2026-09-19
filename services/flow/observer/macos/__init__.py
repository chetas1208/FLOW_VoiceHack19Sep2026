"""macOS observer adapter: Swift ScreenCaptureKit helper with a pure-CLI fallback."""

from .errors import (CaptureFailed, CaptureTimeout, DisplayNotFound, HelperMissing, HelperUnsupported,
                     ObserverError, ObserverNotRunning, PermissionDenied)
from .permissions import PermissionStatus, screen_recording_status
from .screen_capture import MacOSObserver

__all__ = ["CaptureFailed", "CaptureTimeout", "DisplayNotFound", "HelperMissing", "HelperUnsupported",
           "MacOSObserver", "ObserverError", "ObserverNotRunning", "PermissionDenied", "PermissionStatus",
           "screen_recording_status"]

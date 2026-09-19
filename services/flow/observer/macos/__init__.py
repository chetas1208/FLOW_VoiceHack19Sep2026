"""macOS observer adapter; native ScreenCaptureKit bridge is kept replaceable."""

from .screen_capture import MacOSObserver

__all__ = ["MacOSObserver"]

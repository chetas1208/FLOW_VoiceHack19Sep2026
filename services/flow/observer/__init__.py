"""Platform-neutral observation interfaces and deterministic local adapters."""

from .base import DesktopObserver, MockDesktopObserver, ObserverContext
from .frame import CapturedFrame, CaptureReason
from .sampler import AdaptiveSampler, SamplerConfig
from .pipeline import FrameChangeDetector, ObserverPipeline

__all__ = ["AdaptiveSampler", "CapturedFrame", "CaptureReason", "DesktopObserver",
           "FrameChangeDetector", "MockDesktopObserver", "ObserverContext",
           "ObserverPipeline", "SamplerConfig"]

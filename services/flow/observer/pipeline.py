"""Capture-to-Observation coordinator with privacy and bounded failure handling."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..activity import ActivityAnalyzer
from ..models import ActivityCategory, Observation
from ..privacy.policy import PrivacyPolicy
from ..session_manager import SessionManager, _id
from ..efficiency import EfficiencyEngine
from .base import DesktopObserver
from .frame import CapturedFrame, CaptureReason


class FrameChangeDetector:
    def __init__(self) -> None:
        self._last: str | None = None

    def changed(self, frame: CapturedFrame) -> bool:
        current = frame.fingerprint
        if current is None or current != self._last:
            self._last = current
            return True
        return False


class ObserverPipeline:
    def __init__(self, session_id: str, goal: str, observer: DesktopObserver,
                 analyzer: "ActivityAnalyzer", manager: SessionManager,
                 privacy: PrivacyPolicy | None = None, efficiency: EfficiencyEngine | None = None) -> None:
        self.session_id, self.goal = session_id, goal
        self.observer, self.analyzer, self.manager = observer, analyzer, manager
        self.privacy = privacy or PrivacyPolicy()
        self.efficiency = efficiency
        self.change_detector = FrameChangeDetector()

    async def observe_once(self, reason: CaptureReason = CaptureReason.PERIODIC) -> Observation | None:
        context = await self.observer.active_context()
        if self.privacy.is_excluded(context.application):
            return self._metadata_observation(context.application, "excluded_context")
        frame = await self.observer.snapshot(reason)
        if frame is not None and (self.privacy.is_excluded(frame.application)
                                  or self.privacy.is_excluded(frame.bundle_id)):
            # Focus moved to an excluded app between the context check and the capture.
            frame.discard_pixels()
            return self._metadata_observation(frame.application, "excluded_context")
        if frame is None or not self.change_detector.changed(frame):
            if frame is not None:
                frame.discard_pixels()
            return None
        history = [item.to_dict() for item in self.manager.observations(self.session_id)[-10:]]
        try:
            from ..activity import AnalysisResult, validate_analysis
            result = await self.analyzer.analyze(self.goal, frame, {
                "application": context.application, "bundle_id": context.bundle_id,
                "window_title": context.window_title,
            }, history)
            if self.efficiency is not None:
                from ..vision.schema import VisionObservation
                if isinstance(result, VisionObservation):
                    semantic = self.efficiency.update(result)
                    semantic.id, semantic.session_id = _id("obs"), self.session_id
                    return self.manager.add_observation(self.session_id, semantic)
            if not isinstance(result, AnalysisResult):
                result = validate_analysis(result)
        except (ValueError, RuntimeError):
            result = AnalysisResult("Semantic analysis unavailable", ActivityCategory.UNKNOWN, None, None, 0.0)
        finally:
            frame.discard_pixels()
        fields = result.to_observation_fields()
        return self.manager.add_observation(self.session_id, Observation(
            _id("obs"), self.session_id, frame.timestamp, "observer",
            context.application, context.window_title, fields["activity_summary"],
            ActivityCategory(fields["category"]), fields["goal_alignment"],
            fields["progress_signal"], fields["confidence"], fields["metadata"]))

    def _metadata_observation(self, application: str | None, reason: str) -> Observation:
        # Excluded contexts are metadata-only: the window title is private and is never stored.
        return self.manager.add_observation(self.session_id, Observation(
            _id("obs"), self.session_id, datetime.now(timezone.utc), "observer",
            application, None, reason, ActivityCategory.UNKNOWN, None, None, None,
            {"excluded": True, "reason": reason}))

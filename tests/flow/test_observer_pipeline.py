import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

from services.flow.activity import AnalysisResult
from services.flow.models import ActivityCategory
from services.flow.observer import CapturedFrame, MockDesktopObserver, ObserverPipeline
from services.flow.observer.idle import IdleDetector, IdleState
from services.flow.privacy import PrivacyPolicy
from services.flow.session_manager import SessionManager
from services.flow.store import FlowStore
from services.flow.voice.policy import InterventionPolicy, InterventionPolicyConfig


class Analyzer:
    async def analyze(self, goal, frame, context, history):
        return AnalysisResult("Editing authentication tests", ActivityCategory.CORE_TASK, .9, .7, .9)


def test_pipeline_generates_semantic_observation_and_discards_pixels():
    async def run():
        with tempfile.TemporaryDirectory() as path:
            manager = SessionManager(FlowStore(path)); session = manager.start_session("Fix auth")
            frame = CapturedFrame(datetime.now(timezone.utc), application="Editor", image_bytes=b"pixels")
            observer = MockDesktopObserver([frame]); await observer.start()
            item = await ObserverPipeline(session.id, session.goal, observer, Analyzer(), manager).observe_once()
            assert item.category == ActivityCategory.CORE_TASK
            assert frame.image_bytes is None
    asyncio.run(run())


def test_excluded_application_never_requests_a_frame():
    async def run():
        with tempfile.TemporaryDirectory() as path:
            manager = SessionManager(FlowStore(path)); session = manager.start_session("test")
            frame = CapturedFrame(datetime.now(timezone.utc), application="Bank App", image_bytes=b"secret")
            observer = MockDesktopObserver([frame]); await observer.start()
            item = await ObserverPipeline(session.id, session.goal, observer, Analyzer(), manager,
                                           PrivacyPolicy({"Bank App"})).observe_once()
            assert item.metadata["excluded"] is True and frame.image_bytes == b"secret"
    asyncio.run(run())


def test_intervention_policy_applies_confidence_and_cooldown():
    policy = InterventionPolicy(InterventionPolicyConfig(.8, 60, 600))
    assert not policy.should_intervene(drift_seconds=59, confidence=.99)
    assert policy.should_intervene(drift_seconds=61, confidence=.9)
    assert not policy.should_intervene(drift_seconds=1000, confidence=.99)


def test_idle_time_is_not_productivity_distraction():
    now = datetime.now(timezone.utc)
    detector = IdleDetector(idle_after=10, away_after=30)
    assert detector.state(now, now) == IdleState.ACTIVE
    assert detector.state(now, now + timedelta(seconds=15)) == IdleState.IDLE

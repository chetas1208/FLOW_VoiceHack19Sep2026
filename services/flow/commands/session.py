"""Legacy local session commands (start, stop, pause, resume), the local daemon toggle, and the replay tools.

Behaviour is intentionally unchanged from the pre-plug-in ``cli.py``; a later change replaces the local-only
start/stop with the daemon-backed versions in this file.
"""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from ..activity import AnalysisResult
from ..config import config_dir, local_api_endpoint
from ..daemon import pid_path, request
from ..efficiency import EfficiencyEngine
from ..models import SessionStatus
from ..observer import CapturedFrame, MockDesktopObserver
from ..observer.frame import CaptureReason
from ..runtime import SessionRuntime
from ..session_manager import InvalidTransition, SessionManager, SessionNotFound
from ..vision.schema import VisionActivityType, VisionObservation

NAMES = ["start", "stop", "pause", "resume", "daemon", "e2e", "efficiency"]


def add_parser(sub) -> None:
    start = sub.add_parser("start")
    start.add_argument("goal_arg", nargs="?")
    start.add_argument("--goal")
    for name in ("stop", "pause", "resume"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--session")
    daemon = sub.add_parser("daemon")
    daemon.add_argument("action", choices=["start", "stop", "status"])
    e2e = sub.add_parser("e2e")
    e2e.add_argument("--goal", default="Test FLOW authentication intelligence")
    efficiency = sub.add_parser("efficiency")
    efficiency.add_argument("action", choices=["test"])


def show_session(session, service: SessionManager) -> None:
    metrics = service.metrics(session.id).to_dict()

    def value(key):
        item = metrics[key]
        if item is None:
            return "unavailable"
        return f"{item:.0%}" if isinstance(item, float) and key != "session_score" else f"{item:.1f}"
    print(f"ID                 {session.id}\nGoal               {session.goal}\nStatus             {session.status.value}")
    print(f"Goal Alignment     {value('goal_alignment')}\nFocus Continuity   {value('focus_continuity')}\nContext Stability  {value('context_stability')}\nProgress           {value('progress')}\nSession Score      {value('session_score')}\nState              {metrics['drift_state']}")


def daemon_action(action: str) -> int:
    if action == "status":
        try:
            print(asyncio.run(request("status")))
            return 0
        except (FileNotFoundError, ConnectionError, OSError):
            print("FLOW daemon: stopped")
            return 1
    if action == "stop":
        try:
            pid = int(pid_path().read_text())
            os.kill(pid, 15)
            print("FLOW daemon stopped")
            return 0
        except (FileNotFoundError, ValueError, ProcessLookupError):
            print("FLOW daemon is not running")
            return 1
    if pid_path().exists():
        print("FLOW daemon is already running")
        return 0
    subprocess.Popen([sys.executable, "-m", "services.flow.daemon"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print("FLOW daemon started")
    return 0


def run(args) -> int:
    if args.command == "daemon":
        return daemon_action(args.action)
    if args.command == "efficiency":
        return _efficiency()
    if args.command == "e2e":
        return _portable_e2e(args.goal)
    service = SessionManager.from_environment()
    try:
        if args.command == "start":
            goal = args.goal or args.goal_arg
            if not goal:
                raise ValueError("start requires a goal")
            session = service.start_session(goal, metadata={"observer": "macos" if platform.system() == "Darwin" else "unavailable"})
            observer_state = "available" if platform.system() == "Darwin" else "not available on this host"
            print(f"FLOW\n\nSession started\n\nID        {session.id}\nGoal      {session.goal}\nStatus    active\n\nObserver\n{observer_state}\n\nDashboard\n{local_api_endpoint()}/flow/session/{session.id}")
        else:
            session_id = args.session
            if not session_id:
                active = service.list_sessions(SessionStatus.ACTIVE)
                if len(active) != 1:
                    raise ValueError("specify --session unless exactly one active local session exists")
                session_id = active[0].id
            if args.command == "stop":
                show_session(service.stop_session(session_id), service)
            elif args.command == "pause":
                show_session(service.pause_session(session_id), service)
            elif args.command == "resume":
                show_session(service.resume_session(session_id), service)
    except (ValueError, SessionNotFound, InvalidTransition) as exc:
        print(f"flow: {exc}", file=sys.stderr)
        return 2
    return 0


def _efficiency() -> int:
    engine = EfficiencyEngine("Fix JWT authentication tests")
    now = datetime.now(timezone.utc)
    sequence = [("Implementing JWT middleware", VisionActivityType.IMPLEMENTATION, .92, .8),
                ("Reading JWT expiration documentation", VisionActivityType.RESEARCH, .82, .3),
                ("Unrelated social feed", VisionActivityType.BROWSING, .05, 0.0)]
    for index, (activity, kind, relevance, progress) in enumerate(sequence):
        engine.update(VisionObservation(now + timedelta(minutes=index), "replay", None, activity, kind,
                                        relevance=relevance, progress_signal=progress, confidence=.9))
    report = engine.report()
    print(f"FLOW EFFICIENCY TEST\n\nSegments          {len(report['segments'])}\nAlignment         {report['alignment']:.0%}\nDrift             {report['drift_state']}\nRecommendation    {report['recommendation']}")
    return 0


def _portable_e2e(goal: str) -> int:
    """Exercise the complete runtime with sanitized replay frames, never real screen data."""
    from ..models import ActivityCategory

    class ReplayAnalyzer:
        async def analyze(self, goal, frame, context, history):
            if frame.application == "Social":
                return AnalysisResult("Unrelated social feed", ActivityCategory.DISTRACTION, .05, 0.0, .95)
            if frame.application == "Docs":
                return AnalysisResult("Reading JWT expiration documentation", ActivityCategory.SUPPORTING_TASK, .84, .3, .9)
            return AnalysisResult("Debugging authentication tests", ActivityCategory.CORE_TASK, .93, .8, .95)

    async def run_replay():
        manager = SessionManager()
        session = manager.start_session(goal)
        start = datetime.now(timezone.utc)
        frames = [CapturedFrame(start + timedelta(seconds=index * 60), application=app,
                                window_title="FLOW replay", image_bytes=f"frame-{index}".encode(),
                                reason=CaptureReason.PERIODIC) for index, app in enumerate(["Editor", "Docs", "Editor", "Social", "Social", "Editor"])]
        observer = MockDesktopObserver(frames)
        runtime = SessionRuntime(manager, session.id, observer, ReplayAnalyzer())
        await observer.start()
        for _ in frames:
            await runtime.run_once()
        await observer.stop()
        manager.stop_session(session.id)
        return runtime.report()
    report = asyncio.run(run_replay())
    metrics = report["metrics"]
    score = "unavailable" if metrics["session_score"] is None else f"{metrics['session_score']:.1f}"
    print(f"FLOW REPLAY E2E\n\nSession           {report['id']}\nObservations      {report['observation_count']}\nSegments          {len(report['task_segments'])}\nDrift state       {metrics['drift_state']}\nCoverage          {metrics['coverage']:.0%}\nSession score     {score}\nStatus            {report['status']}")
    return 0

"""Production-shaped FLOW command tree with local-first behavior."""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import subprocess
import sys
import webbrowser
import asyncio
from datetime import datetime, timedelta, timezone

from .auth import CLIAuthRequest, local_token
from .config import api_endpoint, config_dir, web_endpoint
from .credentials import default_credential_store
from .daemon import pid_path, request
from .device import metadata
from .models import SessionStatus
from .activity import AnalysisResult
from .observer import CapturedFrame, MockDesktopObserver
from .observer.base import create_observer
from .observer.frame import CaptureReason
from .privacy import PrivacyPolicy
from .runtime import SessionRuntime
from .session_manager import InvalidTransition, SessionManager, SessionNotFound

VERSION = "0.2.0"


def _show(session, service: SessionManager) -> None:
    metrics = service.metrics(session.id).to_dict()
    def value(key):
        item = metrics[key]
        if item is None:
            return "unavailable"
        return f"{item:.0%}" if isinstance(item, float) and key != "session_score" else f"{item:.1f}"
    print(f"ID                 {session.id}\nGoal               {session.goal}\nStatus             {session.status.value}")
    print(f"Goal Alignment     {value('goal_alignment')}\nFocus Continuity   {value('focus_continuity')}\nContext Stability  {value('context_stability')}\nProgress           {value('progress')}\nSession Score      {value('session_score')}\nState              {metrics['drift_state']}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flow", description="FLOW local work-session observer and coach")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login"); login.add_argument("--token")
    sub.add_parser("logout"); sub.add_parser("whoami")
    sub.add_parser("version")
    start = sub.add_parser("start"); start.add_argument("goal_arg", nargs="?"); start.add_argument("--goal")
    for name in ("status", "stop", "pause", "resume"):
        cmd = sub.add_parser(name); cmd.add_argument("--session")
    sub.add_parser("list", aliases=["sessions"])
    sub.add_parser("doctor")
    permissions = sub.add_parser("permissions"); permissions.add_argument("action", nargs="?", choices=["open"])
    config = sub.add_parser("config"); config.add_argument("action", choices=["exclude-app", "include-app", "mode"]); config.add_argument("value")
    daemon = sub.add_parser("daemon"); daemon.add_argument("action", choices=["start", "stop", "status"])
    voice = sub.add_parser("voice"); voice.add_argument("action", choices=["install", "status", "test"])
    observer = sub.add_parser("observer"); observer.add_argument("action", choices=["test"])
    analyze = sub.add_parser("analyze"); analyze.add_argument("action", choices=["test"]); analyze.add_argument("--goal", required=True)
    e2e = sub.add_parser("e2e"); e2e.add_argument("--goal", default="Test FLOW authentication intelligence")
    return parser


def _config_policy() -> PrivacyPolicy:
    return PrivacyPolicy.load(config_dir() / "privacy.json")


def _daemon_action(action: str) -> int:
    if action == "status":
        try:
            print(asyncio.run(request("status"))); return 0
        except (FileNotFoundError, ConnectionError, OSError):
            print("FLOW daemon: stopped"); return 1
    if action == "stop":
        try:
            pid = int(pid_path().read_text()); os.kill(pid, 15)
            print("FLOW daemon stopped"); return 0
        except (FileNotFoundError, ValueError, ProcessLookupError):
            print("FLOW daemon is not running"); return 1
    if pid_path().exists():
        print("FLOW daemon is already running"); return 0
    subprocess.Popen([sys.executable, "-m", "services.flow.daemon"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print("FLOW daemon started"); return 0


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    store = default_credential_store(config_dir())
    if args.command == "login":
        if args.token:
            store.save_token(args.token); print("Logged in using supplied development token."); return 0
        if os.getenv("FLOW_AUTH_MODE", "local") == "local":
            store.save_token(local_token()); print("Logged in to local development mode."); return 0
        auth = CLIAuthRequest.create(metadata(config_dir())["device_id"])
        url = auth.authorization_url(web_endpoint()); print(url); webbrowser.open(url)
        print("Complete authorization in your browser, then exchange the code through the configured backend.")
        return 0
    if args.command == "logout":
        store.delete_token(); print("Logged out."); return 0
    if args.command == "whoami":
        print("authenticated" if store.get_token() else "not authenticated"); return 0
    if args.command == "version":
        print(VERSION); return 0
    if args.command == "doctor":
        print(f"FLOW Doctor\n\nCLI             {VERSION}       ✓\nPython          {platform.python_version()}   {'✓' if sys.version_info >= (3, 11) else '✗'}")
        print(f"Platform        {platform.system()}\nAuthentication  {'connected ✓' if store.get_token() else 'not connected ✗'}")
        print(f"Observer        {'available' if platform.system() == 'Darwin' else 'unsupported on this host'}")
        print(f"Daemon          {'running ✓' if pid_path().exists() else 'stopped'}\nAPI             {api_endpoint()}")
        return 0 if sys.version_info >= (3, 11) else 1
    if args.command == "permissions":
        if platform.system() != "Darwin": print("Screen Recording   unavailable on this non-macOS host")
        else:
            print("FLOW Permissions\n\nScreen Recording   check required\nAccessibility      not required\nMicrophone         optional\nNotifications      optional")
            if args.action == "open": subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"], check=False)
        return 0
    if args.command == "config":
        policy = _config_policy()
        if args.action == "exclude-app": policy.add_exclusion(args.value)
        elif args.action == "include-app": policy.remove_exclusion(args.value)
        else:
            if args.value not in {"performance", "balanced", "battery"}: print("mode must be performance, balanced, or battery", file=sys.stderr); return 2
            config_dir().mkdir(parents=True, exist_ok=True); (config_dir() / "mode").write_text(args.value)
        if args.action != "mode": policy.save(config_dir() / "privacy.json")
        print("FLOW configuration updated"); return 0
    if args.command == "daemon": return _daemon_action(args.action)
    if args.command == "voice":
        try:
            import importlib.util
            installed = importlib.util.find_spec("kokoro") is not None
        except (ImportError, ModuleNotFoundError):
            installed = False
        if args.action == "install":
            print("Install optional voice support with: pip install 'flow-agent[voice]'")
        elif args.action == "status":
            print(f"Voice engine: Kokoro\nModel package: {'available' if installed else 'not installed'}\nVoice: af_heart")
        else:
            print("Voice test requires Kokoro installation." if not installed else "Kokoro is installed; audio playback is platform-configured.")
        return 0 if installed or args.action == "install" else 1
    if args.command == "observer":
        if platform.system() != "Darwin":
            print("FLOW observer test: NOT_CONFIGURED (ScreenCaptureKit requires macOS)")
            return 2
        async def observer_test():
            observer = create_observer(); await observer.start(); context = await observer.active_context(); await observer.stop(); return context
        try:
            context = asyncio.run(observer_test())
            print(f"FLOW OBSERVER TEST\n\nPermission        checked\nApplication       {context.application or 'unknown'}\nCapture           native bridge response required")
            return 0
        except Exception as exc:
            print(f"FLOW observer test: FAIL ({exc})", file=sys.stderr); return 1
    if args.command == "analyze":
        print("FLOW analyzer test requires a configured multimodal provider and a permitted macOS frame.")
        print(f"Goal              {args.goal}\nResult             NOT_CONFIGURED")
        return 2
    if args.command == "e2e":
        return _portable_e2e(args.goal)

    service = SessionManager()
    try:
        if args.command == "start":
            goal = args.goal or args.goal_arg
            if not goal: raise ValueError("start requires a goal")
            session = service.start_session(goal, metadata={"observer": "macos" if platform.system() == "Darwin" else "unavailable"})
            observer_state = "available" if platform.system() == "Darwin" else "not available on this host"
            print(f"FLOW\n\nSession started\n\nID        {session.id}\nGoal      {session.goal}\nStatus    active\n\nObserver\n{observer_state}\n\nDashboard\n{api_endpoint()}/flow/session/{session.id}")
        elif args.command in {"list", "sessions"}:
            for session in service.list_sessions(): print(f"{session.id}\t{session.status.value}\t{session.goal}")
        else:
            session_id = args.session
            if not session_id:
                active = service.list_sessions(SessionStatus.ACTIVE)
                if len(active) != 1: raise ValueError("specify --session unless exactly one active local session exists")
                session_id = active[0].id
            if args.command == "status": _show(service.get_session(session_id), service)
            elif args.command == "stop": _show(service.stop_session(session_id), service)
            elif args.command == "pause": _show(service.pause_session(session_id), service)
            elif args.command == "resume": _show(service.resume_session(session_id), service)
    except (ValueError, SessionNotFound, InvalidTransition) as exc:
        print(f"flow: {exc}", file=sys.stderr); return 2
    return 0


def _portable_e2e(goal: str) -> int:
    """Exercise the complete runtime with sanitized replay frames, never real screen data."""
    class ReplayAnalyzer:
        async def analyze(self, goal, frame, context, history):
            if frame.application == "Social":
                return AnalysisResult("Unrelated social feed", __import__("services.flow.models", fromlist=["ActivityCategory"]).ActivityCategory.DISTRACTION, .05, 0.0, .95)
            if frame.application == "Docs":
                return AnalysisResult("Reading JWT expiration documentation", __import__("services.flow.models", fromlist=["ActivityCategory"]).ActivityCategory.SUPPORTING_TASK, .84, .3, .9)
            return AnalysisResult("Debugging authentication tests", __import__("services.flow.models", fromlist=["ActivityCategory"]).ActivityCategory.CORE_TASK, .93, .8, .95)
    async def run():
        manager = SessionManager(); session = manager.start_session(goal)
        start = datetime.now(timezone.utc)
        frames = [CapturedFrame(start + timedelta(seconds=index * 60), application=app,
                                 window_title="FLOW replay", image_bytes=f"frame-{index}".encode(),
                                 reason=CaptureReason.PERIODIC) for index, app in enumerate(["Editor", "Docs", "Editor", "Social", "Social", "Editor"])]
        observer = MockDesktopObserver(frames); runtime = SessionRuntime(manager, session.id, observer, ReplayAnalyzer())
        await observer.start()
        for _ in frames: await runtime.run_once()
        await observer.stop(); manager.stop_session(session.id)
        return runtime.report()
    report = asyncio.run(run())
    metrics = report["metrics"]
    score = "unavailable" if metrics["session_score"] is None else f"{metrics['session_score']:.1f}"
    print(f"FLOW REPLAY E2E\n\nSession           {report['id']}\nObservations      {report['observation_count']}\nSegments          {len(report['task_segments'])}\nDrift state       {metrics['drift_state']}\nCoverage          {metrics['coverage']:.0%}\nSession score     {score}\nStatus            {report['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

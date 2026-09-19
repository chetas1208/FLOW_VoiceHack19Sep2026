"""CLI access to the deterministic evidence-based recommendation engine."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from ..config import config_dir, data_dir
from ..models import SessionStatus
from ..recommend.context import RecommendationContext
from ..recommend.engine import ActionRecommendationEngine
from ..remote_models import PermissionLevel, PermissionPolicy
from ..executor.base import TrustedInstruction
from ..session_manager import SessionManager

NAME = "recommend"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="show or explicitly execute the best evidence-based next action")
    parser.add_argument("--session")
    parser.add_argument("--do", action="store_true", help="delegate the recommendation when it is executable")


def _session(service: SessionManager, explicit: str | None):
    if explicit:
        return service.get_session(explicit)
    active = service.list_sessions(SessionStatus.ACTIVE)
    if len(active) != 1:
        raise ValueError("specify --session unless exactly one active session exists")
    return active[0]


def _recommendation(service: SessionManager, session_id: str):
    session = service.get_session(session_id)
    observations = service.observations(session_id)
    metrics = service.metrics(session_id)
    latest = observations[-1] if observations else None
    context = RecommendationContext(
        session_id=session.id, goal=session.goal, now=datetime.now(timezone.utc),
        current_task=latest.activity_summary if latest else None,
        observations=observations[-60:], progress=metrics.progress, alignment=metrics.goal_alignment,
        drift_state=metrics.drift_state.value, confidence=metrics.confidence,
        last_aligned_task=next((item.activity_summary for item in reversed(observations)
                                if item.goal_alignment is not None and item.goal_alignment >= .7), None),
        session_started_at=session.started_at)
    return ActionRecommendationEngine().recommend(context)


def run(args) -> int:
    service = SessionManager.from_environment()
    try:
        session = _session(service, args.session)
    except ValueError as exc:
        print(f"flow recommend: {exc}")
        return 2
    recommendation = _recommendation(service, session.id)
    if recommendation is None:
        print("FLOW RECOMMENDATION\n\nNo evidence-based next action is available.")
        return 0
    print(f"NEXT BEST ACTION\n\n{recommendation.title}\n\n{recommendation.description}")
    print(f"\nConfidence       {recommendation.confidence:.0%}")
    print(f"Reason           {recommendation.reason}")
    print("Evidence")
    for evidence in recommendation.evidence:
        print(f"- {evidence}")
    if not args.do:
        return 0
    if not recommendation.can_delegate or not recommendation.proposed_task:
        print("\nThis recommendation requires a human action and was not delegated.")
        return 2

    from ..device import device_id
    from ..executor.runner import TaskExecutor, TaskManager

    async def execute():
        executor = TaskExecutor(Path.cwd(), policy=PermissionPolicy.SAFE_AUTO, artifacts_dir=data_dir() / "tasks")
        manager = TaskManager(executor, session_id=session.id, user_id="local-user", device_id=device_id(config_dir()))
        task = await manager.submit(TrustedInstruction.from_recommendation(
            recommendation.proposed_task, recommendation.id, "local-user"),
            permission_level=PermissionLevel.SAFE_EXECUTE,
            recommendation_id=recommendation.id)
        return await manager.wait(task.id, timeout=executor.task_timeout)

    task = asyncio.run(execute())
    print(f"\nDelegated task  {task.id}\nStatus           {task.status.value}")
    if task.error:
        print(f"Error            {task.error}")
    return 0 if task.status.value == "completed" else 1

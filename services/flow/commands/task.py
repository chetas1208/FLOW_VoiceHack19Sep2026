"""Explicit CLI delegation through the sandboxed task executor."""

from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import config_dir, data_dir
from ..device import device_id
from ..executor.base import TrustedInstruction
from ..executor.runner import TaskExecutor, TaskManager
from ..models import SessionStatus
from ..remote_models import PermissionLevel, PermissionPolicy
from ..session_manager import SessionManager

NAME = "task"


def add_parser(subparsers) -> None:
    parser = subparsers.add_parser(NAME, help="explicitly delegate a bounded local task")
    parser.add_argument("action", choices=["add"])
    parser.add_argument("instruction", nargs="?")
    parser.add_argument("--session")


def _session(service: SessionManager, explicit: str | None):
    if explicit:
        return service.get_session(explicit)
    active = service.list_sessions(SessionStatus.ACTIVE)
    if len(active) != 1:
        raise ValueError("specify --session unless exactly one active session exists")
    return active[0]


def run(args) -> int:
    if not args.instruction or not args.instruction.strip():
        print("flow task: task add requires an instruction")
        return 2
    try:
        session = _session(SessionManager.from_environment(), args.session)
    except ValueError as exc:
        print(f"flow task: {exc}")
        return 2

    async def execute():
        executor = TaskExecutor(Path.cwd(), policy=PermissionPolicy.SAFE_AUTO, artifacts_dir=data_dir() / "tasks")
        manager = TaskManager(executor, session_id=session.id, user_id="local-user", device_id=device_id(config_dir()))
        task = await manager.submit(TrustedInstruction(args.instruction, "cli", "user:local"),
                                    permission_level=PermissionLevel.SAFE_EXECUTE)
        return await manager.wait(task.id, timeout=executor.task_timeout)

    task = asyncio.run(execute())
    print(f"Task {task.id}\nStatus  {task.status.value}")
    if task.result:
        print(task.result.get("summary") or "")
    if task.error:
        print(f"Error   {task.error}")
    return 0 if task.status.value == "completed" else 1

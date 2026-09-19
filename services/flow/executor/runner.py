"""TaskExecutor (runs one task safely) and TaskManager (queue, cancellation, persistence hooks)."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..config import data_dir
from ..models import utc_now
from ..remote_models import (
    ActionApproval,
    ApprovalStatus,
    DelegatedTask,
    PermissionLevel,
    PermissionPolicy,
    TaskStatus,
    new_id,
)
from .base import (
    ExecLimits,
    Tool,
    ToolContext,
    ToolError,
    ToolResult,
    TrustedInstruction,
    UntrustedInstructionError,
)
from .planner import PlanError, plan_instruction
from .policy import Decision, PermissionEngine
from .results import ActivityInterval, StepRecord, TaskLog, build_result, sample_lines
from .sandbox import Sandbox, redact
from .tools import default_tools

log = logging.getLogger("flow.executor")

Emit = Callable[[str, dict[str, Any]], Awaitable[None] | None]
RequestApproval = Callable[[ActionApproval], Awaitable[Any]]
TERMINAL = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
_PLACEHOLDER = re.compile(r"^\$(failed_test_name|failed_test_file)$")
_RISK = {PermissionLevel.SAFE_EXECUTE: "medium: executes project code (tests/linter) on this machine; no network, no file changes intended",
         PermissionLevel.WRITE_PROJECT: "high: modifies files in the project; never commits or pushes",
         PermissionLevel.EXTERNAL_NETWORK: "high: makes network requests",
         PermissionLevel.READ_ONLY: "low: reads files only"}


class _StepAbort(Exception):
    """Internal: stop the task with a terminal status."""

    def __init__(self, status: TaskStatus, error: str) -> None:
        super().__init__(error)
        self.status = status
        self.error = error


def _interpret_approval(answer: Any) -> tuple[ApprovalStatus, str | None]:
    if isinstance(answer, ActionApproval):
        return (answer.status if answer.status is not ApprovalStatus.PENDING else ApprovalStatus.DENIED), answer.approved_by
    if isinstance(answer, ApprovalStatus):
        return (answer if answer is not ApprovalStatus.PENDING else ApprovalStatus.DENIED), None
    if isinstance(answer, bool):
        return (ApprovalStatus.APPROVED if answer else ApprovalStatus.DENIED), None
    if isinstance(answer, str):
        try:
            status = ApprovalStatus(answer.lower())
        except ValueError:
            return ApprovalStatus.DENIED, None
        return (status if status is not ApprovalStatus.PENDING else ApprovalStatus.DENIED), None
    return ApprovalStatus.DENIED, None


class TaskExecutor:
    """Runs a delegated task: plan -> policy check -> (approval) -> tool -> evidence."""

    def __init__(self, workdir: str | os.PathLike[str], policy: PermissionPolicy = PermissionPolicy.SAFE_AUTO,
                 emit: Emit | None = None, request_approval: RequestApproval | None = None, *,
                 tools: dict[str, Tool] | None = None, limits: ExecLimits | None = None,
                 artifacts_dir: str | os.PathLike[str] | None = None, approval_timeout: float = 600.0,
                 task_timeout: float = 1800.0, on_update: Callable[[DelegatedTask], Any] | None = None,
                 on_activity: Callable[[ActivityInterval], Any] | None = None, allow_network: bool = False) -> None:
        self.sandbox = Sandbox(workdir)
        self.workdir = self.sandbox.root
        self.policy = policy
        self.emit = emit
        self.request_approval = request_approval
        self.tools = tools if tools is not None else default_tools()
        self.limits = limits or ExecLimits()
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else data_dir() / "tasks"
        self.approval_timeout = approval_timeout
        self.task_timeout = task_timeout
        self.on_update = on_update
        self.on_activity = on_activity
        self.allow_network = allow_network
        self.activity: list[ActivityInterval] = []   # every agent-work interval, all tasks (for the efficiency engine)

    # ---- event / persistence plumbing (never allowed to break a task) ----------------------------
    async def _call(self, fn: Callable[..., Any] | None, *args: Any) -> None:
        if fn is None:
            return
        try:
            out = fn(*args)
            if inspect.isawaitable(out):
                await out
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("executor callback failed")

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        await self._call(self.emit, event, data)

    async def _touch(self, task: DelegatedTask, event: str | None = None) -> None:
        task.revision += 1
        await self._call(self.on_update, task)
        if event:
            await self._emit(event, {"task": task.to_dict()})

    async def announce_created(self, task: DelegatedTask) -> None:
        await self._touch(task, "task.created")

    async def mark_cancelled_before_start(self, task: DelegatedTask, reason: str = "cancelled before it started") -> None:
        task.status = TaskStatus.CANCELLED
        task.completed_at = utc_now()
        task.error = reason
        task.result = build_result("cancelled", [], error=reason, artifacts=[], files_touched=[], intervals=[])
        await self._touch(task, "task.cancelled")

    def _interval(self, task: DelegatedTask, label: str, start) -> ActivityInterval:
        return ActivityInterval(start, None, label, task.id)

    async def _close_interval(self, interval: ActivityInterval, intervals: list[ActivityInterval]) -> None:
        interval.end = utc_now()
        intervals.append(interval)
        self.activity.append(interval)
        await self._call(self.on_activity, interval)

    # ---- main entry ------------------------------------------------------------------------------
    async def run(self, task: DelegatedTask, instruction: TrustedInstruction, *,
                  plan: list[dict[str, Any]] | None = None) -> DelegatedTask:
        """Execute ``task``.  ``plan`` lets a trusted host supply explicit steps (e.g. a patch); otherwise the
        deterministic planner runs."""
        if not isinstance(instruction, TrustedInstruction):
            raise UntrustedInstructionError("a TrustedInstruction is required; observed text cannot start a task")
        task.instruction = instruction.text
        task.created_from = instruction.origin
        steps: list[StepRecord] = []
        intervals: list[ActivityInterval] = []
        touched: list[str] = []
        log_file = TaskLog(self.artifacts_dir, task.id, self.limits.max_log_bytes)
        status, error = TaskStatus.COMPLETED, None
        task.started_at = task.started_at or utc_now()
        try:
            async with asyncio.timeout(self.task_timeout):
                await self._plan(task, instruction, plan, intervals)
                task.status = TaskStatus.RUNNING
                await self._touch(task, "task.running")
                await self._execute(task, steps, intervals, touched, log_file)
        except _StepAbort as abort:
            status, error = abort.status, abort.error
        except asyncio.CancelledError:
            await self._finish(task, TaskStatus.CANCELLED, "cancelled by user", steps, intervals, touched, log_file)
            raise
        except TimeoutError:
            status, error = TaskStatus.FAILED, f"task exceeded its {self.task_timeout:.0f}s time limit and was stopped"
        except Exception as exc:
            log.exception("delegated task crashed")
            status, error = TaskStatus.FAILED, f"internal executor error: {type(exc).__name__}"
        await self._finish(task, status, error, steps, intervals, touched, log_file)
        return task

    async def _finish(self, task: DelegatedTask, status: TaskStatus, error: str | None, steps: list[StepRecord],
                      intervals: list[ActivityInterval], touched: list[str], log_file: TaskLog) -> None:
        artifact = log_file.artifact()
        result = build_result(status.value, steps, error=error, artifacts=[artifact] if artifact else [],
                              files_touched=touched, intervals=intervals)
        task.status = status
        task.completed_at = utc_now()
        task.error = error
        task.result = result
        task.evidence = list(result["evidence"])
        await self._touch(task, f"task.{status.value}")

    # ---- planning --------------------------------------------------------------------------------
    async def _plan(self, task: DelegatedTask, instruction: TrustedInstruction, plan: list[dict[str, Any]] | None,
                    intervals: list[ActivityInterval]) -> None:
        task.status = TaskStatus.PLANNING
        await self._touch(task, "task.planning")
        interval = self._interval(task, "planning", utc_now())
        try:
            steps = plan if plan is not None else plan_instruction(instruction.text, self.workdir)
            for i, step in enumerate(steps, 1):
                if not isinstance(step, dict) or step.get("tool") not in self.tools or not isinstance(step.get("args", {}), dict):
                    raise PlanError(f"step {i} names an unknown tool or has malformed args")
            task.plan = [{"tool": s["tool"], "args": dict(s.get("args", {})), "why": str(s.get("why", ""))[:200],
                          **({"when": s["when"]} if s.get("when") else {})} for s in steps]
        except PlanError as exc:
            raise _StepAbort(TaskStatus.FAILED, str(exc)) from exc
        finally:
            await self._close_interval(interval, intervals)
        await self._touch(task)

    # ---- execution -------------------------------------------------------------------------------
    def _resolve_placeholders(self, args: dict[str, Any], last_facts: dict[str, Any]) -> dict[str, Any] | None:
        out: dict[str, Any] = {}
        for key, value in args.items():
            m = _PLACEHOLDER.match(value) if isinstance(value, str) else None
            if not m:
                out[key] = value
                continue
            names = last_facts.get("failed_names" if m.group(1) == "failed_test_name" else "failed_files") or []
            if not names:
                return None
            out[key] = names[0]
        return out

    async def _execute(self, task: DelegatedTask, steps: list[StepRecord], intervals: list[ActivityInterval],
                       touched: list[str], log_file: TaskLog) -> None:
        ctx = ToolContext(self.workdir, self.limits, self.allow_network)
        anchor: ToolResult | None = None  # last unconditional step; "prev_failed" and placeholders refer to it
        for number, planned in enumerate(task.plan, 1):
            tool = self.tools[planned["tool"]]
            name = tool.spec.name
            now = utc_now()
            if planned.get("when") == "prev_failed" and not (anchor is not None and not anchor.ok):
                steps.append(StepRecord(number, name, "", now, now, None, skipped_reason="previous step reported no failure"))
                continue
            args = self._resolve_placeholders(planned["args"], anchor.facts if anchor else {})
            if args is None:
                steps.append(StepRecord(number, name, "", now, now, None, skipped_reason="no failing test name to look up"))
                continue
            try:
                args = tool.validate(args, ctx)
            except ToolError as exc:
                raise _StepAbort(TaskStatus.FAILED, f"step {number} ({name}) rejected: {exc}") from exc
            described = redact(tool.describe(args))[:200]
            decision = PermissionEngine(self.policy, task.permission_level).decide(tool, args)
            if decision.decision is Decision.DENY:
                raise _StepAbort(TaskStatus.FAILED, f"step {number} ({name}) denied by policy: {decision.reason}")
            if decision.decision is Decision.ASK:
                await self._ask(task, number, tool, args, described, planned.get("why", ""), decision.reason)
            record = StepRecord(number, name, described, utc_now())
            steps.append(record)
            await self._emit("task.tool_started", {"task_id": task.id, "tool": name, "args_summary": described})
            interval = self._interval(task, name, record.started_at)
            try:
                result = await tool.run(args, ctx)
            except ToolError as exc:
                record.ok, record.summary, record.ended_at = False, f"{name} could not run: {exc}", utc_now()
                await self._close_interval(interval, intervals)
                await self._emit("task.tool_completed", {"task_id": task.id, "tool": name, "args_summary": described,
                                                         "summary": record.summary})
                raise _StepAbort(TaskStatus.FAILED, f"step {number} ({name}) failed: {exc}") from exc
            except asyncio.CancelledError:
                record.ok, record.summary, record.ended_at = False, f"{name} was cancelled", utc_now()
                await self._close_interval(interval, intervals)
                raise
            await self._close_interval(interval, intervals)
            record.ended_at = utc_now()
            record.ok, record.exit_code, record.facts = result.ok, result.exit_code, result.facts
            record.summary, record.timed_out, record.files_touched = result.summary, result.timed_out, result.files_touched
            record.command = " ".join(result.argv) if result.argv else None
            record.sample = [redact(s) for s in sample_lines(name, result)]
            touched.extend(result.files_touched)
            log_file.append(f"step {number}: {name} {described}" + (f" (exit {result.exit_code})" if result.exit_code is not None else ""),
                            result.output)
            if not planned.get("when"):
                anchor = result
            ctx.previous_output, ctx.previous_facts = result.output, result.facts
            done = {"task_id": task.id, "tool": name, "args_summary": described, "summary": result.summary[:300]}
            if result.exit_code is not None:
                done["exit_code"] = result.exit_code
            await self._emit("task.tool_completed", done)
            if result.timed_out:
                raise _StepAbort(TaskStatus.FAILED, f"step {number} ({name}) timed out; the process group was killed")
            if not result.ok and tool.spec.level is PermissionLevel.WRITE_PROJECT:
                raise _StepAbort(TaskStatus.FAILED, f"step {number} ({name}) failed: {result.summary}")

    async def _ask(self, task: DelegatedTask, number: int, tool: Tool, args: dict[str, Any], described: str, why: str,
                   reason: str) -> None:
        level = tool.spec.level
        scope = args.get("path") or ("entire project" if level is not PermissionLevel.WRITE_PROJECT else ", ".join(args.get("paths", [])))
        approval = ActionApproval(
            id=new_id("apr"), session_id=task.session_id, task_id=task.id,
            action={"tool": tool.spec.name, "step": number, "description": described},
            risk=_RISK.get(level, "medium"), requested_at=utc_now(), expires_at=utc_now() + timedelta(seconds=self.approval_timeout),
            why=(why or reason)[:300], permission_level=level, scope=f"{scope} in {self.workdir.name}")
        task.status = TaskStatus.WAITING_FOR_APPROVAL
        await self._touch(task)
        await self._emit("task.approval_requested", {"approval": approval.to_dict()})
        status, approver = ApprovalStatus.DENIED, None
        try:
            if self.request_approval is None:
                log.info("no approval channel; denying %s", tool.spec.name)
            else:
                answer = await asyncio.wait_for(self.request_approval(approval), timeout=self.approval_timeout)
                status, approver = _interpret_approval(answer)
        except TimeoutError:
            status = ApprovalStatus.EXPIRED
        except asyncio.CancelledError:
            approval.status, approval.approved_by = ApprovalStatus.DENIED, "system:task-cancelled"
            approval.revision += 1
            await self._emit("task.approval_resolved", {"approval": approval.to_dict()})
            raise
        except Exception:
            log.exception("approval callback failed")
        approval.status, approval.approved_by = status, approver
        approval.revision += 1
        await self._emit("task.approval_resolved", {"approval": approval.to_dict()})
        if status is ApprovalStatus.APPROVED:
            task.status = TaskStatus.RUNNING
            await self._touch(task, "task.running")
            return
        if status is ApprovalStatus.EXPIRED:
            raise _StepAbort(TaskStatus.FAILED, f"approval for step {number} ({tool.spec.name}) expired without an answer")
        raise _StepAbort(TaskStatus.CANCELLED, f"step {number} ({tool.spec.name}) was denied by the user")


class TaskManager:
    """Queue + lifecycle for one session's delegated tasks (one running task by default)."""

    def __init__(self, executor: TaskExecutor, *, session_id: str, user_id: str, device_id: str, max_concurrent: int = 1,
                 on_update: Callable[[DelegatedTask], Any] | None = None) -> None:
        self.executor = executor
        self.session_id, self.user_id, self.device_id = session_id, user_id, device_id
        self.max_concurrent = max(1, max_concurrent)
        if on_update is not None:
            executor.on_update = on_update
        self.tasks: dict[str, DelegatedTask] = {}
        self._queue: asyncio.Queue[tuple[DelegatedTask, TrustedInstruction, list[dict[str, Any]] | None]] = asyncio.Queue()
        self._running: dict[str, asyncio.Task[Any]] = {}
        self._done: dict[str, asyncio.Event] = {}
        self._workers: list[asyncio.Task[None]] = []

    def set_policy(self, policy: PermissionPolicy) -> None:
        """Applies to every step evaluated from now on (including queued tasks)."""
        self.executor.policy = policy

    def get(self, task_id: str) -> DelegatedTask | None:
        return self.tasks.get(task_id)

    def active(self) -> list[DelegatedTask]:
        return [t for t in self.tasks.values() if t.status not in TERMINAL]

    async def submit(self, instruction: TrustedInstruction, *, permission_level: PermissionLevel = PermissionLevel.SAFE_EXECUTE,
                     recommendation_id: str | None = None, plan: list[dict[str, Any]] | None = None) -> DelegatedTask:
        if not isinstance(instruction, TrustedInstruction):
            raise UntrustedInstructionError("submit() requires a TrustedInstruction; strings and observed text are refused")
        task = DelegatedTask(id=new_id("task"), session_id=self.session_id, user_id=self.user_id, device_id=self.device_id,
                             instruction=instruction.text, created_from=instruction.origin, permission_level=permission_level,
                             recommendation_id=recommendation_id)
        self.tasks[task.id] = task
        self._done[task.id] = asyncio.Event()
        await self.executor.announce_created(task)
        await self._queue.put((task, instruction, plan))
        self._ensure_workers()
        return task

    def _ensure_workers(self) -> None:
        self._workers = [w for w in self._workers if not w.done()]
        while len(self._workers) < self.max_concurrent:
            self._workers.append(asyncio.create_task(self._worker(), name="flow-task-worker"))

    async def _worker(self) -> None:
        while True:
            task, instruction, plan = await self._queue.get()
            try:
                if task.status is TaskStatus.CANCELLED:
                    continue
                child = asyncio.create_task(self.executor.run(task, instruction, plan=plan), name=f"flow-task-{task.id}")
                self._running[task.id] = child
                await asyncio.wait({child})
                if child.cancelled():
                    if task.status not in TERMINAL:  # cancelled before run() got to start
                        await self.executor.mark_cancelled_before_start(task)
                elif child.exception() is not None:
                    log.error("task %s crashed: %r", task.id, child.exception())
                    if task.status not in TERMINAL:
                        task.status, task.error = TaskStatus.FAILED, "internal executor error"
                        task.completed_at = utc_now()
                        await self.executor._touch(task, "task.failed")
            finally:
                self._running.pop(task.id, None)
                self._done[task.id].set()
                self._queue.task_done()

    async def wait(self, task_id: str, timeout: float | None = None) -> DelegatedTask:
        await asyncio.wait_for(self._done[task_id].wait(), timeout)
        return self.tasks[task_id]

    async def cancel(self, task_id: str) -> bool:
        """Cancel a queued, waiting or running task; a running subprocess group is killed before returning."""
        task = self.tasks.get(task_id)
        if task is None or task.status in TERMINAL:
            return False
        child = self._running.get(task_id)
        if child is not None:
            child.cancel()
            await asyncio.wait({child}, timeout=15)
            if task.status not in TERMINAL:
                await self.executor.mark_cancelled_before_start(task)
            return True
        await self.executor.mark_cancelled_before_start(task)
        self._done[task_id].set()
        return True

    async def shutdown(self) -> None:
        for task_id in list(self._running):
            await self.cancel(task_id)
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

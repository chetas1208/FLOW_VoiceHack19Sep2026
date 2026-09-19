"""Goal tracking: versioned goals, evidence-backed subtasks, and a conservative completion state.

Rules (see ``docs/flow/goal-tracking.md``):

* A goal is a *version*. ``set_goal`` appends a new ``GoalVersion``; older versions and the observations recorded
  under them are never rewritten, so nothing is rescored retroactively.
* ``progress()`` is ``done / total`` and only exists when subtasks exist. There is no invented percentage.
* Observations can move a subtask to ``in_progress`` but never to ``done``. Only a user edit or a *completed
  delegated task with a factual result* (for example ``run_tests`` with exit code 0) marks work done, and every
  such change carries the evidence that justified it.
* ``CONFIRMED_COMPLETE`` needs either an explicit user confirmation, or strong evidence: a passing validation step
  (``run_tests`` exit code 0, recorded under the *current* goal version) **and** every subtask done **and** at least
  one subtask the user wrote themselves (auto-suggested subtasks alone are not a decomposition of the goal).
  Anything weaker tops out at ``LIKELY_COMPLETE``.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from datetime import datetime
from typing import Any, Callable, Iterable

from .models import iso, utc_now
from .remote_models import (DelegatedTask, GoalState, GoalVersion, Subtask, SubtaskStatus, TaskStatus)

VALIDATION_TOOLS = frozenset({"run_tests"})
# Delegated-task tools that correspond to a milestone worth tracking. Investigative tools (read/search) do not.
TOOL_SUBTASKS: dict[str, str] = {
    "run_tests": "Run the test suite",
    "run_linter": "Run the linter",
    "inspect_package_metadata": "Check dependency versions",
}
TEST_PHASES = frozenset({"testing", "validation", "verifying"})
MAX_OBSERVATIONS = 500
MAX_EVIDENCE = 6

Clock = Callable[[], datetime]


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def _subtask_id(session_id: str, title: str, salt: int = 0) -> str:
    digest = hashlib.sha1(f"{session_id}:{_norm_title(title)}:{salt}".encode()).hexdigest()[:16]
    return f"sub_{digest}"


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=utc_now().tzinfo)
    return None


class GoalTracker:
    """Per-session goal, subtasks and completion state. Pure and deterministic; the daemon persists it."""

    def __init__(self, session_id: str, goal: str, *, source: str = "cli", clock: Clock | None = None,
                 started_at: datetime | None = None) -> None:
        if not goal or not goal.strip():
            raise ValueError("goal must not be empty")
        self.session_id = session_id
        self._clock: Clock = clock or utc_now
        self.versions: list[GoalVersion] = []
        self.subtasks: list[Subtask] = []
        self.observations: deque[dict[str, Any]] = deque(maxlen=MAX_OBSERVATIONS)
        self.validations: list[dict[str, Any]] = []
        self._recorded_tasks: dict[str, tuple[str, int]] = {}
        self._user_confirmed: dict[int, str] = {}      # goal version -> who confirmed
        self._goal_revision: dict[int, int] = {}
        self._runtime_revision = 0
        self._last_runtime: tuple[int, str] | None = None
        self.versions.append(GoalVersion(session_id, 1, goal.strip(), effective_at=started_at or self._clock(),
                                         source=source, state=GoalState.NOT_STARTED))
        self._goal_revision[1] = 1

    # ---- goal versions ------------------------------------------------------------------------
    @property
    def current(self) -> GoalVersion:
        return self.versions[-1]

    @property
    def goal(self) -> str:
        return self.current.goal

    @property
    def history(self) -> list[GoalVersion]:
        return list(self.versions)

    def set_goal(self, goal: str, source: str = "cli", effective_at: datetime | None = None) -> GoalVersion:
        """Append a new goal version. Setting the identical text again is a no-op (returns the current version).

        Past observations keep the version they were recorded under; a confirmation or validation belongs to the
        version it happened under and never carries over to the new one.
        """
        text = (goal or "").strip()
        if not text:
            raise ValueError("goal must not be empty")
        if _norm_title(text) == _norm_title(self.current.goal):
            return self.current
        self._freeze_current()
        version = GoalVersion(self.session_id, self.current.version + 1, text,
                              effective_at=effective_at or self._clock(), source=source, state=GoalState.NOT_STARTED)
        self.versions.append(version)
        self._goal_revision[version.version] = 1
        self._refresh()
        return version

    def version_at(self, moment: datetime | str | None) -> GoalVersion:
        when = _when(moment)
        if when is None:
            return self.current
        chosen = self.versions[0]
        for version in self.versions:
            if version.effective_at <= when:
                chosen = version
        return chosen

    def _freeze_current(self) -> None:
        self.current.state = self.state
        self._goal_revision[self.current.version] = self._goal_revision.get(self.current.version, 0) + 1

    # ---- subtasks -----------------------------------------------------------------------------
    def set_subtasks(self, items: Iterable[dict[str, Any] | Subtask]) -> list[Subtask]:
        """Replace the subtask list with the user's edit. Existing evidence is kept for subtasks that survive."""
        existing = {item.id: item for item in self.subtasks}
        by_title = {_norm_title(item.title): item for item in self.subtasks}
        result: list[Subtask] = []
        seen: set[str] = set()
        for position, raw in enumerate(items):
            data = raw.to_dict() if isinstance(raw, Subtask) else dict(raw)
            title = str(data.get("title") or "").strip()
            if not title:
                raise ValueError("subtask title must not be empty")
            status = SubtaskStatus(data.get("status") or "todo")
            previous = existing.get(data.get("id") or "") or by_title.get(_norm_title(title))
            sid = previous.id if previous else (data.get("id") or _subtask_id(self.session_id, title))
            salt = 0
            while sid in seen:
                salt += 1
                sid = _subtask_id(self.session_id, title, salt)
            seen.add(sid)
            evidence = list(previous.evidence) if previous else []
            if previous is None or previous.status is not status:
                note = {SubtaskStatus.DONE: "marked done by the user", SubtaskStatus.IN_PROGRESS: "marked in progress by the user",
                        SubtaskStatus.TODO: "marked to do by the user"}[status]
                evidence = self._evidence(evidence, note)
            revision = (previous.revision + (1 if previous and (previous.title != title or previous.status is not status
                                                                  or previous.position != position) else 0)) if previous else 1
            result.append(Subtask(sid, self.session_id, title, status, evidence, position, "user", revision))
        self.subtasks = result
        self._refresh()
        return list(result)

    def _find(self, title: str) -> Subtask | None:
        key = _norm_title(title)
        return next((item for item in self.subtasks if _norm_title(item.title) == key), None)

    @staticmethod
    def _evidence(existing: list[str], *notes: str) -> list[str]:
        out = list(existing)
        for note in notes:
            if note and note not in out:
                out.append(note)
        return out[-MAX_EVIDENCE:]

    def _suggest(self, title: str, status: SubtaskStatus, evidence: list[str], origin: str) -> Subtask:
        """Add or advance an auto-suggested subtask. A user-owned status is never overridden downward, and an
        auto suggestion never reopens a ``done`` subtask."""
        item = self._find(title)
        if item is None:
            item = Subtask(_subtask_id(self.session_id, title), self.session_id, title, status,
                           self._evidence([], *evidence), len(self.subtasks), origin, 1)
            self.subtasks.append(item)
            return item
        order = {SubtaskStatus.TODO: 0, SubtaskStatus.IN_PROGRESS: 1, SubtaskStatus.DONE: 2}
        changed = False
        if order[status] > order[item.status]:
            item.status, changed = status, True
        merged = self._evidence(item.evidence, *evidence)
        if merged != item.evidence:
            item.evidence, changed = merged, True
        if changed:
            item.revision += 1
        return item

    # ---- observations -------------------------------------------------------------------------
    def record_observation(self, obs: dict[str, Any]) -> dict[str, Any]:
        """Store an observation under the goal version in force at its timestamp. Returns the stored copy."""
        stored = dict(obs)
        stamp = _when(obs.get("timestamp")) or self._clock()
        stored["goal_version"] = self.version_at(stamp).version
        self.observations.append(stored)
        phase = str(obs.get("task_phase") or (obs.get("metadata") or {}).get("task_phase") or "").lower()
        if phase in TEST_PHASES and stored["goal_version"] == self.current.version:
            activity = obs.get("activity") or obs.get("activity_summary") or "testing"
            self._suggest("Run the test suite", SubtaskStatus.IN_PROGRESS,
                          [f"observed {phase} at {stamp.strftime('%H:%M')}: {activity}"], "observed")
        self._refresh()
        return stored

    def observations_for(self, version: int) -> list[dict[str, Any]]:
        return [item for item in self.observations if item.get("goal_version") == version]

    # ---- delegated task results ---------------------------------------------------------------
    def record_task_result(self, task: DelegatedTask) -> bool:
        """Fold a finished delegated task into subtasks/validation. Idempotent per (task id, revision).

        Returns True when the task was new information. Cancelled or unfinished tasks are ignored; a result
        recorded for a task that finished under an *older* goal version is attributed to that version and
        cannot complete the current goal.
        """
        if task.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED) or not task.result:
            return False
        marker = (task.status.value, task.revision)
        if self._recorded_tasks.get(task.id) == marker:
            return False
        self._recorded_tasks[task.id] = marker
        finished = task.completed_at or self._clock()
        version = self.version_at(finished).version
        current = version == self.current.version
        for step in task.result.get("steps") or []:
            tool = step.get("tool")
            if tool not in TOOL_SUBTASKS or step.get("ok") is None:
                continue
            code = step.get("exit_code")
            passed = bool(step.get("ok")) and (code in (0, None))
            if tool in VALIDATION_TOOLS:
                self.validations.append({"task_id": task.id, "goal_version": version, "passed": passed and code == 0,
                                         "exit_code": code, "at": finished})
            if not current:
                continue
            note = f"task {task.id}: {tool} exit code {code}" if code is not None else f"task {task.id}: {tool} ok"
            lines = [note]
            if step.get("summary"):
                lines.append(f"task {task.id}: {step['summary']}")
            if passed:
                self._suggest(TOOL_SUBTASKS[tool], SubtaskStatus.DONE, lines, "delegated")
            else:
                self._suggest(TOOL_SUBTASKS[tool], SubtaskStatus.IN_PROGRESS, lines, "delegated")
        self._refresh()
        return True

    # ---- state --------------------------------------------------------------------------------
    def confirm_complete(self, source: str = "user") -> GoalState:
        """Explicit user confirmation. The only way to reach CONFIRMED_COMPLETE without validation evidence."""
        self._user_confirmed[self.current.version] = source
        self._refresh()
        return self.state

    def reopen(self) -> GoalState:
        self._user_confirmed.pop(self.current.version, None)
        self._refresh()
        return self.state

    def progress(self) -> float | None:
        """``done / total``; ``None`` when there are no subtasks (never an invented percentage)."""
        if not self.subtasks:
            return None
        return sum(1 for item in self.subtasks if item.status is SubtaskStatus.DONE) / len(self.subtasks)

    def counts(self) -> dict[str, int]:
        done = sum(1 for item in self.subtasks if item.status is SubtaskStatus.DONE)
        return {"done": done, "total": len(self.subtasks),
                "in_progress": sum(1 for item in self.subtasks if item.status is SubtaskStatus.IN_PROGRESS)}

    def latest_validation(self) -> dict[str, Any] | None:
        mine = [item for item in self.validations if item["goal_version"] == self.current.version]
        return mine[-1] if mine else None

    def confirmation(self) -> dict[str, Any] | None:
        """Why the goal is (or is not) confirmed complete, for display."""
        version = self.current.version
        if version in self._user_confirmed:
            return {"by": self._user_confirmed[version], "kind": "user"}
        if self._strong_evidence():
            check = self.latest_validation() or {}
            return {"by": f"task {check.get('task_id')}", "kind": "evidence"}
        return None

    def _strong_evidence(self) -> bool:
        check = self.latest_validation()
        if not check or not check["passed"] or not self.subtasks:
            return False
        if any(item.status is not SubtaskStatus.DONE for item in self.subtasks):
            return False
        return any(item.origin == "user" for item in self.subtasks)

    @property
    def state(self) -> GoalState:
        version = self.current.version
        if version in self._user_confirmed or self._strong_evidence():
            return GoalState.CONFIRMED_COMPLETE
        counts = self.counts()
        check = self.latest_validation()
        if counts["total"]:
            if counts["done"] == counts["total"]:
                return GoalState.LIKELY_COMPLETE
            if counts["done"]:
                return GoalState.PARTIALLY_COMPLETE
        elif check and check["passed"]:
            return GoalState.LIKELY_COMPLETE
        if counts["in_progress"] or self.observations_for(version):
            return GoalState.IN_PROGRESS
        return GoalState.NOT_STARTED

    def _refresh(self) -> None:
        state = self.state
        self.current.state = state
        signature = (self.current.version, state.value)
        if signature != self._last_runtime:
            self._last_runtime = signature
            self._runtime_revision += 1
            self._goal_revision[self.current.version] = self._goal_revision.get(self.current.version, 0) + 1

    # ---- contract entities --------------------------------------------------------------------
    def to_entities(self) -> list[dict[str, Any]]:
        """Contract entities for ``POST /v1/sessions/{id}/entities:batch``.

        ``goal_version`` (id = str(version)), one ``subtask`` per subtask, and a ``runtime_state`` *fragment*
        carrying ``goal_version`` and ``goal_state``; the daemon merges that fragment into its runtime_state row.
        """
        entities: list[dict[str, Any]] = []
        for version in self.versions:
            data = version.to_dict()
            entities.append({"kind": "goal_version", "id": str(version.version),
                             "revision": self._goal_revision.get(version.version, 1), "data": data})
        for item in self.subtasks:
            entities.append({"kind": "subtask", "id": item.id, "revision": item.revision, "data": item.to_dict()})
        entities.append({"kind": "runtime_state", "id": "current", "revision": self._runtime_revision,
                         "data": {"goal_version": self.current.version, "goal_state": self.state.value}})
        return entities

    def snapshot(self) -> dict[str, Any]:
        """Display shape used by ``flow goal`` and the live view."""
        return {"text": self.goal, "version": self.current.version, "state": self.state.value,
                "progress": self.progress(), "counts": self.counts(), "confirmation": self.confirmation(),
                "subtasks": [item.to_dict() for item in self.subtasks],
                "history": [{"version": v.version, "goal": v.goal, "source": v.source, "effective_at": iso(v.effective_at)}
                            for v in self.versions]}

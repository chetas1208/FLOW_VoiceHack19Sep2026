"""Core types of the delegated-task executor: trust boundary, tool protocol, results.

Only a :class:`TrustedInstruction` can start a task.  It can be minted from an authenticated
CLI/web command (or a user-accepted recommendation) and never from screen text, observations,
window titles, logs or any other data the agent merely *reads*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..remote_models import (
    CommandSource,
    CommandType,
    PermissionLevel,
    SessionCommand,
    TaskOrigin,
)

MAX_INSTRUCTION_CHARS = 2000
_AUTH_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{3,120}$")
# Origins an attacker-influenced data source could claim; never acceptable.
_UNTRUSTED_ORIGIN_HINTS = ("observation", "screen", "ocr", "vision", "log", "window", "voice", "system", "tool")


class UntrustedInstructionError(ValueError):
    """Raised when text that did not come from an authenticated user is offered as an instruction."""


class UntrustedText(str):
    """Marker type for text derived from observations (screen text, OCR, logs, tool output).

    Observation-side code should wrap what it extracts with :func:`taint`; such text is refused by
    :class:`TrustedInstruction` even if someone tries to pass it off as user input.
    """

    __slots__ = ()


def taint(value: str) -> UntrustedText:
    return UntrustedText(value)


@dataclass(frozen=True, slots=True)
class TrustedInstruction:
    """A task instruction typed by an authenticated user (CLI/web) or accepted from a recommendation."""

    text: str
    origin: TaskOrigin
    authenticated_by: str

    def __post_init__(self) -> None:
        text = self.text
        if type(text) is not str:  # rejects UntrustedText and every other str subclass
            raise UntrustedInstructionError("instruction text must be plain user-typed text, not derived/observed text")
        if not text.strip() or "\x00" in text:
            raise UntrustedInstructionError("instruction is empty or contains control bytes")
        if len(text) > MAX_INSTRUCTION_CHARS:
            raise UntrustedInstructionError(f"instruction longer than {MAX_INSTRUCTION_CHARS} characters")
        origin = self.origin
        if not isinstance(origin, TaskOrigin):
            raw = str(origin).lower()
            if any(hint in raw for hint in _UNTRUSTED_ORIGIN_HINTS):
                raise UntrustedInstructionError(f"origin {origin!r} is not a trusted instruction source")
            try:
                origin = TaskOrigin(raw)
            except ValueError as exc:
                raise UntrustedInstructionError(f"unknown instruction origin {origin!r}") from exc
            object.__setattr__(self, "origin", origin)
        by = self.authenticated_by
        if not isinstance(by, str) or not _AUTH_RE.match(by):
            raise UntrustedInstructionError("authenticated_by must name the authenticated principal (e.g. 'device:dev_123')")

    @classmethod
    def from_command(cls, command: SessionCommand) -> TrustedInstruction:
        """Mint from an ADD_TASK command that arrived over the authenticated command channel."""
        if command.type is not CommandType.ADD_TASK:
            raise UntrustedInstructionError("only ADD_TASK commands carry a task instruction")
        origin = {CommandSource.CLI: TaskOrigin.CLI, CommandSource.WEB: TaskOrigin.WEB}.get(command.source)
        if origin is None:
            raise UntrustedInstructionError(f"command source {command.source.value!r} may not create tasks")
        text = command.payload.get("instruction")
        return cls(text if type(text) is str else "", origin, f"user:{command.user_id}/{command.command_id}")

    @classmethod
    def from_recommendation(cls, proposed_task: str, recommendation_id: str, accepted_by: str) -> TrustedInstruction:
        """Mint from a recommendation the user explicitly accepted (EXECUTE_RECOMMENDATION)."""
        return cls(proposed_task if type(proposed_task) is str else "", TaskOrigin.RECOMMENDATION,
                   f"accepted:{accepted_by}/{recommendation_id}")


class ToolError(Exception):
    """A tool refused to run or could not run (bad args, sandbox violation, missing binary)."""


@dataclass(slots=True)
class ExecLimits:
    timeout: float = 60.0           # seconds per subprocess (git, linters)
    test_timeout: float = 300.0     # seconds for test runs
    max_output_bytes: int = 64_000  # returned to the task result (head+tail)
    max_log_bytes: int = 512_000    # per-task raw log artifact
    max_read_bytes: int = 64_000    # read_file cap
    max_write_bytes: int = 200_000  # write_file cap
    max_search_matches: int = 50
    max_list_entries: int = 300


@dataclass(slots=True)
class ToolContext:
    workdir: Path
    limits: ExecLimits = field(default_factory=ExecLimits)
    allow_network: bool = False
    env_extra: dict[str, str] = field(default_factory=dict)
    previous_output: str = ""            # raw (redacted) output of the previous step, for read_logs(source=previous)
    previous_facts: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    """Outcome of one tool call.  ``exit_code`` is only set for subprocess tools."""

    tool: str
    ok: bool                              # the tool did what was asked (subprocess: exit code 0)
    summary: str
    output: str = ""                      # redacted, capped text for the log artifact
    exit_code: int | None = None
    argv: list[str] | None = None
    facts: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    total_bytes: int = 0
    files_touched: list[str] = field(default_factory=list)
    duration: float = 0.0
    timed_out: bool = False


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    level: PermissionLevel
    description: str


class Tool(Protocol):
    spec: ToolSpec

    def validate(self, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        """Return normalised args or raise :class:`ToolError`.  Must not touch the filesystem state."""

    def describe(self, args: dict[str, Any]) -> str:
        """Short human string of what will happen (goes into approval prompts and events)."""

    def is_low_risk(self, args: dict[str, Any]) -> bool:
        """True when ``safe_auto`` may run this without asking."""

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...

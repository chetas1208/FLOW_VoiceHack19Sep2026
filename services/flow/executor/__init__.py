"""Safe delegated-task executor: deterministic planner, permissioned tools, evidence-based results.

See ``docs/flow/delegated-tasks.md``.
"""

from .base import (
           ExecLimits,
           TrustedInstruction,
           UntrustedInstructionError,
           UntrustedText,
           taint,
)
from .planner import PlanError, plan_instruction
from .policy import (
           Decision,
           PermissionEngine,
           PolicyDecision,
           classify_argv,
           classify_command_text,
)
from .results import ActivityInterval
from .runner import TaskExecutor, TaskManager
from .tools import default_tools

__all__ = ["ActivityInterval", "Decision", "ExecLimits", "PermissionEngine", "PlanError", "PolicyDecision", "TaskExecutor",
           "TaskManager", "TrustedInstruction", "UntrustedInstructionError", "UntrustedText", "classify_argv",
           "classify_command_text", "default_tools", "plan_instruction", "taint"]

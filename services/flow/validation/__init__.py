"""Machine-readable environment validation for FLOW (see docs/flow/macos-observer.md)."""

from .macos import parse_scenarios, run_macos_validation, summary_lines, write_artifact
from .model import CHECKS, FAILED, NOT_CONFIGURED, SKIPPED, STATUSES, VERIFIED, validate_artifact

__all__ = ["CHECKS", "FAILED", "NOT_CONFIGURED", "SKIPPED", "STATUSES", "VERIFIED", "parse_scenarios",
           "run_macos_validation", "summary_lines", "validate_artifact", "write_artifact"]

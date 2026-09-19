"""Orchestrator for ``flow validate macos``: builds the machine-readable artifact."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import probes, scenarios
from .context import ValidationContext
from .measure import Measured, current_rss_mb, peak_rss_mb
from .model import (CHECKS, FAILED, NOT_CONFIGURED, SCENARIOS, SKIPPED, VERIFIED, all_sections, overall, section,
                    validate_artifact)

SCHEMA_VERSION = 1


class ResourceTracker:
    """Idle/peak RSS and average CPU for the validation run, children included."""

    def __init__(self, measure) -> None:
        self._measure = measure
        self.started = time.monotonic()
        self.cpu_start = time.process_time()
        self.idle_rss_mb = current_rss_mb()
        self.children: list[dict[str, Any]] = []
        self._cpu_children = 0.0

    def measure(self, command, timeout, env=None) -> Measured:
        result = self._measure(command, timeout, env)
        self.children.append({"name": " ".join(str(part) for part in command[-3:]),
                              "peak_rss_mb": round(result.peak_rss_mb, 1),
                              "cpu_seconds": round(result.cpu_seconds, 2),
                              "wall_seconds": round(result.wall_seconds, 2)})
        self._cpu_children += result.cpu_seconds
        return result

    def section(self, ctx: ValidationContext) -> dict[str, Any]:
        wall = max(time.monotonic() - self.started, 1e-6)
        cpu = (time.process_time() - self.cpu_start) + self._cpu_children
        peak = max([peak_rss_mb(), self.idle_rss_mb or 0.0, *[child["peak_rss_mb"] for child in self.children]])
        numbers = {"idle_rss_mb": None if self.idle_rss_mb is None else round(self.idle_rss_mb, 1),
                   "peak_rss_mb": round(peak, 1), "avg_cpu_percent": round(100 * cpu / wall, 1),
                   "sample_seconds": round(wall, 1), "children": self.children,
                   "scope": "validation process plus the vision/voice test children"}
        if not ctx.is_macos:
            return section(NOT_CONFIGURED, note=f"measured on a {ctx.system()} host; not valid macOS evidence",
                           **numbers)
        if numbers["idle_rss_mb"] is None:
            return section(FAILED, reason="could not read process RSS", **numbers)
        return section(VERIFIED, **numbers)


def parse_scenarios(values: Iterable[str] | None) -> list[str]:
    requested: list[str] = []
    for value in values or ["all"]:
        for name in str(value).replace(" ", ",").split(","):
            if name:
                requested.append(name.strip().lower())
    unknown = [name for name in requested if name != "all" and name not in CHECKS]
    if unknown:
        raise ValueError(f"unknown scenario(s): {', '.join(unknown)}; choose from {', '.join(CHECKS)}, all")
    return list(CHECKS) if "all" in requested else [name for name in CHECKS if name in requested]


def _not_selected(name: str) -> dict[str, Any]:
    return section(SKIPPED, reason=f"'{name}' not selected")


def run_macos_validation(ctx: ValidationContext, selected: list[str]) -> dict[str, Any]:
    tracker = ResourceTracker(ctx.measure)
    ctx.measure = tracker.measure
    want = set(selected)
    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **probes.platform_fields(ctx),
        "requested": selected,
        "interactive": ctx.interactive,
    }
    artifact["environment"] = probes.check_environment(ctx) if "env" in want else _not_selected("env")
    artifact["permissions"] = probes.check_permissions(ctx) if "permissions" in want else _not_selected("permissions")
    artifact["models"] = probes.check_models(ctx) if "models" in want else _not_selected("models")
    artifact["screen_capture"] = probes.check_screen_capture(ctx) if "observer" in want else _not_selected("observer")
    artifact["vision"] = probes.check_flow_test(ctx, "vision") if "vision" in want else _not_selected("vision")
    artifact["voice"] = probes.check_flow_test(ctx, "voice") if "voice" in want else _not_selected("voice")
    artifact["cloud"] = probes.check_cloud(ctx) if "cloud" in want else _not_selected("cloud")
    artifact["scenarios"] = {name: scenarios.run_scenario(name, ctx) if name in want else _not_selected(name)
                             for name in SCENARIOS}
    artifact["resources"] = tracker.section(ctx) if "resources" in want else _not_selected("resources")
    artifact["overall"], artifact["summary"] = overall(all_sections(artifact))
    problems = validate_artifact(artifact)
    if problems:  # a bug in this module, never in the operator's environment
        artifact["overall"] = FAILED
        artifact["artifact_problems"] = problems
    return artifact


def write_artifact(artifact: dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=target.parent, prefix=".macos-validation-", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as out:
            json.dump(artifact, out, indent=2, sort_keys=False)
            out.write("\n")
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target


def summary_lines(artifact: dict[str, Any]) -> list[str]:
    rows = [("environment", artifact["environment"]), ("permissions", artifact["permissions"]),
            ("models", artifact["models"]), ("screen capture", artifact["screen_capture"]),
            ("vision", artifact["vision"]), ("voice", artifact["voice"]), ("resources", artifact["resources"]),
            *[(f"scenario {name}", item) for name, item in artifact["scenarios"].items()],
            ("cloud", artifact["cloud"])]
    lines = [f"FLOW macOS validation  {artifact['platform']} {artifact['architecture']}  "
             f"flow {artifact['flow_version']}", ""]
    for label, item in rows:
        detail = item.get("reason") or (item.get("evidence") or {}).get("reason") or item.get("note") or ""
        lines.append(f"  {label:<20} {item['status']:<15} {detail}".rstrip())
    counts = artifact["summary"]
    lines += ["", "  overall: " + artifact["overall"] + "  (" +
              ", ".join(f"{key} {value}" for key, value in counts.items()) + ")"]
    return lines

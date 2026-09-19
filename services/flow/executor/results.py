"""Task results: factual evidence, short summaries, bounded raw-log artifacts, agent-activity intervals."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import iso
from .base import ToolResult

MAX_EVIDENCE_ITEMS = 24
MAX_EVIDENCE_CHARS = 300
MAX_SUMMARY_CHARS = 600


def _cut(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


@dataclass(slots=True)
class StepRecord:
    index: int
    tool: str
    args_summary: str
    started_at: datetime
    ended_at: datetime | None = None
    ok: bool | None = None                 # None = skipped
    exit_code: int | None = None
    summary: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    command: str | None = None
    skipped_reason: str | None = None
    files_touched: list[str] = field(default_factory=list)
    timed_out: bool = False
    sample: list[str] = field(default_factory=list)   # a few real output lines worth quoting

    def to_public(self) -> dict[str, Any]:
        return {"index": self.index, "tool": self.tool, "ok": self.ok, "exit_code": self.exit_code,
                "summary": _cut(self.summary or (self.skipped_reason or ""), 200),
                "seconds": round((self.ended_at - self.started_at).total_seconds(), 2) if self.ended_at else None}


@dataclass(slots=True)
class ActivityInterval:
    """A stretch of time the agent (not the human) was working; feeds the human-vs-agent report."""

    start: datetime
    end: datetime | None
    label: str
    task_id: str

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "label": self.label, "start": iso(self.start),
                "end": iso(self.end) if self.end else None}


def sample_lines(tool: str, result: ToolResult, limit: int = 3) -> list[str]:
    """Pick a few real output lines to quote as evidence (never invented text)."""
    lines = [ln.strip() for ln in result.output.splitlines() if ln.strip()]
    if tool == "search_text":
        return lines[:limit]
    if tool in {"read_logs", "run_tests", "run_linter"}:
        import re
        hits = [ln for ln in lines if re.search(r"\b(error|exception|traceback|failed|assert)", ln, re.IGNORECASE)]
        return hits[:limit]
    return []


def evidence_for(step: StepRecord) -> list[str]:
    """Evidence strings that quote real facts: command, exit code, parsed counts, quoted output lines."""
    if step.skipped_reason:
        return [_cut(f"{step.tool}: skipped ({step.skipped_reason})", MAX_EVIDENCE_CHARS)]
    head = f"{step.tool}: "
    if step.timed_out:
        head += "timed out and was killed; "
    elif step.exit_code is not None:
        head += f"exit code {step.exit_code}; "
    text = head + step.summary
    if step.command:
        command = step.command if len(step.command) <= 110 else step.command[:109] + "…"
        text += f" [cmd: {command}]"
    out = [_cut(text, MAX_EVIDENCE_CHARS)]
    failed = step.facts.get("failed_tests")
    if failed:
        out.append(_cut(f"{step.tool}: failing tests: " + ", ".join(failed[:5])
                        + (f" (+{len(failed) - 5} more)" if len(failed) > 5 else ""), MAX_EVIDENCE_CHARS))
    if step.tool == "inspect_package_metadata":
        for dep in step.facts.get("dependencies", [])[:8]:
            out.append(_cut(f"{dep['name']} declared {dep['declared']}, locked {dep.get('locked') or 'n/a'} ({dep['file']})",
                            MAX_EVIDENCE_CHARS))
    for line in step.sample:
        out.append(_cut(f"{step.tool} output: {line}", MAX_EVIDENCE_CHARS))
    return out


def build_result(status: str, steps: list[StepRecord], *, error: str | None, artifacts: list[dict[str, Any]],
                 files_touched: list[str], intervals: list[ActivityInterval]) -> dict[str, Any]:
    evidence: list[str] = []
    for step in steps:
        if not step.skipped_reason:
            evidence.extend(evidence_for(step))
    evidence = evidence[:MAX_EVIDENCE_ITEMS]
    done = [s for s in steps if s.ok is not None]
    findings = [s for s in done if not s.ok]
    if status == "completed":
        outcome = "findings" if findings else "ok"
        body = "; ".join(s.summary for s in done) or "no steps were needed"
        prefix = "Completed with findings" if findings else "Completed"
        summary = f"{prefix}: {body}"
    else:
        outcome = status
        body = "; ".join(s.summary for s in done)
        summary = f"Task {status}: {error or 'no detail'}" + (f". Before that: {body}" if body else "")
    return {"status": status, "outcome": outcome, "summary": _cut(summary, MAX_SUMMARY_CHARS), "evidence": evidence,
            "artifacts": artifacts, "files_touched": sorted(dict.fromkeys(files_touched)),
            "steps": [s.to_public() for s in steps], "agent_activity": [i.to_dict() for i in intervals]}


class TaskLog:
    """Append-only, size-bounded raw-log artifact (already-redacted text only)."""

    def __init__(self, directory: Path, task_id: str, max_bytes: int) -> None:
        self.path = directory / f"{task_id}.log"
        self.max_bytes = max_bytes
        self.written = 0
        self.full = False
        self._opened = False

    def append(self, header: str, body: str) -> None:
        if self.full:
            return
        try:
            if not self._opened:
                self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                os.close(fd)
                self._opened = True
            chunk = f"### {header}\n{body}\n\n".encode("utf-8", "replace")
            room = self.max_bytes - self.written
            if len(chunk) > room:
                chunk = chunk[:max(0, room)] + b"\n[log truncated: artifact size cap reached]\n"
                self.full = True
            with open(self.path, "ab") as fh:
                fh.write(chunk)
            self.written += len(chunk)
        except OSError:
            self.full = True

    def artifact(self) -> dict[str, Any] | None:
        if not self._opened or not self.path.exists():
            return None
        data = self.path.read_bytes()
        return {"kind": "log", "name": self.path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()[:16],
                "truncated": self.full}

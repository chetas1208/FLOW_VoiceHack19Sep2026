"""Filesystem and process sandbox primitives (no shell, no network by default, bounded output).

Honest scope: this is a *policy* sandbox — path checks, an argv allowlist, a scrubbed environment,
process-group kill on timeout/cancel, and proxy/offline settings.  It is not a kernel sandbox: a
test suite the user asked to run still executes project code as the user.  That is exactly why
``run_tests`` is SAFE_EXECUTE and gated by policy.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
import signal
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..privacy.redaction import redact_text
from ..remote_models import PermissionLevel
from .base import ExecLimits, ToolError
from .policy import assert_argv_allowed

_SECRET_DIRS = {".git", ".ssh", ".aws", ".gnupg", ".kube", ".azure", ".docker", ".terraform", ".gcloud", ".config/gcloud"}
_SECRET_NAME_GLOBS = (
    ".env", ".env.*", "*.env", ".envrc", "*.pem", "*.key", "*.p12", "*.pfx", "*.jks", "*.keystore", "*.ppk", "*.gpg",
    "*.asc", "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", ".netrc", "_netrc", ".npmrc", ".yarnrc", ".yarnrc.yml",
    ".pypirc", ".htpasswd", ".pgpass", ".git-credentials", ".dockercfg", "credentials", "credentials.*",
    "*.credentials", "secrets", "secrets.*", "secret.*", "*.secret", "*.secrets", "service-account*.json",
    "serviceaccount*.json", "kubeconfig", "*.kubeconfig", "*.tfstate", "*.tfstate.*", "*.tfvars", "token", "tokens",
    "*.token", ".token", "auth.json", "client_secret*.json", "master.key",
)
_SAFE_SUFFIXES = (".example", ".sample", ".template", ".dist", ".tpl")
# pathspec excludes for git diff (git glob syntax)
GIT_SECRET_PATHSPECS = tuple(f":(exclude,glob)**/{g}" for g in (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", ".netrc", ".npmrc", ".pypirc",
    "credentials*", "secrets.*", "*.secret", "*.tfstate", "*.tfvars", "service-account*.json", ".htpasswd"))

IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
                ".tox", "dist", "build", ".next", ".cache"}


class SandboxError(ToolError):
    """A path or command violated the sandbox."""


def is_secret_name(name: str) -> bool:
    lowered = name.lower()
    if lowered.endswith(_SAFE_SUFFIXES):
        return False
    return any(fnmatch.fnmatch(lowered, g) for g in _SECRET_NAME_GLOBS)


def secret_reason(relative: Path) -> str | None:
    parts = [p for p in relative.parts if p not in ("", ".")]
    for i, part in enumerate(parts):
        if part.lower() in _SECRET_DIRS:
            return f"'{part}' directories are off-limits"
    joined = "/".join(p.lower() for p in parts)
    if ".config/gcloud" in joined:
        return "gcloud config is off-limits"
    if parts and is_secret_name(parts[-1]):
        return f"'{parts[-1]}' looks like a secret/credential file"
    return None


class Sandbox:
    """Resolves user-supplied paths strictly inside ``root``."""

    def __init__(self, workdir: str | os.PathLike[str]) -> None:
        self.root = Path(os.path.realpath(workdir))
        if not self.root.is_dir():
            raise SandboxError(f"workdir does not exist: {workdir}")

    def relative(self, path: Path) -> str:
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            return str(path)
        return str(rel) or "."

    def resolve(self, raw: str, *, must_exist: bool = True, allow_secret: bool = False) -> Path:
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise SandboxError("path must be a non-empty string")
        candidate = Path(raw) if os.path.isabs(raw) else self.root / raw
        lexical = Path(os.path.normpath(candidate))
        real = Path(os.path.realpath(candidate))
        for label, path in (("path", lexical), ("resolved path", real)):
            if path != self.root and self.root not in path.parents:
                raise SandboxError(f"{label} escapes the working directory: {raw}")
        if not allow_secret:
            for path in (lexical, real):
                reason = secret_reason(path.relative_to(self.root))
                if reason:
                    raise SandboxError(f"access denied: {reason}")
        if must_exist and not real.exists():
            raise SandboxError(f"no such file or directory: {raw}")
        return real

    def resolve_lexical_no_follow(self, raw: str) -> Path:
        """For writes: the final component must not be a symlink (prevents write-through escapes)."""
        real = self.resolve(raw, must_exist=False)
        candidate = Path(raw) if os.path.isabs(raw) else self.root / raw
        if os.path.islink(candidate):
            raise SandboxError(f"refusing to write through a symlink: {raw}")
        return real


# ---- redaction ----------------------------------------------------------------------------------
_EXTRA_REDACTIONS = (
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*(?:bearer|basic|token)\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:[\w.-]*)(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|auth[_-]?token|client[_-]?secret|"
                r"private[_-]?key|token)[\w-]*\s*[=:]\s*)(?!\[)[^\s'\",;]{4,}"), r"\1[REDACTED]"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[AWS_KEY_REDACTED]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "[TOKEN_REDACTED]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), "[TOKEN_REDACTED]"),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"), "[JWT_REDACTED]"),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]{3,}@"), r"\1[REDACTED]@"),
)


def redact(text: str) -> str:
    text = redact_text(text) or ""
    for pattern, replacement in _EXTRA_REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


# ---- environment --------------------------------------------------------------------------------
ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "VIRTUAL_ENV", "TZ", "SYSTEMROOT",
                 "PYTHONPATH", "NODE_PATH", "CARGO_HOME", "RUSTUP_HOME", "GOPATH", "GOCACHE", "HOME")


def build_env(extra: Mapping[str, str] | None = None, *, allow_network: bool = False,
              base: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base is None else base
    env = {k: source[k] for k in ENV_ALLOWLIST if k in source}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull, "CI": "1", "NO_COLOR": "1", "PYTHONUNBUFFERED": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1", "NPM_CONFIG_UPDATE_NOTIFIER": "false", "GIT_PAGER": "cat"})
    if not allow_network:
        blackhole = "http://127.0.0.1:9"
        env.update({"HTTP_PROXY": blackhole, "HTTPS_PROXY": blackhole, "ALL_PROXY": blackhole,
                    "http_proxy": blackhole, "https_proxy": blackhole, "all_proxy": blackhole,
                    "NO_PROXY": "", "no_proxy": "", "PIP_NO_INDEX": "1", "NPM_CONFIG_OFFLINE": "true",
                    "CARGO_NET_OFFLINE": "true", "GOPROXY": "off"})
    if extra:
        env.update({k: v for k, v in extra.items() if k not in {"PATH"} and isinstance(v, str)})
    return env


# ---- subprocess runner --------------------------------------------------------------------------
@dataclass(slots=True)
class ProcResult:
    argv: list[str]
    exit_code: int | None
    output: str
    total_bytes: int
    total_lines: int
    truncated: bool
    timed_out: bool
    duration: float
    pid: int | None = None


async def kill_process_group(pgid: int, *, grace: float = 1.0) -> None:
    """SIGTERM the whole group, then SIGKILL.  ``pgid`` is always a group *we* created (setsid)."""
    if pgid <= 1 or pgid == os.getpgrp():
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return
        if sig is signal.SIGTERM:
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline:
                try:
                    os.killpg(pgid, 0)
                except (ProcessLookupError, PermissionError):
                    return
                await asyncio.sleep(0.02)


async def run_argv(argv: list[str], *, cwd: Path, limits: ExecLimits, env: Mapping[str, str],
                   stdin_data: bytes | None = None, timeout: float | None = None,
                   ceiling: PermissionLevel = PermissionLevel.SAFE_EXECUTE) -> ProcResult:
    """Run ``argv`` (never a shell) with output caps and a hard timeout; kills the process group."""
    assert_argv_allowed(argv, ceiling)
    limit = timeout if timeout is not None else limits.timeout
    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd), env=dict(env), stdin=asyncio.subprocess.PIPE if stdin_data is not None
            else asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True, limit=1 << 20)
    except FileNotFoundError as exc:
        raise ToolError(f"executable not found: {argv[0]}") from exc
    except OSError as exc:
        raise ToolError(f"cannot start {argv[0]}: {exc.strerror or exc}") from exc
    pgid = proc.pid
    cap = max(2_000, limits.max_output_bytes)
    head_cap, tail_cap = cap // 4, cap - cap // 4
    head = bytearray()
    tail = bytearray()
    counters = {"bytes": 0, "lines": 0}

    async def pump() -> None:
        assert proc.stdout is not None
        if stdin_data is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin_data)
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                proc.stdin.close()
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            counters["bytes"] += len(chunk)
            counters["lines"] += chunk.count(b"\n")
            if len(head) < head_cap:
                take = head_cap - len(head)
                head.extend(chunk[:take])
                chunk = chunk[take:]
            if chunk:
                tail.extend(chunk)
                if len(tail) > tail_cap * 2:
                    del tail[:len(tail) - tail_cap]
        await proc.wait()

    timed_out = False
    try:
        await asyncio.wait_for(pump(), timeout=limit)
    except TimeoutError:
        timed_out = True
        await kill_process_group(pgid)
        await proc.wait()
    except BaseException:  # cancellation or any error: never leave the group running
        await kill_process_group(pgid)
        try:
            await asyncio.wait_for(proc.wait(), 5)
        except Exception:  # noqa: BLE001 - best effort during teardown
            pass
        raise
    finally:
        if proc.returncode is None:
            await kill_process_group(pgid)
    if len(tail) > tail_cap:
        del tail[:len(tail) - tail_cap]
    total = counters["bytes"]
    truncated = total > len(head) + len(tail)
    text = head.decode("utf-8", "replace")
    if truncated:
        skipped = total - len(head) - len(tail)
        text += f"\n...[truncated {skipped} bytes; {total} bytes / {counters['lines']} lines total]...\n"
    text += tail.decode("utf-8", "replace")
    return ProcResult(list(argv), None if timed_out else proc.returncode, text, total, counters["lines"], truncated,
                      timed_out, time.monotonic() - started, proc.pid)

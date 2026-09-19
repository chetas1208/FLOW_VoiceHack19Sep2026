"""The executor's tool set.  Every subprocess tool takes argv lists only (never a shell)."""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..remote_models import PermissionLevel
from .base import Tool, ToolContext, ToolError, ToolResult, ToolSpec
from .sandbox import (
    GIT_SECRET_PATHSPECS,
    IGNORED_DIRS,
    ProcResult,
    Sandbox,
    SandboxError,
    build_env,
    is_secret_name,
    redact,
    run_argv,
    secret_reason,
)

AUTH_KEYWORDS = ("auth", "oauth", "jwt", "jose", "passlib", "bcrypt", "argon2", "saml", "oidc", "openid", "login",
                 "session", "passport", "keycloak", "okta", "cognito", "firebase", "clerk", "supabase", "itsdangerous",
                 "authlib", "cryptography", "security", "csrf", "sso", "2fa", "totp", "otp", "webauthn")
_PY_NAME = re.compile(r"^python(\d+(\.\d+)*)?$")
_KEYWORD_RE = re.compile(r"^[A-Za-z0-9_ ]{1,80}$")
_NODEID_TAIL = re.compile(r"^[\w.\[\]\-:,]{1,200}$")
_GLOB_RE = re.compile(r"^[\w*.?\-\[\]]{1,60}$")


# ---- helpers ------------------------------------------------------------------------------------
def _check_keys(tool: str, args: dict[str, Any], allowed: set[str], required: set[str] = frozenset()) -> None:
    if not isinstance(args, dict):
        raise ToolError(f"{tool}: args must be an object")
    unknown = set(args) - allowed
    if unknown:
        raise ToolError(f"{tool}: unknown argument(s) {sorted(unknown)}")
    missing = required - set(args)
    if missing:
        raise ToolError(f"{tool}: missing argument(s) {sorted(missing)}")


def _int(tool: str, args: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    value = args.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ToolError(f"{tool}: {key} must be an integer in [{lo}, {hi}]")
    return value


def _str(tool: str, args: dict[str, Any], key: str, default: str | None = None, max_len: int = 500) -> str | None:
    value = args.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > max_len or "\x00" in value:
        raise ToolError(f"{tool}: {key} must be a string of at most {max_len} characters")
    return value


def _bool(tool: str, args: dict[str, Any], key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ToolError(f"{tool}: {key} must be true or false")
    return value


def rel_arg(rel: str) -> str:
    """A relative path safe to hand to a CLI: never starts with '-'."""
    return rel if rel == "." or rel.startswith("./") else f"./{rel}"


def _is_binary(sample: bytes) -> bool:
    return b"\x00" in sample


def python_exe(root: Path) -> str:
    venv = root / ".venv" / "bin" / "python"
    if venv.exists() and os.access(venv, os.X_OK):
        return str(venv)
    exe = sys.executable or ""
    if exe and _PY_NAME.match(os.path.basename(exe)):
        return exe
    return shutil.which("python3") or "python3"


def _proc_output(pr: ProcResult) -> str:
    return redact(pr.output)


def _skip_dir(name: str) -> bool:
    return name in IGNORED_DIRS


class BaseTool:
    spec: ToolSpec
    allowed: set[str] = set()
    required: set[str] = set()

    def validate(self, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        _check_keys(self.spec.name, args, self.allowed, self.required)
        return dict(args)

    def describe(self, args: dict[str, Any]) -> str:
        shown = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
        return f"{self.spec.name}({shown})"

    def is_low_risk(self, args: dict[str, Any]) -> bool:
        return self.spec.level is PermissionLevel.READ_ONLY

    async def run(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:  # pragma: no cover - abstract
        raise NotImplementedError


def _short(value: Any, limit: int = 60) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ---- read-only: files ---------------------------------------------------------------------------
class ListFiles(BaseTool):
    spec = ToolSpec("list_files", PermissionLevel.READ_ONLY, "List files and directories inside the working directory")
    allowed = {"path", "recursive", "max_entries"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        path = _str("list_files", args, "path", ".") or "."
        real = Sandbox(ctx.workdir).resolve(path)
        if not real.is_dir():
            raise ToolError("list_files: path is not a directory")
        return {"path": Sandbox(ctx.workdir).relative(real), "recursive": _bool("list_files", args, "recursive"),
                "max_entries": _int("list_files", args, "max_entries", ctx.limits.max_list_entries, 1, 2000)}

    async def run(self, args, ctx):
        return await asyncio.to_thread(self._run, args, ctx)

    def _run(self, args, ctx) -> ToolResult:
        sb = Sandbox(ctx.workdir)
        base = sb.resolve(args["path"])
        lines: list[str] = []
        hidden = 0
        truncated = False
        stack = [base]
        while stack and not truncated:
            current = stack.pop()
            try:
                entries = sorted(os.scandir(current), key=lambda e: e.name)
            except OSError as exc:
                lines.append(f"{sb.relative(current)}: unreadable ({exc.strerror})")
                continue
            subdirs: list[Path] = []
            for entry in entries:
                if len(lines) >= args["max_entries"]:
                    truncated = True
                    break
                path = Path(entry.path)
                if secret_reason(Path(sb.relative(path))):
                    hidden += 1
                    continue
                if entry.is_symlink():
                    target = Path(os.path.realpath(path))
                    inside = target == sb.root or sb.root in target.parents
                    lines.append(f"{sb.relative(path)}@ -> {'inside workdir' if inside else '[outside workdir, not followed]'}")
                    continue
                if entry.is_dir(follow_symlinks=False):
                    lines.append(f"{sb.relative(path)}/")
                    if args["recursive"] and not _skip_dir(entry.name):
                        subdirs.append(path)
                else:
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        size = -1
                    lines.append(f"{sb.relative(path)} ({size} bytes)")
            stack.extend(reversed(subdirs))
        if hidden:
            lines.append(f"[{hidden} secret/credential entries hidden]")
        if truncated:
            lines.append(f"[listing truncated at {args['max_entries']} entries]")
        return ToolResult("list_files", True, f"Listed {len(lines)} entries under {args['path']}", "\n".join(lines),
                          facts={"entries": len(lines), "hidden_secrets": hidden, "truncated": truncated},
                          truncated=truncated)


class ReadFile(BaseTool):
    spec = ToolSpec("read_file", PermissionLevel.READ_ONLY, "Read a text file inside the working directory (size capped)")
    allowed = {"path", "start_line", "max_bytes"}
    required = {"path"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        sb = Sandbox(ctx.workdir)
        real = sb.resolve(_str("read_file", args, "path") or "")
        if not real.is_file():
            raise ToolError("read_file: not a regular file")
        return {"path": sb.relative(real), "start_line": _int("read_file", args, "start_line", 1, 1, 10_000_000),
                "max_bytes": _int("read_file", args, "max_bytes", ctx.limits.max_read_bytes, 1, ctx.limits.max_read_bytes)}

    async def run(self, args, ctx):
        return await asyncio.to_thread(self._run, args, ctx)

    def _run(self, args, ctx) -> ToolResult:
        real = Sandbox(ctx.workdir).resolve(args["path"])
        size = real.stat().st_size
        with open(real, "rb") as fh:
            raw = fh.read(args["max_bytes"] + 1)
        if _is_binary(raw[:8192]):
            raise ToolError("read_file: binary file refused")
        truncated = len(raw) > args["max_bytes"] or size > args["max_bytes"]
        text = raw[:args["max_bytes"]].decode("utf-8", "replace")
        lines = text.splitlines()
        start = args["start_line"]
        body = "\n".join(lines[start - 1:])
        return ToolResult("read_file", True, f"Read {args['path']} ({min(size, args['max_bytes'])} of {size} bytes)",
                          redact(body), facts={"path": args["path"], "size": size, "lines": len(lines), "truncated": truncated},
                          truncated=truncated, total_bytes=size)


class SearchText(BaseTool):
    spec = ToolSpec("search_text", PermissionLevel.READ_ONLY, "Literal text search across files inside the working directory")
    allowed = {"query", "path", "case_sensitive", "glob", "max_matches"}
    required = {"query"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        query = _str("search_text", args, "query", max_len=200) or ""
        if not query.strip():
            raise ToolError("search_text: query is empty")
        sb = Sandbox(ctx.workdir)
        real = sb.resolve(_str("search_text", args, "path", ".") or ".")
        glob = _str("search_text", args, "glob", None, 60)
        if glob is not None and not _GLOB_RE.match(glob):
            raise ToolError("search_text: invalid glob")
        return {"query": query, "path": sb.relative(real), "case_sensitive": _bool("search_text", args, "case_sensitive"),
                "glob": glob, "max_matches": _int("search_text", args, "max_matches", ctx.limits.max_search_matches, 1, 500)}

    async def run(self, args, ctx):
        return await asyncio.to_thread(self._run, args, ctx)

    def _run(self, args, ctx) -> ToolResult:
        import fnmatch
        sb = Sandbox(ctx.workdir)
        base = sb.resolve(args["path"])
        needle = args["query"] if args["case_sensitive"] else args["query"].lower()
        matches: list[str] = []
        files_with = set()
        scanned = 0
        deadline = time.monotonic() + 10
        truncated = False

        def files():
            if base.is_file():
                yield base
                return
            for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d) and not secret_reason(Path(d)))
                for name in sorted(filenames):
                    yield Path(dirpath) / name

        for path in files():
            if len(matches) >= args["max_matches"] or scanned >= 5000 or time.monotonic() > deadline:
                truncated = True
                break
            rel = sb.relative(path)
            if secret_reason(Path(rel)) or path.is_symlink():
                continue
            if args["glob"] and not fnmatch.fnmatch(path.name, args["glob"]):
                continue
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            if _is_binary(data[:8192]):
                continue
            scanned += 1
            for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                hay = line if args["case_sensitive"] else line.lower()
                if needle in hay:
                    matches.append(f"{rel}:{number}: {redact(line.strip())[:200]}")
                    files_with.add(rel)
                    if len(matches) >= args["max_matches"]:
                        break
        summary = f"{len(matches)} match(es) for {_short(args['query'], 40)!r} in {len(files_with)} file(s); {scanned} files scanned"
        return ToolResult("search_text", True, summary, "\n".join(matches),
                          facts={"matches": len(matches), "files": sorted(files_with)[:20], "scanned": scanned,
                                 "truncated": truncated}, truncated=truncated)


class ReadLogs(BaseTool):
    spec = ToolSpec("read_logs", PermissionLevel.READ_ONLY, "Tail a log file inside the working directory, or the previous step's output")
    allowed = {"path", "tail_lines", "grep", "source"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        source = _str("read_logs", args, "source", "file")
        if source not in {"file", "previous"}:
            raise ToolError("read_logs: source must be 'file' or 'previous'")
        out = {"source": source, "tail_lines": _int("read_logs", args, "tail_lines", 200, 1, 2000),
               "grep": _str("read_logs", args, "grep", None, 100)}
        if source == "file":
            sb = Sandbox(ctx.workdir)
            path = _str("read_logs", args, "path", None)
            real = sb.resolve(path) if path else _discover_log(sb)
            if not real.is_file():
                raise ToolError("read_logs: not a regular file")
            out["path"] = sb.relative(real)
        return out

    async def run(self, args, ctx):
        return await asyncio.to_thread(self._run, args, ctx)

    def _run(self, args, ctx) -> ToolResult:
        if args["source"] == "previous":
            text, name, size = ctx.previous_output, "previous step output", len(ctx.previous_output)
        else:
            real = Sandbox(ctx.workdir).resolve(args["path"])
            size = real.stat().st_size
            window = ctx.limits.max_read_bytes * 4
            with open(real, "rb") as fh:
                fh.seek(max(0, size - window))
                raw = fh.read(window)
            if _is_binary(raw[:8192]):
                raise ToolError("read_logs: binary file refused")
            text, name = raw.decode("utf-8", "replace"), args["path"]
        lines = text.splitlines()
        if args["grep"]:
            lines = [ln for ln in lines if args["grep"].lower() in ln.lower()]
        tail = lines[-args["tail_lines"]:]
        error_lines = sum(1 for ln in tail if re.search(r"\b(error|exception|traceback|fail(ed|ure)?|fatal)\b", ln, re.IGNORECASE))
        body = redact("\n".join(tail))
        return ToolResult("read_logs", True, f"Read last {len(tail)} lines of {name} ({error_lines} error-like)", body,
                          facts={"source": name, "lines": len(tail), "error_lines": error_lines, "size": size},
                          total_bytes=size)


def _discover_log(sb: Sandbox) -> Path:
    found: list[tuple[float, Path]] = []
    for dirpath, dirnames, filenames in os.walk(sb.root):
        depth = len(Path(dirpath).relative_to(sb.root).parts)
        dirnames[:] = [d for d in dirnames if not _skip_dir(d) and not secret_reason(Path(d))] if depth < 2 else []
        for name in filenames:
            if name.lower().endswith((".log", ".out")) and not is_secret_name(name):
                path = Path(dirpath) / name
                try:
                    found.append((path.stat().st_mtime, path))
                except OSError:
                    pass
    if not found:
        raise ToolError("read_logs: no log files found in the working directory; give a path")
    real = Path(os.path.realpath(max(found)[1]))
    return sb.resolve(sb.relative(real))


# ---- read-only: git -----------------------------------------------------------------------------
_GIT_BASE = ["git", "--no-pager", "-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}",
             "-c", "core.pager=cat", "-c", "protocol.allow=never"]


async def _git(ctx: ToolContext, *tail: str, timeout: float | None = None) -> ProcResult:
    return await run_argv([*_GIT_BASE, *tail], cwd=Sandbox(ctx.workdir).root, limits=ctx.limits,
                          env=build_env(ctx.env_extra, allow_network=False), timeout=timeout,
                          ceiling=PermissionLevel.READ_ONLY)


class GitStatus(BaseTool):
    spec = ToolSpec("git_status", PermissionLevel.READ_ONLY, "git status (branch and changed files)")

    async def run(self, args, ctx):
        pr = await _git(ctx, "status", "--porcelain=v1", "-b", "--untracked-files=normal")
        out = _proc_output(pr)
        if pr.exit_code != 0:
            first = out.strip().splitlines()[0] if out.strip() else "no output"
            return ToolResult("git_status", False, f"git status exit code {pr.exit_code}: {first}", out, pr.exit_code,
                              pr.argv, {"exit_code": pr.exit_code}, pr.truncated, pr.total_bytes, [], pr.duration, pr.timed_out)
        lines = out.splitlines()
        branch = lines[0][3:] if lines and lines[0].startswith("## ") else ""
        entries = [ln for ln in lines if not ln.startswith("## ")]
        untracked = sum(1 for ln in entries if ln.startswith("??"))
        staged = sum(1 for ln in entries if ln[:1] not in {" ", "?", ""})
        unstaged = sum(1 for ln in entries if len(ln) > 1 and ln[1] not in {" ", "?"})
        facts = {"branch": branch, "changed": len(entries), "staged": staged, "unstaged": unstaged, "untracked": untracked,
                 "paths": [ln[3:] for ln in entries[:30]], "exit_code": 0}
        summary = (f"git status exit code 0: branch {branch or '?'}; {len(entries)} changed path(s) "
                   f"({staged} staged, {unstaged} unstaged, {untracked} untracked)")
        return ToolResult("git_status", True, summary, out, 0, pr.argv, facts, pr.truncated, pr.total_bytes, [],
                          pr.duration)


class GitDiff(BaseTool):
    spec = ToolSpec("git_diff", PermissionLevel.READ_ONLY, "git diff (secret-named files excluded)")
    allowed = {"staged", "path", "stat_only"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        out = {"staged": _bool("git_diff", args, "staged"), "stat_only": _bool("git_diff", args, "stat_only")}
        path = _str("git_diff", args, "path", None)
        if path:
            sb = Sandbox(ctx.workdir)
            out["path"] = sb.relative(sb.resolve(path, must_exist=False))
        return out

    async def run(self, args, ctx):
        common = ["diff", "--no-ext-diff", "--no-textconv", "--no-color"] + (["--cached"] if args["staged"] else [])
        specs = ["--", rel_arg(args["path"])] if args.get("path") else ["--", ".", *GIT_SECRET_PATHSPECS]
        num = await _git(ctx, *common, "--numstat", *specs)
        if num.exit_code != 0:
            first = num.output.strip().splitlines()[0] if num.output.strip() else "no output"
            return ToolResult("git_diff", False, f"git diff exit code {num.exit_code}: {first}", redact(num.output),
                              num.exit_code, num.argv, {"exit_code": num.exit_code}, duration=num.duration)
        files = ins = dels = 0
        paths: list[str] = []
        for ln in num.output.splitlines():
            parts = ln.split("\t")
            if len(parts) == 3:
                files += 1
                ins += int(parts[0]) if parts[0].isdigit() else 0
                dels += int(parts[1]) if parts[1].isdigit() else 0
                paths.append(parts[2])
        body = ""
        pr = num
        truncated = False
        if not args["stat_only"] and files:
            pr = await _git(ctx, *common, *specs)
            body = redact(pr.output)
            truncated = pr.truncated
        summary = f"git diff exit code {pr.exit_code}: {files} file(s) changed, +{ins} -{dels}"
        return ToolResult("git_diff", pr.exit_code == 0, summary, body or redact(num.output), pr.exit_code, pr.argv,
                          {"files": files, "insertions": ins, "deletions": dels, "paths": paths[:30], "exit_code": pr.exit_code},
                          truncated, pr.total_bytes, [], pr.duration)


# ---- safe-execute: tests / linter ---------------------------------------------------------------
def detect_test_runner(root: Path) -> str | None:
    if (root / "package.json").is_file():
        try:
            pkg = json.loads((root / "package.json").read_text("utf-8", "replace"))
            if isinstance(pkg.get("scripts"), dict) and pkg["scripts"].get("test"):
                return "npm"
        except (OSError, ValueError):
            pass
    if any((root / n).exists() for n in ("pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "conftest.py")) \
            or (root / "tests").is_dir() or (root / "test").is_dir():
        return "pytest"
    if (root / "go.mod").is_file():
        return "go"
    if (root / "Cargo.toml").is_file():
        return "cargo"
    return None


def _node_pm(root: Path) -> str:
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    return "npm"


_PYTEST_SUMMARY = re.compile(r"(?m)^(?:=+ )?((?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|warnings?|deselected|rerun)(?:, )?)+)"
                             r"(?: in ([\d.]+)s)?")
_PYTEST_FAILED = re.compile(r"(?m)^(?:FAILED|ERROR) (\S+?)(?: - .*)?$")
_JEST_TESTS = re.compile(r"(?m)^Tests:\s+(.*)$")


def parse_test_output(runner: str, output: str) -> dict[str, Any]:
    facts: dict[str, Any] = {"runner": runner, "counts_parsed": False}
    if runner == "pytest":
        summaries = _PYTEST_SUMMARY.findall(output)
        if summaries:
            counts = {}
            for n, word in re.findall(r"(\d+) (\w+)", summaries[-1][0]):
                counts[word.rstrip("s") if word.startswith("error") else word] = int(n)
            facts.update(counts_parsed=True, passed=counts.get("passed", 0), failed=counts.get("failed", 0),
                         errors=counts.get("error", 0), skipped=counts.get("skipped", 0))
            if summaries[-1][1]:
                facts["duration_s"] = float(summaries[-1][1])
        elif re.search(r"no tests ran", output):
            facts.update(counts_parsed=True, passed=0, failed=0, errors=0, skipped=0, collected=0)
        failed = list(dict.fromkeys(_PYTEST_FAILED.findall(output)))
        facts["failed_tests"] = failed[:20]
        facts["failed_files"] = list(dict.fromkeys(f.split("::")[0] for f in failed))[:10]
        facts["failed_names"] = list(dict.fromkeys(f.split("::")[-1].split("[")[0] for f in failed if "::" in f))[:10]
    elif runner in {"npm", "pnpm", "yarn"}:
        m = _JEST_TESTS.search(output)
        if m:
            counts = {w: int(n) for n, w in re.findall(r"(\d+) (\w+)", m.group(1))}
            facts.update(counts_parsed=True, passed=counts.get("passed", 0), failed=counts.get("failed", 0),
                         errors=0, skipped=counts.get("skipped", 0))
        facts["failed_tests"] = list(dict.fromkeys(re.findall(r"(?m)^\s*●\s+(.+?)$", output)))[:20]
    elif runner == "go":
        ok = len(re.findall(r"(?m)^ok\s", output))
        bad = len(re.findall(r"(?m)^FAIL\s", output)) + len(re.findall(r"(?m)^--- FAIL", output))
        facts.update(counts_parsed=bool(ok or bad), passed=ok, failed=bad, errors=0, skipped=0,
                     failed_tests=re.findall(r"(?m)^--- FAIL: (\S+)", output)[:20])
    elif runner == "cargo":
        m = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", output)
        if m:
            facts.update(counts_parsed=True, passed=sum(int(a) for a, _, _ in m), failed=sum(int(b) for _, b, _ in m),
                         errors=0, skipped=sum(int(c) for _, _, c in m))
        facts["failed_tests"] = re.findall(r"(?m)^test (\S+) \.\.\. FAILED", output)[:20]
    return facts


def _counts_text(facts: dict[str, Any]) -> str:
    if not facts.get("counts_parsed"):
        return "no test counts parsed from output"
    parts = [f"{facts[k]} {label}" for k, label in (("failed", "failed"), ("errors", "errors"), ("passed", "passed"),
                                                    ("skipped", "skipped")) if facts.get(k)]
    return ", ".join(parts) or "0 tests ran"


class RunTests(BaseTool):
    spec = ToolSpec("run_tests", PermissionLevel.SAFE_EXECUTE, "Run the project's tests (auto-detected runner, argv allowlist)")
    allowed = {"path", "keyword", "runner"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        sb = Sandbox(ctx.workdir)
        runner = _str("run_tests", args, "runner", None, 20)
        detected = detect_test_runner(sb.root)
        if runner not in {None, "auto", "pytest", "npm", "go", "cargo"}:
            raise ToolError("run_tests: runner must be one of auto, pytest, npm, go, cargo")
        runner = detected if runner in {None, "auto"} else runner
        if runner is None:
            raise ToolError("run_tests: could not detect a test runner (pytest, npm test, go test, cargo test)")
        out: dict[str, Any] = {"runner": runner}
        path = _str("run_tests", args, "path", None)
        if path:
            head, sep, tail = path.partition("::")
            if head.startswith("-") or (sep and not _NODEID_TAIL.match(tail)):
                raise ToolError("run_tests: path must be a relative test path (optionally ::node_id)")
            out["path"] = sb.relative(sb.resolve(head)) + (sep + tail)
        keyword = _str("run_tests", args, "keyword", None, 80)
        if keyword is not None:
            if not _KEYWORD_RE.match(keyword) or keyword.strip().startswith("-"):
                raise ToolError("run_tests: keyword may only contain letters, digits, underscore and spaces")
            out["keyword"] = keyword.strip()
        return out

    def is_low_risk(self, args):
        return bool(args.get("path") or args.get("keyword"))

    def describe(self, args):
        target = args.get("path") or (f"-k {args['keyword']}" if args.get("keyword") else "entire suite")
        return f"run_tests[{args.get('runner')}] {target}"

    def build_argv(self, args: dict[str, Any], root: Path) -> list[str]:
        runner = args["runner"]
        path, keyword = args.get("path"), args.get("keyword")
        if runner == "pytest":
            argv = [python_exe(root), "-m", "pytest", "-q", "--no-header", "-rfE", "--tb=short", "-p", "no:cacheprovider",
                    "--color=no"]
            if keyword:
                argv += ["-k", keyword]
            if path:
                head, sep, tail = path.partition("::")
                argv.append(rel_arg(head) + sep + tail)
            return argv
        if runner == "npm":
            argv = [_node_pm(root), "test", "--silent"] if _node_pm(root) == "npm" else [_node_pm(root), "test"]
            if path:
                argv += ["--", rel_arg(path)]
            return argv
        if runner == "go":
            return ["go", "test", (rel_arg(str(Path(path).parent)) + "/...") if path else "./..."]
        return ["cargo", "test", "--offline", "-q", *([keyword] if keyword else [])]

    async def run(self, args, ctx):
        root = Sandbox(ctx.workdir).root
        argv = self.build_argv(args, root)
        pr = await run_argv(argv, cwd=root, limits=ctx.limits, env=build_env(ctx.env_extra, allow_network=ctx.allow_network),
                            timeout=ctx.limits.test_timeout)
        facts = parse_test_output(args["runner"], pr.output)
        facts["exit_code"] = pr.exit_code
        facts["command"] = " ".join(argv)
        if pr.timed_out:
            summary = f"{args['runner']} timed out after {ctx.limits.test_timeout:.0f}s (killed)"
        else:
            summary = f"{args['runner']} exit code {pr.exit_code}: {_counts_text(facts)}"
        ok = pr.exit_code == 0 and not pr.timed_out
        return ToolResult("run_tests", ok, summary, _proc_output(pr), pr.exit_code, argv, facts, pr.truncated, pr.total_bytes,
                          [], pr.duration, pr.timed_out)


class RunLinter(BaseTool):
    spec = ToolSpec("run_linter", PermissionLevel.SAFE_EXECUTE, "Run the project's linter without auto-fix")
    allowed = {"path"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        sb = Sandbox(ctx.workdir)
        path = _str("run_linter", args, "path", ".") or "."
        return {"path": sb.relative(sb.resolve(path))}

    def is_low_risk(self, args):
        return True

    def build_argv(self, args: dict[str, Any], root: Path) -> tuple[str, list[str]]:
        target = rel_arg(args["path"])
        local = root / ".venv" / "bin" / "ruff"
        ruff = str(local) if local.exists() and os.access(local, os.X_OK) else shutil.which("ruff")
        is_py = any((root / n).exists() for n in ("pyproject.toml", "setup.cfg", "ruff.toml", "setup.py", "requirements.txt"))
        if is_py and ruff:
            return "ruff", [ruff, "check", "--no-fix", "--no-cache", "--output-format=concise", target]
        flake = shutil.which("flake8")
        if is_py and flake:
            return "flake8", [flake, target]
        if (root / "node_modules" / ".bin" / "eslint").exists():
            return "eslint", ["npx", "--no-install", "eslint", target]
        raise ToolError("run_linter: no supported linter found (looked for ruff, flake8, local eslint)")

    async def run(self, args, ctx):
        root = Sandbox(ctx.workdir).root
        name, argv = self.build_argv(args, root)
        pr = await run_argv(argv, cwd=root, limits=ctx.limits, env=build_env(ctx.env_extra, allow_network=False))
        text = pr.output
        issues = len(re.findall(r"(?m)^\S+?:\d+(?::\d+)?:? ", text))
        m = re.search(r"Found (\d+) errors?", text)
        if m:
            issues = int(m.group(1))
        files = list(dict.fromkeys(re.findall(r"(?m)^(\S+?):\d+(?::\d+)?:? ", text)))[:10]
        facts = {"linter": name, "issues": issues, "files_with_issues": files, "exit_code": pr.exit_code,
                 "command": " ".join(argv)}
        if pr.timed_out:
            summary = f"{name} timed out (killed)"
        elif pr.exit_code == 0:
            summary = f"{name} exit code 0: no issues reported"
        else:
            summary = f"{name} exit code {pr.exit_code}: {issues} issue(s) reported"
        return ToolResult("run_linter", pr.exit_code == 0 and not pr.timed_out, summary, _proc_output(pr), pr.exit_code, argv,
                          facts, pr.truncated, pr.total_bytes, [], pr.duration, pr.timed_out)


# ---- read-only: package metadata ----------------------------------------------------------------
_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*([^;#]*)")


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name.lower())


def _parse_req(text: str) -> tuple[str, str] | None:
    m = _REQ.match(text)
    if not m or text.lstrip().startswith(("-", "#", "git+", "http")):
        return None
    spec = m.group(2).strip().replace(" ", "")
    return m.group(1), spec


class InspectPackageMetadata(BaseTool):
    spec = ToolSpec("inspect_package_metadata", PermissionLevel.READ_ONLY,
                    "List declared (and locked) dependency versions from pyproject/requirements/package.json/lockfiles")
    allowed = {"keywords"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        kws = args.get("keywords", [])
        if not isinstance(kws, list) or len(kws) > 40 or not all(isinstance(k, str) and 1 <= len(k) <= 40 for k in kws):
            raise ToolError("inspect_package_metadata: keywords must be a list of short strings")
        return {"keywords": [k.lower() for k in kws]}

    async def run(self, args, ctx):
        return await asyncio.to_thread(self._run, args, ctx)

    def _candidates(self, sb: Sandbox) -> list[Path]:
        names = {"pyproject.toml", "package.json", "package-lock.json", "poetry.lock", "uv.lock", "Pipfile", "yarn.lock",
                 "pnpm-lock.yaml"}
        found: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(sb.root):
            depth = len(Path(dirpath).relative_to(sb.root).parts)
            dirnames[:] = [d for d in sorted(dirnames) if not _skip_dir(d) and not secret_reason(Path(d))] if depth < 2 else []
            for name in sorted(filenames):
                if name in names or (name.startswith("requirements") and name.endswith(".txt")):
                    found.append(Path(dirpath) / name)
        return found[:30]

    def _run(self, args, ctx) -> ToolResult:
        sb = Sandbox(ctx.workdir)
        deps: dict[tuple[str, str], dict[str, Any]] = {}
        locked: dict[str, str] = {}
        checked: list[str] = []
        unparsed: list[str] = []

        def declare(name: str, spec: str, rel: str, kind: str) -> None:
            deps.setdefault((_norm(name), rel), {"name": name, "declared": spec or "unpinned", "file": rel, "kind": kind})

        for path in self._candidates(sb):
            try:
                real = sb.resolve(sb.relative(path))
                rel = sb.relative(real)
                text = real.read_text("utf-8", "replace") if real.stat().st_size < 5_000_000 else ""
            except (SandboxError, OSError):
                continue
            checked.append(rel)
            name = path.name
            try:
                if name == "pyproject.toml":
                    self._pyproject(tomllib.loads(text), rel, declare)
                elif name.startswith("requirements"):
                    for line in text.splitlines():
                        parsed = _parse_req(line)
                        if parsed:
                            declare(parsed[0], parsed[1], rel, "runtime")
                elif name == "package.json":
                    pkg = json.loads(text)
                    for section, kind in (("dependencies", "runtime"), ("devDependencies", "dev"),
                                          ("peerDependencies", "peer"), ("optionalDependencies", "optional")):
                        for dep, spec in (pkg.get(section) or {}).items():
                            declare(dep, str(spec), rel, kind)
                elif name == "package-lock.json":
                    lock = json.loads(text)
                    for key, meta in (lock.get("packages") or {}).items():
                        if key.startswith("node_modules/") and isinstance(meta, dict) and meta.get("version"):
                            locked[_norm(key.split("node_modules/")[-1])] = str(meta["version"])
                    for dep, meta in (lock.get("dependencies") or {}).items():
                        if isinstance(meta, dict) and meta.get("version"):
                            locked.setdefault(_norm(dep), str(meta["version"]))
                elif name in {"poetry.lock", "uv.lock"}:
                    for pkg in tomllib.loads(text).get("package", []):
                        if pkg.get("name") and pkg.get("version"):
                            locked[_norm(pkg["name"])] = str(pkg["version"])
                elif name == "Pipfile":
                    for section, kind in (("packages", "runtime"), ("dev-packages", "dev")):
                        for dep, spec in (tomllib.loads(text).get(section) or {}).items():
                            declare(dep, spec if isinstance(spec, str) and spec != "*" else "", rel, kind)
                else:
                    unparsed.append(rel)
            except (ValueError, tomllib.TOMLDecodeError, AttributeError, TypeError):
                unparsed.append(rel)
        keywords = args["keywords"]
        rows = []
        for (norm, _), row in sorted(deps.items()):
            if keywords and not any(k in norm for k in keywords):
                continue
            version = locked.get(norm)
            flags = []
            if row["declared"] == "unpinned":
                flags.append("unpinned")
            elif ">=" in row["declared"] and "<" not in row["declared"] and "," not in row["declared"]:
                flags.append("no upper bound")
            rows.append({**row, "locked": version, "flags": flags})
        rows = rows[:100]
        lines = [f"{r['name']}  declared: {r['declared']}  locked: {r['locked'] or 'n/a'}  ({r['kind']}, {r['file']})"
                 + (f"  [{', '.join(r['flags'])}]" if r["flags"] else "") for r in rows]
        subject = "auth-related " if keywords else ""
        summary = (f"Found {len(rows)} {subject}dependenc{'y' if len(rows) == 1 else 'ies'} in {len(checked)} file(s); "
                   "declared vs locked versions only - latest versions were not checked (no network)")
        return ToolResult("inspect_package_metadata", True, summary, "\n".join(lines),
                          facts={"dependencies": rows[:40], "count": len(rows), "files_checked": checked,
                                 "unparsed_files": unparsed, "keywords": keywords, "latest_checked": False})

    @staticmethod
    def _pyproject(data: dict[str, Any], rel: str, declare: Callable[[str, str, str, str], None]) -> None:
        project = data.get("project") or {}
        for req in project.get("dependencies") or []:
            parsed = _parse_req(req)
            if parsed:
                declare(parsed[0], parsed[1], rel, "runtime")
        for extra, reqs in (project.get("optional-dependencies") or {}).items():
            for req in reqs:
                parsed = _parse_req(req)
                if parsed:
                    declare(parsed[0], parsed[1], rel, f"optional:{extra}")
        for group, reqs in (data.get("dependency-groups") or {}).items():
            for req in reqs:
                parsed = _parse_req(req) if isinstance(req, str) else None
                if parsed:
                    declare(parsed[0], parsed[1], rel, f"group:{group}")
        poetry = (data.get("tool") or {}).get("poetry") or {}
        for section, kind in (("dependencies", "runtime"), ("dev-dependencies", "dev")):
            for dep, spec in (poetry.get(section) or {}).items():
                if dep.lower() != "python":
                    declare(dep, spec if isinstance(spec, str) else str((spec or {}).get("version", "")), rel, kind)
        for build in (data.get("build-system") or {}).get("requires") or []:
            parsed = _parse_req(build)
            if parsed:
                declare(parsed[0], parsed[1], rel, "build")


# ---- write tools (WRITE_PROJECT) ----------------------------------------------------------------
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


class WriteFile(BaseTool):
    spec = ToolSpec("write_file", PermissionLevel.WRITE_PROJECT, "Create or overwrite one file inside the working directory")
    allowed = {"path", "content"}
    required = {"path", "content"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        content = args["content"]
        if not isinstance(content, str) or "\x00" in content:
            raise ToolError("write_file: content must be text")
        if len(content.encode("utf-8")) > ctx.limits.max_write_bytes:
            raise ToolError(f"write_file: content larger than {ctx.limits.max_write_bytes} bytes")
        sb = Sandbox(ctx.workdir)
        real = sb.resolve_lexical_no_follow(_str("write_file", args, "path") or "")
        if real == sb.root or real.is_dir():
            raise ToolError("write_file: path is a directory")
        return {"path": sb.relative(real), "content": content}

    def describe(self, args):
        return f"write_file {args.get('path')} ({len(args.get('content', ''))} chars)"

    def is_low_risk(self, args):
        return False

    async def run(self, args, ctx):
        return await asyncio.to_thread(self._run, args, ctx)

    def _run(self, args, ctx) -> ToolResult:
        sb = Sandbox(ctx.workdir)
        target = sb.resolve_lexical_no_follow(args["path"])
        before = target.read_bytes() if target.is_file() else None
        new = args["content"].encode("utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / f".flow-tmp-{secrets.token_hex(6)}"
        try:
            tmp.write_bytes(new)
            if before is not None:
                os.chmod(tmp, target.stat().st_mode & 0o777)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()
        old_lines = (before or b"").decode("utf-8", "replace").splitlines()
        new_lines = args["content"].splitlines()
        diff = list(difflib.unified_diff(old_lines, new_lines, f"a/{args['path']}", f"b/{args['path']}", lineterm="", n=1))
        added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
        removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
        state = "created" if before is None else "modified"
        return ToolResult("write_file", True, f"{state} {args['path']} (+{added} -{removed})", redact("\n".join(diff[:80])),
                          facts={"path": args["path"], "created": before is None, "added": added, "removed": removed,
                                 "sha256_before": _sha(before) if before is not None else None, "sha256_after": _sha(new)},
                          files_touched=[args["path"]])


_PATCH_FILE = re.compile(r"(?m)^(?:---|\+\+\+) (?:[ab]/)?(\S.*?)(?:\t.*)?$")


class ApplyPatch(BaseTool):
    spec = ToolSpec("apply_patch", PermissionLevel.WRITE_PROJECT, "Apply a unified diff to files inside the working directory")
    allowed = {"patch"}
    required = {"patch"}

    def validate(self, args, ctx):
        super().validate(args, ctx)
        patch = args["patch"]
        if not isinstance(patch, str) or "\x00" in patch or not patch.strip():
            raise ToolError("apply_patch: patch must be non-empty text")
        if len(patch.encode("utf-8")) > ctx.limits.max_write_bytes:
            raise ToolError("apply_patch: patch too large")
        for banned in ("GIT binary patch", "\nrename from ", "\nrename to ", "\ncopy from ", "\ncopy to ",
                       "\ndeleted file mode", "\nnew file mode 120000", "\nold mode ", "\nnew mode ", "\nsimilarity index"):
            if banned in "\n" + patch:
                raise ToolError(f"apply_patch: unsupported patch content ({banned.strip()})")
        sb = Sandbox(ctx.workdir)
        paths = []
        for m in _PATCH_FILE.finditer(patch):
            raw = m.group(1).strip()
            if raw == "/dev/null":
                if m.group(0).startswith("+++"):
                    raise ToolError("apply_patch: deleting files is not permitted")
                continue
            paths.append(sb.relative(sb.resolve_lexical_no_follow(raw)))
        paths = list(dict.fromkeys(paths))
        if not paths:
            raise ToolError("apply_patch: no file headers found (expected a unified diff)")
        return {"patch": patch if patch.endswith("\n") else patch + "\n", "paths": paths}

    def describe(self, args):
        return f"apply_patch to {', '.join(args.get('paths', []))}"

    def is_low_risk(self, args):
        return False

    async def run(self, args, ctx):
        sb = Sandbox(ctx.workdir)
        data = args["patch"].encode("utf-8")
        before = {p: _sha((sb.root / p).read_bytes()) if (sb.root / p).is_file() else None for p in args["paths"]}
        env = build_env(ctx.env_extra, allow_network=False)
        base = ["git", "-c", f"core.hooksPath={os.devnull}", "apply", "--whitespace=nowarn"]
        check = await run_argv([*base, "--check", "-"], cwd=sb.root, limits=ctx.limits, env=env, stdin_data=data,
                               ceiling=PermissionLevel.READ_ONLY)
        if check.exit_code != 0:
            return ToolResult("apply_patch", False, f"patch does not apply (git apply --check exit code {check.exit_code})",
                              redact(check.output), check.exit_code, check.argv, {"exit_code": check.exit_code}, duration=check.duration)
        stat = await run_argv([*base, "--numstat", "-"], cwd=sb.root, limits=ctx.limits, env=env, stdin_data=data,
                              ceiling=PermissionLevel.READ_ONLY)
        pr = await run_argv([*base, "-"], cwd=sb.root, limits=ctx.limits, env=env, stdin_data=data,
                            ceiling=PermissionLevel.WRITE_PROJECT)
        if pr.exit_code != 0:
            return ToolResult("apply_patch", False, f"git apply exit code {pr.exit_code}", redact(pr.output), pr.exit_code,
                              pr.argv, {"exit_code": pr.exit_code}, duration=pr.duration)
        touched = []
        for p in args["paths"]:
            after = _sha((sb.root / p).read_bytes()) if (sb.root / p).is_file() else None
            if after != before[p]:
                touched.append(p)
        ins = dels = 0
        for ln in stat.output.splitlines():
            parts = ln.split("\t")
            if len(parts) == 3:
                ins += int(parts[0]) if parts[0].isdigit() else 0
                dels += int(parts[1]) if parts[1].isdigit() else 0
        if not touched:
            return ToolResult("apply_patch", False, "git apply exit code 0 but no target file changed", "", 0, pr.argv,
                              {"exit_code": 0}, duration=pr.duration)
        return ToolResult("apply_patch", True, f"git apply exit code 0: {len(touched)} file(s) changed, +{ins} -{dels}",
                          redact(stat.output), 0, pr.argv, {"files": touched, "insertions": ins, "deletions": dels, "exit_code": 0},
                          files_touched=touched, duration=pr.duration)


def default_tools() -> dict[str, Tool]:
    tools: list[Tool] = [ListFiles(), ReadFile(), SearchText(), GitStatus(), GitDiff(), RunTests(), RunLinter(),
                         InspectPackageMetadata(), ReadLogs(), WriteFile(), ApplyPatch()]
    return {t.spec.name: t for t in tools}

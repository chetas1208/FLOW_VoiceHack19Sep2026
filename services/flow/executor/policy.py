"""Permission decisions and command classification.

Levels are ordered ``READ_ONLY < SAFE_EXECUTE < WRITE_PROJECT < EXTERNAL_NETWORK < DESTRUCTIVE``.
A task carries the *highest level it was granted*; the session policy then decides, per step,
whether to run it, ask the user, or refuse.  DESTRUCTIVE is refused unconditionally.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..remote_models import PermissionLevel, PermissionPolicy
from .base import Tool, ToolError

LEVEL_RANK = {PermissionLevel.READ_ONLY: 0, PermissionLevel.SAFE_EXECUTE: 1, PermissionLevel.WRITE_PROJECT: 2,
              PermissionLevel.EXTERNAL_NETWORK: 3, PermissionLevel.DESTRUCTIVE: 4}


def rank(level: PermissionLevel) -> int:
    return LEVEL_RANK[level]


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: Decision
    level: PermissionLevel
    reason: str


class PermissionEngine:
    """Maps (session policy, task grant, tool, args) to allow / ask / deny."""

    def __init__(self, policy: PermissionPolicy = PermissionPolicy.SAFE_AUTO,
                 granted: PermissionLevel = PermissionLevel.SAFE_EXECUTE) -> None:
        self.policy = policy
        self.granted = granted

    def decide(self, tool: Tool, args: dict[str, Any]) -> PolicyDecision:
        level = tool.spec.level
        if level is PermissionLevel.DESTRUCTIVE:
            return PolicyDecision(Decision.DENY, level, "destructive actions are never permitted")
        if rank(level) > rank(self.granted):
            return PolicyDecision(Decision.DENY, level,
                                  f"task was not granted {level.value} (granted: {self.granted.value})")
        if self.policy is PermissionPolicy.READ_ONLY:
            if level is PermissionLevel.READ_ONLY:
                return PolicyDecision(Decision.ALLOW, level, "read-only policy: read tool")
            return PolicyDecision(Decision.DENY, level, f"read-only policy forbids {level.value} tools")
        if level is PermissionLevel.READ_ONLY:
            return PolicyDecision(Decision.ALLOW, level, "read tool")
        if level is PermissionLevel.EXTERNAL_NETWORK:
            return PolicyDecision(Decision.ASK, level, "network access always needs approval")
        if self.policy is PermissionPolicy.SAFE_AUTO:
            if level is PermissionLevel.SAFE_EXECUTE and tool.is_low_risk(args):
                return PolicyDecision(Decision.ALLOW, level, "safe_auto: classified low-risk")
            return PolicyDecision(Decision.ASK, level, f"safe_auto does not auto-approve this {level.value} action")
        return PolicyDecision(Decision.ASK, level, f"manual policy: {level.value} action needs approval")


# ---- command classification --------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Classification:
    level: PermissionLevel | None  # None = not on the allowlist (treated as denied)
    reason: str


_PY = re.compile(r"^python(\d+(\.\d+)*)?$")
_SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh", "csh", "tcsh", "eval", "exec", "source", "xargs", "nohup", "watch"}
_ALWAYS_DESTRUCTIVE = {"rm", "rmdir", "unlink", "dd", "mkfs", "shred", "truncate", "chmod", "chown", "chgrp", "kill",
                       "killall", "pkill", "sudo", "su", "doas", "shutdown", "reboot", "halt", "mv", "ln", "crontab",
                       "launchctl", "systemctl", "service", "docker", "podman", "kubectl", "helm", "terraform",
                       "ansible", "brew", "apt", "apt-get", "yum", "dnf", "diskutil", "mount", "umount", "osascript",
                       "defaults", "security", "gh", "fly", "heroku", "vercel", "netlify", "gcloud", "aws", "az"}
_NETWORK = {"curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "ncat", "netcat", "telnet", "ftp", "ping", "dig",
            "nslookup", "http", "https", "httpie", "socat"}
_WRITE = {"cp", "mkdir", "touch", "tee", "install", "sed", "ed", "patch", "tar", "zip", "unzip"}
_READ = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "find", "pwd", "echo", "stat", "file", "sort", "uniq", "diff",
         "tree", "du", "df", "which", "date", "whoami", "id"}
_GIT_READ = {"status", "diff", "log", "show", "rev-parse", "ls-files", "blame", "shortlog", "describe", "grep",
             "cat-file", "ls-tree", "rev-list", "diff-tree", "show-ref", "for-each-ref"}
_GIT_NET = {"fetch", "pull", "clone", "ls-remote", "remote", "submodule"}
_PKG_NET_VERBS = {"install", "i", "add", "update", "upgrade", "ci", "remove", "uninstall", "rm", "publish", "download",
                  "self-update", "up", "sync", "lock"}
_NODE_PMS = {"npm", "pnpm", "yarn", "bun"}
_SHELL_OPS = ("|", ";", "&&", "||", "&", ">", ">>", "<", "`", "$(")


def _base(arg: str) -> str:
    return os.path.basename(arg)


def classify_argv(argv: list[str]) -> Classification:
    """Classify one already-tokenised command.  Never involves a shell."""
    if not argv or not all(isinstance(a, str) for a in argv):
        return Classification(None, "empty or non-string argv")
    prog = _base(argv[0])
    rest = argv[1:]
    if "\x00" in "".join(argv):
        return Classification(PermissionLevel.DESTRUCTIVE, "NUL byte in argv")
    if prog in _SHELLS:
        return Classification(PermissionLevel.DESTRUCTIVE, f"{prog}: shell / arbitrary command execution is not permitted")
    if prog == "env":
        return Classification(PermissionLevel.DESTRUCTIVE, "env: command wrapper is not permitted")
    if prog in _ALWAYS_DESTRUCTIVE:
        return Classification(PermissionLevel.DESTRUCTIVE, f"{prog}: destructive or system-changing command")
    if prog in _NETWORK:
        return Classification(PermissionLevel.EXTERNAL_NETWORK, f"{prog}: network access")
    if prog in _WRITE:
        return Classification(PermissionLevel.WRITE_PROJECT, f"{prog}: modifies files")
    if prog in _READ:
        if prog == "find" and any(a in {"-delete", "-exec", "-execdir", "-ok", "-fprint"} for a in rest):
            return Classification(PermissionLevel.DESTRUCTIVE, "find with -delete/-exec")
        return Classification(PermissionLevel.READ_ONLY, f"{prog}: read-only")
    if prog == "git":
        return _classify_git(rest)
    if _PY.match(prog) or prog == "python":
        return _classify_python(rest)
    if prog in _NODE_PMS:
        return _classify_node_pm(prog, rest)
    if prog in {"npx", "pnpx", "bunx"}:
        return _classify_npx(rest)
    if prog == "pip" or prog == "pip3" or prog == "uv" or prog == "poetry" or prog == "pipx":
        verb = next((a for a in rest if not a.startswith("-")), "")
        if verb in {"list", "show", "freeze", "check", "tree", "--version"}:
            return Classification(PermissionLevel.READ_ONLY, f"{prog} {verb}: read-only")
        return Classification(PermissionLevel.EXTERNAL_NETWORK, f"{prog} {verb or ''}: package changes / network")
    if prog in {"pytest", "py.test"}:
        return Classification(PermissionLevel.SAFE_EXECUTE, "pytest run")
    if prog in {"ruff", "flake8", "pyflakes", "mypy", "pylint", "eslint"}:
        if any(a in {"--fix", "--fix-only", "--unsafe-fixes", "--write"} or a.startswith("--fix") for a in rest):
            return Classification(PermissionLevel.WRITE_PROJECT, f"{prog} with fixes modifies files")
        return Classification(PermissionLevel.SAFE_EXECUTE, f"{prog} lint (no fixes)")
    if prog == "go" and rest[:1] in (["test"], ["vet"]):
        return Classification(PermissionLevel.SAFE_EXECUTE, "go test/vet")
    if prog == "cargo" and rest[:1] in (["test"], ["clippy"], ["check"]):
        return Classification(PermissionLevel.SAFE_EXECUTE, f"cargo {rest[0]}")
    return Classification(None, f"{prog}: not on the executor allowlist")


def _classify_git(rest: list[str]) -> Classification:
    args = list(rest)
    i = 0
    while i < len(args) and args[i].startswith("-"):  # global options: -c k=v, --no-pager, -C dir
        if args[i] in {"-c", "-C", "--git-dir", "--work-tree"}:
            i += 1
        i += 1
    sub = args[i] if i < len(args) else ""
    tail = args[i + 1:]
    if sub in {"push", "commit", "reset", "clean", "checkout", "restore", "rebase", "merge", "cherry-pick", "revert",
               "rm", "mv", "tag", "stash", "switch", "worktree", "gc", "prune", "reflog", "filter-branch", "am",
               "update-ref", "config", "init", "add", "notes", "bisect"}:
        return Classification(PermissionLevel.DESTRUCTIVE, f"git {sub}: changes repository state (never permitted)")
    if sub in _GIT_NET:
        return Classification(PermissionLevel.EXTERNAL_NETWORK, f"git {sub}: network access")
    if sub == "branch":
        if any(a in {"-d", "-D", "-m", "-M", "-c", "-C", "--delete", "--move", "--copy"} for a in tail):
            return Classification(PermissionLevel.DESTRUCTIVE, "git branch modification")
        return Classification(PermissionLevel.READ_ONLY, "git branch (list)")
    if sub == "apply":
        return Classification(PermissionLevel.READ_ONLY if "--check" in tail or "--stat" in tail or "--numstat" in tail
                              else PermissionLevel.WRITE_PROJECT, "git apply")
    if sub in _GIT_READ:
        return Classification(PermissionLevel.READ_ONLY, f"git {sub}: read-only")
    return Classification(None, f"git {sub or '?'}: not on the executor allowlist")


def _classify_python(rest: list[str]) -> Classification:
    if rest[:2] == ["-m", "pytest"] or rest[:2] == ["-m", "unittest"]:
        return Classification(PermissionLevel.SAFE_EXECUTE, "python -m pytest/unittest")
    if rest[:2] == ["-m", "ruff"] or rest[:2] == ["-m", "flake8"] or rest[:2] == ["-m", "pyflakes"]:
        return _classify_lint_module(rest)
    if rest[:1] in (["-c"], ["-"]) or "-c" in rest[:2]:
        return Classification(PermissionLevel.DESTRUCTIVE, "python -c: arbitrary code execution")
    if rest[:2] == ["-m", "pip"]:
        return classify_argv(["pip", *rest[2:]])
    return Classification(None, "python invocation not on the executor allowlist")


def _classify_lint_module(rest: list[str]) -> Classification:
    if any(a.startswith("--fix") or a in {"--unsafe-fixes", "--write"} for a in rest):
        return Classification(PermissionLevel.WRITE_PROJECT, "linter with fixes modifies files")
    return Classification(PermissionLevel.SAFE_EXECUTE, f"python -m {rest[1]} (no fixes)")


def _classify_node_pm(prog: str, rest: list[str]) -> Classification:
    verb = next((a for a in rest if not a.startswith("-")), "")
    if verb in {"test", "t", "tst"}:
        return Classification(PermissionLevel.SAFE_EXECUTE, f"{prog} test")
    if verb == "run":
        script = [a for a in rest if not a.startswith("-")][1:2]
        if script and script[0] in {"test", "lint", "typecheck"}:
            return Classification(PermissionLevel.SAFE_EXECUTE, f"{prog} run {script[0]}")
        return Classification(None, f"{prog} run <script>: arbitrary project script not allowlisted")
    if verb in {"ls", "list", "outdated", "audit", "view", "info", "why", "explain"}:
        return Classification(PermissionLevel.EXTERNAL_NETWORK if verb in {"outdated", "audit", "view", "info"}
                              else PermissionLevel.READ_ONLY, f"{prog} {verb}")
    if verb in _PKG_NET_VERBS:
        return Classification(PermissionLevel.EXTERNAL_NETWORK, f"{prog} {verb}: package changes / network")
    return Classification(None, f"{prog} {verb}: not on the executor allowlist")


def _classify_npx(rest: list[str]) -> Classification:
    if "--no-install" in rest or "--no" in rest:
        target = next((a for a in rest if not a.startswith("-")), "")
        if target in {"eslint", "tsc", "jest", "vitest"}:
            return Classification(PermissionLevel.SAFE_EXECUTE, f"npx --no-install {target}")
    return Classification(PermissionLevel.EXTERNAL_NETWORK, "npx may download and run remote code")


def classify_command_text(text: str) -> Classification:
    """Classify a raw command *string* the way a shell would read it (used to refuse composed commands)."""
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars="|;&<>()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return Classification(PermissionLevel.DESTRUCTIVE, "unparsable command string")
    if not tokens:
        return Classification(None, "empty command")
    segments: list[tuple[str, list[str]]] = []  # (separator that preceded the segment, argv)
    sep, segment = "", []
    for tok in tokens + [";"]:
        if tok and set(tok) <= set("|;&"):
            if segment:
                segments.append((sep, segment))
            sep, segment = tok, []
        elif tok and set(tok) <= set("<>()") or "`" in tok or "$(" in tok:
            return Classification(PermissionLevel.DESTRUCTIVE, "redirection / substitution / subshell")
        else:
            segment.append(tok)
    worst = Classification(PermissionLevel.READ_ONLY, "read-only")
    for sep, seg in segments:
        if sep == "|" and _base(seg[0]) in _SHELLS:
            return Classification(PermissionLevel.DESTRUCTIVE, "pipe into a shell")
        c = classify_argv(seg)
        if c.level is None or c.level is PermissionLevel.DESTRUCTIVE:
            return c
        if rank(c.level) > rank(worst.level):
            worst = c
    return worst


def assert_argv_allowed(argv: list[str], ceiling: PermissionLevel = PermissionLevel.SAFE_EXECUTE) -> Classification:
    """Last line of defence before ``exec``: refuse anything not allowlisted at or below ``ceiling``."""
    c = classify_argv(argv)
    if c.level is None:
        raise ToolError(f"refused: {c.reason}")
    if c.level is PermissionLevel.DESTRUCTIVE or rank(c.level) > rank(ceiling):
        raise ToolError(f"refused: {c.reason} ({c.level.value})")
    return c

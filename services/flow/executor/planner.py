"""Deterministic instruction -> plan mapping.  No LLM, no guessing.

A plan is a short list of ``{"tool", "args", "why"}`` steps (optionally ``"when": "prev_failed"``).
Instructions that ask for edits, installs, deploys or anything the tools cannot do are *refused*
with an actionable "cannot plan; rephrase" error rather than being approximated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .tools import AUTH_KEYWORDS

MAX_STEPS = 6
PLAN_ERROR_PREFIX = "cannot plan; rephrase"


class PlanError(Exception):
    """The instruction cannot be turned into a safe, deterministic plan."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"{PLAN_ERROR_PREFIX}: {reason}")
        self.reason = reason


_BLOCKED = re.compile(
    r"\b(delete|remove|erase|wipe|drop|deploy|publish|push|commit|merge|rebase|install|uninstall|upgrade|update|fix|"
    r"rewrite|refactor|implement|edit|modify|patch|rename|reset|revert|upload|download|curl|wget|sudo|chmod|kill|rm)\b")
_ALLOWED_PHRASES = re.compile(
    r"\b(?:suggest|propose|recommend|explain|describe|diagnose|identify|point out|tell me)\w*\s+(?:\w+\s+){0,3}?"
    r"(?:fix|fixes|patch|change|changes|update|updates|upgrade|upgrades)\b|\bpassword reset\b|\breset password\b|"
    r"\bhow to (?:fix|update|upgrade)\b|\bwithout (?:changing|modifying|editing)\b|\bnot to (?:change|modify|edit)\b")

_DEP = re.compile(r"\b(dependenc\w*|packages?|requirements?|lockfiles?|librar(?:y|ies)|deps?)\b")
_AUTH_TOPIC = re.compile(r"\b(auth\w*|login|jwt|oauth\w*|sso|saml|oidc|passwords?|sessions?|tokens?)\b")
_STATUS = re.compile(r"\bgit status\b|\bstatus of (?:the |this )?(?:repo|repository|git|project)\b|\buncommitted\b|\bworking tree\b")
_DIFF = re.compile(r"\bdiff\b|\bwhat (?:has )?changed\b|\b(?:recent|my|the|current|pending) changes\b|\bchanged files\b|\bmodified files\b")
_LINT = re.compile(r"\b(lint\w*|ruff|flake8|eslint|pyflakes|static analysis|style check)\b")
_TEST = re.compile(r"\b(tests?|pytest|test suite|specs?|jest|vitest|failing|failures?|failed)\b")
_RUN = re.compile(r"\b(run|execute|rerun|re-run|check|diagnos\w*|why|investigat\w*|debug|verify|see if|figure out)\b|\bpytest\b")
_DIAGNOSE = re.compile(r"\b(diagnos\w*|why|investigat\w*|debug|root cause|explain|what'?s wrong|broken|failing|failures?|failed)\b")
_SEARCH = re.compile(r"\b(search|grep|find|look for|locate|where (?:is|are|do|does)|occurrences? of|uses? of|usages? of|references? to)\b")
_READ = re.compile(r"\b(read|show|open|view|cat|print|display|look at|inspect|summari[sz]e)\b")
_LOGS = re.compile(r"\blogs?\b")
_LIST = re.compile(r"\b(list|show|what)\b.*\b(files?|directory|directories|folders?|structure|layout|tree)\b|\bls\b")
_QUOTED = re.compile(r"[\"'`]([^\"'`]{1,120})[\"'`]")
_EXT = r"(?:py|js|ts|tsx|jsx|json|toml|ya?ml|md|txt|cfg|ini|log|go|rs|java|rb|sh|lock|html|css|out)"
_PATH = re.compile(rf"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.{_EXT}|(?:[\w.-]+/)+[\w.-]*)(?![\w-])")
_KEYWORD_STOP = {"the", "all", "my", "our", "unit", "failing", "failed", "these", "those", "this", "that", "and", "or", "then",
                 "project", "whole", "entire", "full", "new", "existing", "a", "an", "run", "check", "rerun", "test",
                 "integration", "relevant", "related", "specific", "some", "any", "which", "what", "if", "of", "for"}
_METADATA_FILES = {"pyproject.toml", "package.json", "requirements.txt", "package-lock.json", "poetry.lock", "uv.lock"}


def _step(tool: str, args: dict[str, Any], why: str, when: str | None = None) -> dict[str, Any]:
    step: dict[str, Any] = {"tool": tool, "args": args, "why": why}
    if when:
        step["when"] = when
    return step


def _paths(text: str) -> list[str]:
    found = []
    for m in _PATH.finditer(text):
        token = m.group(1).rstrip(".,;:)")
        if token and not token.startswith(("http", "//")) and "@" not in token and token not in found:
            found.append(token)
    return found


def _test_keyword(text: str) -> str | None:
    for m in re.finditer(r"\b([a-z0-9_]{2,30})\s+tests?\b", text):
        word = m.group(1)
        if word not in _KEYWORD_STOP:
            return word
    m = re.search(r"\btests?\s+(?:for|of|in|covering)\s+(?:the\s+)?([a-z0-9_]{2,30})\b", text)
    if m and m.group(1) not in _KEYWORD_STOP:
        return m.group(1)
    return None


def plan_instruction(instruction: str, workdir: str | Path | None = None) -> list[dict[str, Any]]:
    if not isinstance(instruction, str) or not instruction.strip():
        raise PlanError("the instruction is empty")
    raw = " ".join(instruction.split())
    quoted = [q.strip() for q in _QUOTED.findall(raw) if q.strip()]
    text = raw.lower()
    scrubbed = _ALLOWED_PHRASES.sub(" ", text)
    blocked = _BLOCKED.search(scrubbed)
    if blocked:
        raise PlanError(f"'{blocked.group(1)}' needs write, network or destructive access, which delegated tasks do not "
                        "plan on their own. Ask for an inspection instead (for example: run the tests, check dependencies, "
                        "show git status, search for a term).")
    steps: list[dict[str, Any]] = []
    paths = _paths(raw)
    file_paths = [p for p in paths if not p.endswith("/")]
    dep_intent = bool(_DEP.search(text))

    if dep_intent:
        auth = bool(_AUTH_TOPIC.search(text))
        steps.append(_step("inspect_package_metadata", {"keywords": list(AUTH_KEYWORDS) if auth else []},
                           ("List auth-related dependencies with declared/locked versions; latest versions cannot be "
                            "checked offline" if auth else "List declared and locked dependency versions")))
    if _DIFF.search(text):
        steps.append(_step("git_status", {}, "See which files changed"))
        steps.append(_step("git_diff", {}, "Show the actual changes"))
    elif _STATUS.search(text):
        steps.append(_step("git_status", {}, "Show the repository state"))
    if _LINT.search(text):
        target = next((p for p in file_paths if not p.endswith(".log")), None)
        steps.append(_step("run_linter", {"path": target} if target else {}, "Run the linter without auto-fix"))
    if _TEST.search(text) and _RUN.search(text):
        args: dict[str, Any] = {}
        target = next((p for p in paths if "test" in p.lower() or p.endswith(".py")), None)
        if target:
            args["path"] = target
        else:
            keyword = _test_keyword(text)
            if keyword:
                args["keyword"] = keyword
        steps.append(_step("run_tests", args, "Run the tests and record the exit code and counts"))
        if _DIAGNOSE.search(text):
            steps.append(_step("read_logs", {"source": "previous", "tail_lines": 60},
                               "Look at the error lines of the test output", "prev_failed"))
            steps.append(_step("search_text", {"query": "$failed_test_name"},
                               "Locate the failing test in the source", "prev_failed"))
    if _LOGS.search(text) and not (dep_intent and not _READ.search(text)):
        log_path = next((p for p in file_paths if p.endswith((".log", ".out", ".txt"))), None)
        steps.append(_step("read_logs", {"path": log_path} if log_path else {}, "Read the tail of the log"))
    elif _READ.search(text) and file_paths:
        for path in file_paths[:2]:
            if dep_intent and path.split("/")[-1] in _METADATA_FILES:
                continue
            if any(s["tool"] == "run_tests" and s["args"].get("path") == path for s in steps):
                continue
            steps.append(_step("read_file", {"path": path}, f"Read {path}"))
    if _SEARCH.search(text) and (quoted or not steps):
        term = quoted[0] if quoted else None
        if term is None:
            m = re.search(r"(?:search|grep|find|look for|locate|occurrences? of|uses? of|usages? of|references? to|where (?:is|are|do|does))"
                          r"\s+(?:for\s+|the\s+|all\s+)*([\w.\-/:]+)", raw, re.IGNORECASE)
            term = m.group(1) if m and m.group(1).lower() not in _KEYWORD_STOP else None
        if not term:
            raise PlanError("say what to search for, ideally in quotes (for example: search for \"TODO\")")
        steps.append(_step("search_text", {"query": term}, f"Find occurrences of {term!r}"))
    if not steps and _LIST.search(text):
        steps.append(_step("list_files", {"path": next((p.rstrip("/") for p in paths if p.endswith("/")), ".")},
                           "List the project files"))
    if not steps:
        raise PlanError("I could not map this to a known inspection. Supported: run tests (optionally for a topic or file), "
                        "run the linter, check dependencies, git status/diff, read a file or log, search for a term, "
                        "list files")
    unique: list[dict[str, Any]] = []
    for step in steps:
        if step not in unique:
            unique.append(step)
    return unique[:MAX_STEPS]

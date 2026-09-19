"""Client for the Swift ``flow-macos-observer`` helper (one JSON line per call)."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import (CaptureFailed, DisplayNotFound, HelperMissing, HelperUnsupported,
                     ObserverError, PermissionDenied)
from .runner import Runner, RunResult, run

HELPER_NAME = "flow-macos-observer"
ENV_VAR = "FLOW_MACOS_HELPER"
MAX_FRAME_BYTES = 32 * 1024 * 1024

_ERRORS = {"permission_denied": PermissionDenied, "unsupported_os": HelperUnsupported,
           "display_not_found": DisplayNotFound}


def find_helper(explicit: str | os.PathLike[str] | None = None, env: Mapping[str, str] | None = None) -> str | None:
    """Explicit path, then FLOW_MACOS_HELPER, then PATH, then bundled/build locations."""
    env = os.environ if env is None else env
    for candidate in (explicit, env.get(ENV_VAR)):
        if candidate and _executable(candidate):
            return str(candidate)
    found = shutil.which(HELPER_NAME, path=env.get("PATH"))
    if found:
        return found
    package_root = Path(__file__).resolve().parents[4]
    for bundled in (Path(__file__).resolve().parents[2] / "bin" / HELPER_NAME,
                    package_root / "native" / "macos-observer" / ".build" / "release" / HELPER_NAME,
                    Path.home() / ".local" / "share" / "flow" / "bin" / HELPER_NAME):
        if _executable(bundled):
            return str(bundled)
    return None


def _executable(path: str | os.PathLike[str]) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _error_from(payload: Mapping[str, Any]) -> ObserverError:
    code = str(payload.get("error", "capture_failed"))
    message = str(payload.get("message") or code)
    hint = None
    if code == "permission_denied":
        hint = "grant Screen Recording in System Settings > Privacy & Security, then restart the terminal"
    return _ERRORS.get(code, CaptureFailed)(message, hint=hint)


def _split(result: RunResult) -> tuple[dict[str, Any], bytes]:
    head, _, rest = result.stdout.partition(b"\n")
    try:
        payload = json.loads(head.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("not an object")
    except (ValueError, UnicodeDecodeError) as exc:
        detail = result.stderr.decode("utf-8", "replace").strip()[:200]
        raise CaptureFailed(f"helper returned invalid output (exit {result.returncode}) {detail}".strip()) from exc
    if not payload.get("ok", False):
        raise _error_from(payload)
    return payload, rest


class Helper:
    def __init__(self, path: str, runner: Runner = run, timeout: float = 10.0) -> None:
        self.path, self.runner, self.timeout = path, runner, timeout

    def call(self, *args: str, timeout: float | None = None) -> dict[str, Any]:
        result = self.runner([self.path, *args], timeout or self.timeout)
        payload, _ = _split(result)
        return payload

    def version(self) -> dict[str, Any]:
        return self.call("version", timeout=5)

    def capture(self, display: str, max_dim: int, image_format: str,
                timeout: float) -> tuple[dict[str, Any], bytes]:
        command: Sequence[str] = [self.path, "capture", "--display", display, "--max-dim", str(max_dim),
                                  "--format", image_format, "--out", "-"]
        payload, data = _split(self.runner(command, timeout))
        expected = payload.get("bytes")
        if not isinstance(expected, int) or expected <= 0 or expected > MAX_FRAME_BYTES:
            raise CaptureFailed("helper reported an invalid frame size")
        if len(data) != expected:
            raise CaptureFailed(f"helper frame truncated ({len(data)} of {expected} bytes)")
        return payload, data


def require_helper(path: str | None) -> Helper:
    if path is None:
        raise HelperMissing("flow-macos-observer helper not found",
                            hint="run scripts/build-macos-helper.sh and set FLOW_MACOS_HELPER")
    return Helper(path)

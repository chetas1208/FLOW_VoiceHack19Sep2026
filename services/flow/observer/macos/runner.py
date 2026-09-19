"""Single subprocess choke point: bounded timeout, no shell, no stdin, typed failures."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Sequence

from .errors import CaptureFailed, CaptureTimeout, HelperMissing


@dataclass(frozen=True, slots=True)
class RunResult:
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


Runner = Callable[[Sequence[str], float], RunResult]


def run(command: Sequence[str], timeout: float) -> RunResult:
    try:
        completed = subprocess.run(list(command), capture_output=True, timeout=timeout, check=False,
                                   stdin=subprocess.DEVNULL, shell=False)
    except subprocess.TimeoutExpired as exc:
        raise CaptureTimeout(f"{command[0]} did not finish within {timeout:g}s",
                             hint="retry, or check that the display is awake and unlocked") from exc
    except FileNotFoundError as exc:
        raise HelperMissing(f"{command[0]} was not found", hint="run scripts/build-macos-helper.sh") from exc
    except OSError as exc:
        raise CaptureFailed(f"could not execute {command[0]}: {exc.strerror or exc}") from exc
    return RunResult(completed.returncode, completed.stdout or b"", completed.stderr or b"")

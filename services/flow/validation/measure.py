"""Run a child process and report exit code, wall/CPU time and its OWN peak RSS (via wait4)."""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

OUTPUT_LIMIT = 1_000_000


@dataclass(frozen=True, slots=True)
class Measured:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    wall_seconds: float = 0.0
    cpu_seconds: float = 0.0
    peak_rss_mb: float = 0.0
    timed_out: bool = False


def _rss_to_mb(value: int) -> float:
    # ru_maxrss is bytes on macOS and kilobytes on Linux.
    return value / (1024 * 1024) if platform.system() == "Darwin" else value / 1024


def run_measured(command: Sequence[str], timeout: float, env: Mapping[str, str] | None = None) -> Measured:
    with tempfile.TemporaryDirectory(prefix="flow-validate-") as tmp:
        out_path, err_path = Path(tmp) / "out", Path(tmp) / "err"
        started = time.monotonic()
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            try:
                proc = subprocess.Popen(list(command), stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                        env=None if env is None else dict(env), start_new_session=True)
            except OSError as exc:
                return Measured(127, "", f"cannot execute {command[0]}: {exc}")
            timed_out = False
            while True:
                pid, status, usage = os.wait4(proc.pid, os.WNOHANG)
                if pid:
                    break
                if time.monotonic() - started > timeout:
                    timed_out = True
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    _, status, usage = os.wait4(proc.pid, 0)
                    break
                time.sleep(0.05)
            proc.returncode = os.waitstatus_to_exitcode(status)
        wall = time.monotonic() - started
        stdout = out_path.read_bytes()[:OUTPUT_LIMIT].decode("utf-8", "replace")
        stderr = err_path.read_bytes()[:OUTPUT_LIMIT].decode("utf-8", "replace")
    return Measured(proc.returncode, stdout, stderr, wall, usage.ru_utime + usage.ru_stime,
                    _rss_to_mb(usage.ru_maxrss), timed_out)


def current_rss_mb() -> float | None:
    """Resident set size of this process right now, in MB."""
    try:
        with open("/proc/self/status") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    try:
        result = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True,
                                text=True, timeout=5, check=False)
        return int(result.stdout.strip()) / 1024
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def peak_rss_mb() -> float:
    import resource
    return _rss_to_mb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

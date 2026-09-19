"""Injectable environment for the validators, so every probe is testable without a Mac."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from ..config import config_dir as default_config_dir, data_dir as default_data_dir
from .measure import Measured, run_measured


def _say(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def _open_path(path: str) -> bool:
    try:
        return subprocess.run(["/usr/bin/open", path], capture_output=True, timeout=10, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@dataclass
class ValidationContext:
    system: Callable[[], str] = platform.system
    machine: Callable[[], str] = platform.machine
    mac_version: Callable[[], str] = lambda: platform.mac_ver()[0]
    env: Mapping[str, str] = field(default_factory=lambda: os.environ)
    interactive: bool = True
    scenario_timeout: float = 240.0
    poll_interval: float = 2.0
    data_dir: Path = field(default_factory=default_data_dir)
    config_dir: Path = field(default_factory=default_config_dir)
    flow_command: list[str] = field(default_factory=lambda: [sys.executable, "-m", "services.flow.cli"])
    say: Callable[[str], None] = _say
    ask: Callable[[str], str] = input
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    measure: Callable[..., Measured] = run_measured
    open_path: Callable[[str], bool] = _open_path
    observer_factory: Callable[[], object] | None = None
    exclude_app: str | None = None
    session_id: str | None = None
    cloud_timeout: float = 5.0
    http_get: Callable[[str, float], tuple[int, str]] | None = None
    model_timeout: float = 900.0

    @property
    def is_macos(self) -> bool:
        return self.system() == "Darwin"

"""Fail-closed Docker isolation adapter for opt-in untrusted test workloads.

Not a security certificate: Docker daemon permissions, kernel isolation,
image provenance, tenant boundaries and host volume exposure require review.
No fallback to executing untrusted project commands on the host.
"""
import os
import shutil
import subprocess
from pathlib import Path

ALLOWED = {'python', 'python3', 'pytest', 'node', 'npm'}


def run_isolated(repo, command, *, image='python:3.12-slim', timeout=120, extra_env=None):
    repo = Path(repo).resolve(strict=True)
    if not repo.is_dir() or not isinstance(command, list) or not command:
        raise ValueError('repository directory and argv are required')
    if command[0] not in ALLOWED or not all(isinstance(arg, str) and 0 < len(arg) <= 1024 for arg in command):
        raise ValueError('command is not an allowlisted executable + argv')
    if not 1 <= timeout <= 300:
        raise ValueError('timeout must be between 1 and 300 seconds')
    if extra_env:
        raise ValueError('unreviewed environment variables are not allowed in sandbox')
    if not shutil.which('docker'):
        raise RuntimeError('Docker unavailable: refusing host fallback for untrusted code')
    args = ['docker', 'run', '--rm', '--pull=never', '--network=none',
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--pids-limit=64', '--memory=512m', '--cpus=1',
            '--user=65534:65534', '--tmpfs=/tmp:rw,nosuid,noexec,size=64m',
            '--mount', f'type=bind,src={repo},dst=/workspace,readonly',
            '--workdir=/workspace', image, *command]
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False,
                                env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')})
    except subprocess.TimeoutExpired as exc:
        return {'status': 'TIMEOUT', 'returncode': None, 'stdout': '', 'stderr': 'sandbox timeout'}
    # Never dump arbitrary stdout in telemetry; return bounded result for local caller only.
    return {'status': 'COMPLETED' if result.returncode == 0 else 'FAILED',
            'returncode': result.returncode, 'stdout': result.stdout[:16000],
            'stderr': result.stderr[:16000]}

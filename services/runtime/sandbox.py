"""Fail-closed Docker isolation adapter for opt-in untrusted test workloads.

Not a security certificate: Docker daemon permissions, kernel isolation,
image provenance, tenant boundaries and host volume exposure require review.
No fallback to executing untrusted project commands on the host.

Statuses: COMPLETED / FAILED describe the workload. TIMEOUT means the workload
was stopped and its container removed. INFRA_ERROR (docker exit 125: daemon or
image problem) and UNAVAILABLE (daemon unreachable) describe the environment and
must never be read as a test result.
"""
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

ALLOWED = {'python', 'python3', 'pytest', 'node', 'npm'}
LABEL = 'agentgraph.sandbox=1'
DOCKER_ERROR = 125  # `docker run` itself failed (daemon, image, option), not the workload


# Daemon selection only; nothing here reaches the workload container.
CLIENT_ENV = ('HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH')


def _docker(args, timeout):
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin')}
    env.update({k: os.environ[k] for k in CLIENT_ENV if k in os.environ})
    return subprocess.run(['docker', *args], capture_output=True, text=True, timeout=timeout, check=False, env=env)


def _remove(name):
    try:
        _docker(['rm', '--force', name], 30)
    except (OSError, subprocess.TimeoutExpired):
        pass


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
    try:
        probe = _docker(['info', '--format', '{{.ServerVersion}}'], 15)
    except subprocess.TimeoutExpired:
        probe = None
    if probe is None or probe.returncode != 0:
        return {'status': 'UNAVAILABLE', 'returncode': None, 'stdout': '',
                'stderr': 'Docker daemon unreachable: no workload was run'}
    name = 'agentgraph-sb-' + uuid4().hex[:16]
    args = ['run', '--rm', '--name', name, '--label', LABEL, '--pull=never', '--network=none',
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
            '--pids-limit=64', '--memory=512m', '--cpus=1',
            '--user=65534:65534', '--tmpfs=/tmp:rw,nosuid,noexec,size=64m',
            '--mount', f'type=bind,src={repo},dst=/workspace,readonly',
            '--workdir=/workspace', image, *command]
    try:
        result = _docker(args, timeout)
    except subprocess.TimeoutExpired:
        # Killing the CLI does not stop the container: remove it explicitly.
        _remove(name)
        return {'status': 'TIMEOUT', 'returncode': None, 'stdout': '', 'stderr': 'sandbox timeout; container removed',
                'container': name}
    if result.returncode == DOCKER_ERROR:
        _remove(name)
        return {'status': 'INFRA_ERROR', 'returncode': result.returncode, 'stdout': '',
                'stderr': result.stderr[:4000], 'container': name}
    # Never dump arbitrary stdout in telemetry; return bounded result for local caller only.
    return {'status': 'COMPLETED' if result.returncode == 0 else 'FAILED',
            'returncode': result.returncode, 'stdout': result.stdout[:16000],
            'stderr': result.stderr[:16000], 'container': name}

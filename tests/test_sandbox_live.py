"""Live Docker sandbox checks. Opt-in (QA_DOCKER_LIVE=1): needs a running daemon and python:3.12-slim."""
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from services.runtime.sandbox import LABEL, run_isolated

pytestmark = pytest.mark.skipif(os.getenv('QA_DOCKER_LIVE') != '1', reason='opt-in live Docker sandbox test')
# VM-backed daemons (Colima, Docker Desktop) share only some host paths, typically $HOME;
# system temp dirs are often not mountable. Keep workspaces under the repo instead.
BASE = Path(os.getenv('QA_SANDBOX_TMP', Path(__file__).resolve().parents[1] / '.local-runs' / 'sandbox-tests'))


def _workspace():
    BASE.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=BASE)

PROBE = '''
import os, socket
print('uid', os.getuid())
try:
    socket.create_connection(('1.1.1.1', 53), 2); print('network OPEN')
except OSError: print('network blocked')
for target in ('/workspace/escape.txt', '/etc/escape.txt'):
    try:
        open(target, 'w').write('x'); print('write OPEN', target)
    except OSError: print('write blocked', target)
open('/tmp/scratch', 'w').write('ok'); print('tmp writable')
'''


def _ours():
    return subprocess.run(['docker', 'ps', '-aq', '--filter', 'label=' + LABEL],
                          capture_output=True, text=True, check=True).stdout.split()


def test_live_isolation_properties():
    with _workspace() as temp:
        (Path(temp) / 'probe.py').write_text(PROBE)
        result = run_isolated(temp, ['python', 'probe.py'], timeout=60)
        assert result['status'] == 'COMPLETED', result
        out = result['stdout']
        assert 'uid 65534' in out
        assert 'network blocked' in out and 'network OPEN' not in out
        assert 'write OPEN' not in out and out.count('write blocked') == 2
        assert 'tmp writable' in out
        assert not (Path(temp) / 'escape.txt').exists()


def test_live_workload_failure_is_failed_not_infra():
    with _workspace() as temp:
        result = run_isolated(temp, ['python', '-c', 'raise SystemExit(3)'], timeout=60)
        assert result['status'] == 'FAILED' and result['returncode'] == 3


def test_live_timeout_removes_the_container():
    with _workspace() as temp:
        started = time.monotonic()
        result = run_isolated(temp, ['python', '-c', 'import time; time.sleep(60)'], timeout=3)
        assert result['status'] == 'TIMEOUT'
        assert time.monotonic() - started < 40
        assert result['container'] not in subprocess.run(
            ['docker', 'ps', '-a', '--format', '{{.Names}}'], capture_output=True, text=True).stdout
        assert _ours() == []


def test_live_missing_image_is_infra_error_not_test_failure():
    with _workspace() as temp:
        result = run_isolated(temp, ['python', '-V'], image='proofhound-missing-image:never', timeout=60)
        assert result['status'] == 'INFRA_ERROR' and result['returncode'] == 125
        assert _ours() == []


def test_unreachable_daemon_is_unavailable_not_failed():
    with _workspace() as temp:
        with patch.dict(os.environ, {'DOCKER_HOST': 'unix:///nonexistent/proofhound.sock'}):
            result = run_isolated(temp, ['python', '-V'], timeout=30)
        assert result['status'] == 'UNAVAILABLE' and result['returncode'] is None

import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from services.runtime.sandbox import run_isolated


def test_sandbox_rejects_untrusted_host_fallback():
    with tempfile.TemporaryDirectory() as temp:
        with patch('services.runtime.sandbox.shutil.which',return_value=None):
            with pytest.raises(RuntimeError,match='refusing host fallback'):
                run_isolated(temp,['python','-m','pytest'])
        with pytest.raises(ValueError):
            run_isolated(temp,['bash','-c','cat /etc/shadow'])
        with pytest.raises(ValueError):
            run_isolated(temp,['python'],extra_env={'AWS_SECRET_ACCESS_KEY':'leak'})


def test_sandbox_constructs_hardened_docker_command():
    class Result:
        returncode=0
        stdout='all good'
        stderr=''
    with tempfile.TemporaryDirectory() as temp:
        with patch('services.runtime.sandbox.shutil.which',return_value='/usr/bin/docker'),\
             patch('services.runtime.sandbox.subprocess.run',return_value=Result()) as call:
            result=run_isolated(temp,['python','-m','pytest'])
            args=call.call_args.args[0]
            assert '--network=none' in args and '--read-only' in args
            assert '--cap-drop=ALL' in args and '--pull=never' in args
            assert any(x.startswith('type=bind') and 'readonly' in x for x in args)
            assert call.call_args.kwargs['timeout']==120
            assert result['status']=='COMPLETED'

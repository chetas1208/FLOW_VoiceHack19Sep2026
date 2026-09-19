"""Live uvicorn OTLP receiver + client exporter + SQLite span recovery."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from reference_apps.fixtures import agentic_fixture, manifest_for

ROOT=Path(__file__).resolve().parents[1]


def test_persistent_otlp_ingestion_end_to_end():
    with tempfile.TemporaryDirectory() as temp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0))
            port=sock.getsockname()[1]
        env={**os.environ,'QA_DATA_DIR':temp,'QA_OTLP_INGEST_TOKEN':'test-secret-token'}
        server=subprocess.Popen([sys.executable,'-m','uvicorn','services.telemetry.receiver:app',
                                 '--host','127.0.0.1','--port',str(port),'--log-level','error'],
                                cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            for _ in range(80):
                if server.poll() is not None:
                    raise AssertionError('receiver exited: '+server.stderr.read().decode()[:500])
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.1)
            else:
                raise AssertionError('OTLP receiver failed to listen')
            with agentic_fixture() as (base, oracle):
                manifest=Path(temp)/'manifest.json'
                manifest.write_text(json.dumps(manifest_for('agentic',base,oracle)))
                result=subprocess.run([sys.executable,'-m','services.engine.cli',str(manifest),
                                       '--output',temp,'--otlp-endpoint',
                                       f'http://127.0.0.1:{port}/v1/traces'],
                                      env=env,cwd=ROOT,text=True,capture_output=True,timeout=35)
                assert result.returncode==0,result.stderr
                run=json.loads(result.stdout)
                assert run['verdict']=='FAIL'
            with sqlite3.connect(Path(temp)/'telemetry.sqlite3') as db:
                spans=db.execute('SELECT name,run_id FROM spans WHERE trace_id=?',(run['trace_id'],)).fetchall()
            assert any(name=='qa.run' and rid==run['run_id'] for name,rid in spans)
            assert any(name=='qa.independent_verification' for name,_ in spans)
        finally:
            server.terminate()
            try: server.wait(timeout=5)
            except subprocess.TimeoutExpired: server.kill();server.wait(timeout=3)
            if server.stderr:server.stderr.close()

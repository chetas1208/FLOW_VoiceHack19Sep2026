import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import pytest
from services.engine.manifest import validate_manifest
from services.engine.runner import execute
from services.engine.store import Store


def test_scoped_environment_credential_not_persisted_or_logged():
    class Protected(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get('Authorization')!='Bearer very-private-fixture-token':
                self.send_error(401)
                return
            body=b'{"status":"ok","authorization":"very-private-fixture-token"}'
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Protected)
    thread=Thread(target=server.serve_forever,daemon=True)
    thread.start()
    key='QA_TARGET_TOKEN_UNIT_TEST'
    manifest={'id':'authenticated', 'base_url':f'http://127.0.0.1:{server.server_port}',
              'auth_env':key,'steps':[{'name':'read','method':'GET','path':'/'}],
              'assertions':[{'id':'okay','step':'read','pointer':'/status','operator':'equals','expected':'ok'}]}
    old=os.environ.get(key)
    try:
        with pytest.raises(ValueError):
            validate_manifest(manifest)
        os.environ[key]='very-private-fixture-token'
        with tempfile.TemporaryDirectory() as temp:
            result=execute(manifest,temp)
            assert result['verdict']=='PASS'
            evidence=Store(temp).evidence_bytes(result['evidence_sha256'])
            assert b'very-private-fixture-token' not in evidence
            assert 'very-private-fixture-token' not in str(result)
    finally:
        if old is None:os.environ.pop(key,None)
        else:os.environ[key]=old
        server.shutdown();server.server_close();thread.join(timeout=3)

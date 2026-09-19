"""Actual protobuf wire export from new engine to a local OTLP/HTTP receiver."""
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from reference_apps.fixtures import agentic_fixture, manifest_for

ROOT=Path(__file__).resolve().parents[1]


def test_new_engine_otlp_receiver_trace_ids():
    received=[]
    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path,self.rfile.read(int(self.headers['content-length']))))
            self.send_response(200)
            self.send_header('Content-Type','application/x-protobuf')
            self.send_header('Content-Length','0')
            self.end_headers()
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Receiver)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as temp, agentic_fixture() as (base, oracle):
            manifest=Path(temp)/'manifest.json'
            manifest.write_text(json.dumps(manifest_for('agentic',base,oracle)))
            command=[sys.executable,'-m','services.engine.cli',str(manifest),
                     '--output',temp,'--otlp-endpoint',f'http://127.0.0.1:{server.server_port}/v1/traces']
            p=subprocess.run(command,cwd=ROOT,text=True,capture_output=True,timeout=30)
            assert p.returncode==0,p.stderr
            run=json.loads(p.stdout)
            assert run['verdict']=='FAIL'
            assert received and all(path=='/v1/traces' for path,_ in received)
            spans=[span for _,blob in received for resource in ExportTraceServiceRequest.FromString(blob).resource_spans
                   for scope in resource.scope_spans for span in scope.spans]
            assert any(s.trace_id.hex()==run['trace_id'] for s in spans)
            assert any(s.name=='qa.independent_verification' for s in spans)
            assert any(s.name=='qa.http_step' for s in spans)
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)

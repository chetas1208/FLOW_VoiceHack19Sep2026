"""Real HTTP and actual OTLP/HTTP receiver integration tests."""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.fullstack_qa.live import verify_retry
from services.agentic_qa.adapter import verify_project_creation

class OTLPReceiver(BaseHTTPRequestHandler):
    received=[]
    def do_POST(self):
        body=self.rfile.read(int(self.headers['Content-Length']))
        self.__class__.received.append((self.path,body,self.headers.get('Content-Type')))
        self.send_response(200)
        self.send_header('Content-Type','application/x-protobuf')
        self.send_header('Content-Length','0')
        self.end_headers()
    def log_message(self,*args):pass

class LiveIntegration(unittest.TestCase):
    def test_real_http_retry_fails(self):
        r=verify_retry();self.assertEqual(r['verdict'],'FAIL');self.assertEqual(r['observed']['server_charge_count'],2)
        self.assertEqual([x['status'] for x in r['observed']['http_responses']],[200,200])
    def test_agent_output_not_trusted(self):
        r=verify_project_creation();self.assertEqual(r['verdict'],'FAIL');self.assertFalse(r['assertions']['project_exists'])
    def test_actual_otlp_http_export(self):
        from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
        OTLPReceiver.received=[]
        server=HTTPServer(('127.0.0.1',0),OTLPReceiver)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                cmd=[sys.executable,'-m','services.runtime.live','agentic','--output',temp,'--otlp-endpoint',f'http://127.0.0.1:{server.server_port}/v1/traces']
                p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,timeout=25)
                self.assertEqual(p.returncode,0,p.stderr)
                record=json.loads(p.stdout)
                self.assertTrue(OTLPReceiver.received,'No OTLP POST received')
                path,body,content_type=OTLPReceiver.received[0]
                self.assertEqual(path,'/v1/traces')
                self.assertEqual(content_type,'application/x-protobuf')
                req=ExportTraceServiceRequest.FromString(body)
                ids=[span.trace_id.hex() for resource in req.resource_spans for scope in resource.scope_spans for span in scope.spans]
                self.assertIn(record['trace_id'],ids)
                self.assertEqual(record['verdict'],'FAIL')
        finally:
            server.shutdown();server.server_close();thread.join(timeout=3)
if __name__=='__main__':unittest.main()

"""End-to-end oracle, privacy, HACP wire and browser tests."""
import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from fastapi.testclient import TestClient
from jsonschema import ValidationError
from reference_apps.fixtures import fullstack_fixture, agentic_fixture, manifest_for
from services.engine.manifest import validate_manifest
from services.engine.runner import execute, resolve_pointer, MISSING
from services.engine.store import Store
from services.platform.hacp_mailbox import Mailbox, envelope, canonical, collaboration_demo
from benchmarks.benchmark import benchmark


class EngineTests(unittest.TestCase):
    def test_four_case_benchmark(self):
        with tempfile.TemporaryDirectory() as temp:
            report = benchmark(temp)
            self.assertEqual(report['known_defect_detection'], 2)
            self.assertEqual(report['known_defect_total'], 2)
            self.assertEqual(report['false_failure_count'], 0)
            self.assertEqual(report['known_good_total'], 2)
            self.assertTrue(all(item['correct'] for item in report['cases']))
            self.assertEqual(len(Store(temp).list()), 4)

    def test_fullstack_oracle_and_graph(self):
        from services.graph.graph import Graph
        with tempfile.TemporaryDirectory() as temp, fullstack_fixture() as (app, oracle):
            manifest = manifest_for('fullstack', app, oracle)
            result = execute(manifest, temp, graph=Graph(Path(temp)/'graph.sqlite3'))
            self.assertEqual(result['verdict'], 'FAIL')
            self.assertEqual(len(result['trace_id']), 32)
            self.assertIn('exactly-once', [a['id'] for a in result['assertions'] if a['status'] == 'FAIL'])
            evidence = json.loads(Store(temp).evidence_bytes(result['evidence_sha256']))
            self.assertNotIn('benchmark-order', json.dumps(evidence))  # raw state is not persisted
            self.assertIn('qa.run', __import__('inspect').getsource(execute))

    def test_agent_corrected_and_false_success(self):
        with tempfile.TemporaryDirectory() as temp:
            for fixed, expected in ((False, 'FAIL'), (True, 'PASS')):
                with agentic_fixture(fixed) as (base, oracle):
                    result = execute(manifest_for('agentic', base, oracle), temp)
                    self.assertEqual(result['verdict'], expected)

    def test_manifest_rejects_remote_and_destructive(self):
        with fullstack_fixture() as (base, oracle):
            m = manifest_for('fullstack', base, oracle)
            for malicious in ('http://169.254.169.254', 'http://example.com', 'file:///etc/passwd',
                              'http://localhost:80/path', 'http://admin:secret@localhost'):
                changed = copy.deepcopy(m)
                changed['base_url'] = malicious
                with self.assertRaises((ValueError, ValidationError)):
                    validate_manifest(changed)
            changed = copy.deepcopy(m)
            changed['steps'][0]['method'] = 'DELETE'
            with self.assertRaises(ValueError):
                validate_manifest(changed)
            changed = copy.deepcopy(m)
            changed['steps'][0]['target'] = 'oracle'
            with self.assertRaises(ValueError):
                validate_manifest(changed)
            changed = copy.deepcopy(m)
            changed['assertions'][0]['step'] = 'does-not-exist'
            with self.assertRaises(ValueError):
                validate_manifest(changed)

    def test_manifest_does_not_execute_arbitrary_commands(self):
        with fullstack_fixture() as (base, oracle):
            m = manifest_for('fullstack', base, oracle)
            m['steps'][0]['command'] = 'rm -rf /'
            with self.assertRaises(ValidationError):
                validate_manifest(m)

    def test_evidence_redaction_and_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            run = {'run_id': 'test', 'project_id': 'p', 'scenario_id': 's', 'version': 'v',
                   'kind': 'agentic', 'verdict': 'PASS', 'trace_id': '0'*32,
                   'created_at': '2026-09-19T00:00:00Z', 'observed': {
                       'password': 'do-not-persist', 'nested': {'api_key': 'do-not-persist'}, 'safe': 42}}
            result = store.save(run)
            evidence = store.evidence_bytes(result['evidence_sha256'])
            self.assertNotIn(b'do-not-persist', evidence)
            self.assertEqual(json.loads(evidence)['safe'], 42)
            (store.evidence/(result['evidence_sha256']+'.json')).write_text('tampered')
            with self.assertRaises(IOError):
                store.evidence_bytes(result['evidence_sha256'])
            with self.assertRaises(ValueError):
                store.evidence_bytes('../../etc/passwd')

    def test_missing_pointer_not_a_false_pass(self):
        self.assertIs(resolve_pointer({}, '/missing'), MISSING)
        self.assertIs(resolve_pointer({'a': []}, '/a/0'), MISSING)

    def test_nonjson_state_inconclusive(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'<html>not JSON</html>')
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            manifest = {'id': 'nonjson', 'base_url': base,
                        'steps': [{'name': 'get', 'method': 'GET', 'path': '/'}],
                        'assertions': [{'id': 'value', 'step': 'get', 'pointer': '/a',
                                        'operator': 'equals', 'expected': 1}]}
            with tempfile.TemporaryDirectory() as temp:
                self.assertEqual(execute(manifest, temp)['verdict'], 'INCONCLUSIVE')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_hacp_wire_and_replay_tamper_and_membership(self):
        a, b, stranger = ('urn:hacp:agent:a', 'urn:hacp:agent:b', 'urn:hacp:agent:stranger')
        keys = {a: b'agent-a-secret', b: b'agent-b-secret', stranger: b'other-secret'}
        with tempfile.TemporaryDirectory() as temp:
            m = Mailbox(Path(temp)/'mailbox.db', keys)
            m.open('s1', a, b)
            record = envelope('s1', a, b, 'contract.proposed', {'task_id': 't'})
            signature = m.sign(record, a)
            m.deliver(record, signature)
            self.assertEqual(m.receive('s1', b)[0]['message_id'], record['message_id'])
            self.assertEqual(m.receive('s1', b), [])
            with self.assertRaises(ValueError):
                m.deliver(record, signature)
            altered = dict(record, message_id='m-' + 'a'*32, body={'task_id': 'evil'})
            with self.assertRaises(PermissionError):
                m.deliver(altered, signature)
            outside = envelope('s1', a, stranger, 'contract.proposed', {})
            with self.assertRaises(PermissionError):
                m.deliver(outside, m.sign(outside, a))
            m.close('s1', a)
            with self.assertRaises(PermissionError):
                m.deliver(envelope('s1', a, b, 'heartbeat', {}), m.sign(envelope('s1', a, b, 'heartbeat', {}), a))

    def test_hacp_canonical_vectors_and_float_rejection(self):
        import hashlib
        self.assertEqual(hashlib.sha256(canonical({'b': 2, 'a': 1}).encode()).hexdigest(),
                         '43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777')
        with self.assertRaises(ValueError):
            canonical({'cost': 1.3})
        self.assertEqual(canonical({'newline': '\n'}), '{"newline":"\\u000a"}')

    def test_hacp_two_peer_delivery(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertTrue(collaboration_demo(temp)['verified'])

    def test_api_auth_and_dashboard(self):
        with tempfile.TemporaryDirectory() as temp:
            original = os.environ.get('QA_DATA_DIR'), os.environ.get('QA_API_TOKEN')
            try:
                os.environ['QA_DATA_DIR'] = temp
                os.environ['QA_API_TOKEN'] = 'long-development-token'
                import importlib
                from services.platform import api
                importlib.reload(api)
                client = TestClient(api.app)
                self.assertEqual(client.get('/engine/runs').status_code, 401)
                auth = {'x-qa-api-token': 'long-development-token'}
                self.assertEqual(client.get('/engine/runs', headers=auth).status_code, 200)
                with agentic_fixture() as (base, oracle):
                    response = client.post('/engine/execute', headers=auth,
                                           json=manifest_for('agentic', base, oracle))
                self.assertEqual(response.status_code, 200, response.text)
                run = response.json()
                self.assertEqual(run['verdict'], 'FAIL')
                self.assertEqual(client.get('/engine/runs/'+run['run_id'], headers=auth).status_code, 200)
                evidence = client.get('/engine/evidence/'+run['evidence_sha256'], headers=auth)
                self.assertEqual(evidence.status_code, 200)
                self.assertEqual(client.get('/graph/summary', headers=auth).status_code, 200)
                self.assertIn('ProofHound', client.get('/dashboard', headers=auth).text)
            finally:
                if original[0] is None: os.environ.pop('QA_DATA_DIR', None)
                else: os.environ['QA_DATA_DIR'] = original[0]
                if original[1] is None: os.environ.pop('QA_API_TOKEN', None)
                else: os.environ['QA_API_TOKEN'] = original[1]

    @unittest.skipUnless(os.getenv('QA_BROWSER_ACCEPTANCE') == '1', 'opt-in real Chromium acceptance')
    def test_chromium_fixture_bridge(self):
        from services.fullstack_qa.browser import verify_browser_retry
        old = os.environ.get('QA_BROWSER_FIXTURE_RELAY')
        try:
            os.environ['QA_BROWSER_FIXTURE_RELAY'] = '1'
            record = verify_browser_retry()
            self.assertTrue(record['browser_executed'])
            self.assertEqual(record['server_charge_count'], 2)
        finally:
            if old is None: os.environ.pop('QA_BROWSER_FIXTURE_RELAY', None)
            else: os.environ['QA_BROWSER_FIXTURE_RELAY'] = old


if __name__ == '__main__':
    unittest.main()

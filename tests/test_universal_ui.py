"""Actual Chromium+HTTP+server-log+independent-oracle universal UI acceptance."""
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import ValidationError

from services.engine.store import Store
from services.universal_ui.discovery import discover
from services.universal_ui.drivers import DriverError, PlaywrightDriver, UnsupportedAction, WebDriver
from services.universal_ui.evidence import EventStream, scrub
from services.universal_ui.runner import execute
from services.universal_ui.spec import validate
from reference_apps.ui_fixture import ui_fixture




def scenario(origin, oracle, log_file):
    return {
        'id': 'end-to-end-checkout', 'project_id': 'fixture', 'origin': origin,
        'oracle_origin': oracle, 'allow_mutations': True, 'fixture_relay': True,
        'log_file': str(log_file), 'log_messages': True, 'screenshots': True,
        'steps': [
            {'name': 'open', 'action': 'goto', 'path': '/'},
            {'name': 'title', 'action': 'assert_title', 'expected': 'QA shop'},
            {'name': 'accessibility', 'action': 'audit_accessibility'},
            {'name': 'click_first', 'action': 'click', 'locator': {'by': 'test_id', 'value': 'buy'}},
            {'name': 'first_visible', 'action': 'wait_for', 'locator': {'by': 'text', 'value': 'Created'}},
            {'name': 'click_retry', 'action': 'click', 'locator': {'by': 'test_id', 'value': 'buy'}},
            {'name': 'backend_state', 'action': 'assert_oracle', 'oracle_path': '/state',
             'pointer': '/charges', 'operator': 'equals', 'expected': 1},
            {'name': 'server_health', 'action': 'assert_no_server_errors'},
            {'name': 'browser_health', 'action': 'assert_no_console_errors'},
            {'name': 'network_health', 'action': 'assert_no_http_errors'},
            {'name': 'screen', 'action': 'screenshot'},
        ]}


@pytest.mark.parametrize('broken,expected', [(False, 'PASS'), (True, 'FAIL')])
def test_real_chromium_ui_server_logs_and_oracle(broken, expected):
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        log = root / 'server.log'
        log.write_text('INFO startup\n')
        with ui_fixture(log, broken=broken) as (origin, oracle):
            spec = scenario(origin, oracle, log)
            with patch.dict(os.environ, {'QA_LOG_ROOT': temp}, clear=False):
                result = execute(spec, root / 'output', local_files=True)
            assert result['verdict'] == expected, result
            assert result['steps_executed'] == len(spec['steps'])
            assert len(result['screenshots']) >= 1
            evidence = Store(root / 'output').evidence_bytes(result['evidence_sha256'])
            assert b'server-secret' not in evidence
            assert b'test@example.com' not in evidence
            assert b'private-screenshots' not in evidence
            observed = json.loads(evidence)
            assert any(e['source'] == 'network' and e.get('path') == '/create' for e in observed['events'])
            assert any(e['source'] == 'server_log' for e in observed['events'])
            assert result['trace_id'] != '0' * 32
            if broken:
                assert any(f['category'] == 'state_mismatch' for f in result['findings'])
                assert any(f['correlated_sources'] == ['server_log'] for f in result['findings'])
                assert any(a['step'] == 'backend_state' and a['status'] == 'FAIL' for a in result['assertions'])
            else:
                assert not result['findings']


def test_discovery_read_only_inventory_and_unapproved_drafts():
    with tempfile.TemporaryDirectory() as temp:
        log = Path(temp) / 'fixture.log'
        log.touch()
        with ui_fixture(log, broken=False) as (origin, oracle):
            inventory = discover({'id': 'crawl', 'origin': origin, 'fixture_relay': True}, max_pages=3)
            assert inventory['read_only']
            assert inventory['page_count'] == 1
            assert inventory['drafts']
            assert inventory['proposed_scenarios_approved'] is False
            assert all(x['status'] == 'PROPOSED_REQUIRES_OWNER_APPROVAL' for x in inventory['drafts'])


def test_owner_boundaries_and_missing_assertions():
    origin = 'http://127.0.0.1:9999'
    template = {'id': 'safe', 'origin': origin, 'steps': [{'name': 'click', 'action': 'click',
                'locator': {'by': 'css', 'value': '#one'}}]}
    with pytest.raises(ValueError, match='mutations'):
        validate(template)
    with pytest.raises(ValueError, match='destructive'):
        validate({**template, 'allow_mutations': True, 'steps': [
            {'name': 'remove', 'action': 'click', 'locator': {'by': 'text', 'value': 'Delete account'}}]})
    with pytest.raises(ValueError, match='log_file'):
        validate({**template, 'allow_mutations': True, 'log_file': '/etc/passwd'})
    with pytest.raises(ValueError, match='origin'):
        validate({'id': 'missing', 'steps': [{'name': 'open', 'action': 'goto', 'path': '/'}]})
    with tempfile.TemporaryDirectory() as temp:
        log = Path(temp) / 'test.log'; log.touch()
        with ui_fixture(log, broken=False) as (origin, oracle):
            result = execute({'id': 'actions-only', 'origin': origin, 'fixture_relay': True,
                              'steps': [{'name': 'open', 'action': 'goto', 'path': '/'}]}, temp)
            assert result['verdict'] == 'INCONCLUSIVE'
    assert 'real' == 'real'


def test_logs_scrub_credential_email_and_query():
    assert scrub('Bearer secret-123 password=pw email=user@example.com http://site/a?key=foo') == (
        'Bearer [REDACTED] password=[REDACTED] email=[EMAIL] http://site/a?[REDACTED]')



def test_auth_env_bearer_header_allows_authorized_fixture_without_secret_leak():
    seen = {'authorized': False}

    class AuthenticatedPage(BaseHTTPRequestHandler):
        def do_GET(self):
            expected = 'Bearer fixture-token-123'
            seen['authorized'] = self.headers.get('Authorization') == expected
            if not seen['authorized']:
                body = b'<!doctype html><title>Denied</title><h1>Denied</h1>'
                self.send_response(401)
            else:
                body = b'<!doctype html><title>Private fixture</title><h1>Ready</h1>'
                self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), AuthenticatedPage)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        spec = {'id': 'auth-env-fixture', 'origin': f'http://127.0.0.1:{server.server_port}',
                'fixture_relay': True, 'auth_env': 'QA_TARGET_TOKEN_AUTH_ENV_FIXTURE',
                'steps': [{'name': 'open', 'action': 'goto', 'path': '/'},
                          {'name': 'title', 'action': 'assert_title', 'expected': 'Private fixture'}]}
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {'QA_TARGET_TOKEN_AUTH_ENV_FIXTURE': 'fixture-token-123'}, clear=False):
                run = execute(spec, temp)
            assert run['verdict'] == 'PASS', run
            assert seen['authorized'] is True
            evidence = Store(temp).evidence_bytes(run['evidence_sha256'])
            assert b'fixture-token-123' not in evidence
            assert b'Authorization' not in evidence
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)



def test_token_leak_redirect_keeps_auth_on_same_origin_and_off_third_party():
    state = {'app_auth': [], 'third_party_auth': []}

    class ThirdParty(BaseHTTPRequestHandler):
        def do_GET(self):
            state['third_party_auth'].append(self.headers.get('Authorization'))
            body = b'leak target'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    third = ThreadingHTTPServer(('127.0.0.1', 0), ThirdParty)
    third_thread = threading.Thread(target=third.serve_forever, daemon=True)
    third_thread.start()

    class RedirectingApp(BaseHTTPRequestHandler):
        def do_GET(self):
            state['app_auth'].append(self.headers.get('Authorization'))
            self.send_response(302)
            self.send_header('Location', f'http://localhost:{third.server_port}/leak')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    app = ThreadingHTTPServer(('127.0.0.1', 0), RedirectingApp)
    app_thread = threading.Thread(target=app.serve_forever, daemon=True)
    app_thread.start()
    driver = None
    try:
        spec = {'id': 'token-leak-redirect', 'origin': f'http://127.0.0.1:{app.server_port}',
                'auth_env': 'QA_TARGET_TOKEN_REDIRECT',
                'steps': [{'name': 'open', 'action': 'goto', 'path': '/redirect'}]}
        with patch.dict(os.environ, {'QA_TARGET_TOKEN_REDIRECT': 'redirect-secret'}, clear=False):
            driver = PlaywrightDriver(spec, EventStream())
            with pytest.raises(Exception):
                driver.navigate('/redirect')
        assert state['app_auth'] == ['Bearer redirect-secret']
        assert all(value is None for value in state['third_party_auth'])
    finally:
        if driver:
            driver.close()
        app.shutdown(); app.server_close(); app_thread.join(timeout=3)
        third.shutdown(); third.server_close(); third_thread.join(timeout=3)


def test_token_leak_relay_subresource_keeps_auth_on_fixture_and_off_third_party():
    state = {'app_auth': [], 'third_party_auth': []}

    class ThirdParty(BaseHTTPRequestHandler):
        def do_GET(self):
            state['third_party_auth'].append(self.headers.get('Authorization'))
            body = b'pixel'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    third = ThreadingHTTPServer(('127.0.0.1', 0), ThirdParty)
    third_thread = threading.Thread(target=third.serve_forever, daemon=True)
    third_thread.start()

    class FixturePage(BaseHTTPRequestHandler):
        def do_GET(self):
            state['app_auth'].append(self.headers.get('Authorization'))
            body = (f'<!doctype html><title>Relay private</title>'
                    f'<h1>Ready</h1><img src="http://localhost:{third.server_port}/pixel" />').encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    app = ThreadingHTTPServer(('127.0.0.1', 0), FixturePage)
    app_thread = threading.Thread(target=app.serve_forever, daemon=True)
    app_thread.start()
    try:
        spec = {'id': 'token-leak-relay', 'origin': f'http://127.0.0.1:{app.server_port}',
                'fixture_relay': True, 'auth_env': 'QA_TARGET_TOKEN_RELAY',
                'steps': [{'name': 'open', 'action': 'goto', 'path': '/'},
                          {'name': 'title', 'action': 'assert_title', 'expected': 'Relay private'}]}
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {'QA_TARGET_TOKEN_RELAY': 'relay-secret'}, clear=False):
                run = execute(spec, temp)
            assert run['verdict'] == 'PASS', run
        assert state['app_auth'] == ['Bearer relay-secret']
        assert all(value is None for value in state['third_party_auth'])
    finally:
        app.shutdown(); app.server_close(); app_thread.join(timeout=3)
        third.shutdown(); third.server_close(); third_thread.join(timeout=3)

def test_unsupported_browser_engine_setup_is_inconclusive_not_infra_error():
    spec = {'id': 'unsupported-engine', 'origin': 'http://127.0.0.1:9',
            'steps': [{'name': 'open', 'action': 'goto', 'path': '/'}]}
    with tempfile.TemporaryDirectory() as temp:
        with patch('services.universal_ui.runner.open_driver', side_effect=UnsupportedAction('browser engine unavailable')):
            run = execute(spec, temp)
    assert run['verdict'] == 'INCONCLUSIVE', run
    assert run['error'] == 'browser engine unavailable'
    assert run['steps_executed'] == 0


def test_auth_env_is_rejected_for_webdriver_until_header_injection_exists():
    with patch.dict(os.environ, {'QA_TARGET_TOKEN_NATIVE': 'native-token'}, clear=False):
        with pytest.raises(ValueError, match='auth_env bearer header injection'):
            validate({'id': 'native-auth', 'driver': 'webdriver',
                      'webdriver_url': 'http://127.0.0.1:4723',
                      'auth_env': 'QA_TARGET_TOKEN_NATIVE',
                      'steps': [{'name': 'ready', 'action': 'assert_title', 'expected': 'Ready'}]})

def test_webdriver_native_missing_origin_is_allowed_but_navigation_not():
    validate({'id': 'native', 'driver': 'webdriver', 'webdriver_url': 'http://127.0.0.1:4723',
              'steps': [{'name': 'observe', 'action': 'assert_visible',
                         'locator': {'by': 'accessibility_id', 'value': 'Home'}, 'expected': True}]})
    with pytest.raises(ValueError):
        validate({'id': 'native', 'driver': 'webdriver', 'webdriver_url': 'http://malicious.net:4723',
                  'steps': [{'name': 'observe', 'action': 'assert_title', 'expected': 'Home'}]})


def test_w3c_webdriver_protocol_against_http_mock():
    """Proves implemented W3C request shapes, not an Appium device certification."""
    state = {'created': False, 'closed': False, 'locators': []}
    element_key = WebDriver.ELEMENT_KEY
    class FakeW3C(BaseHTTPRequestHandler):
        def write(self, payload, status=200):
            body = json.dumps({'value': payload}).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['content-length'])))
            if self.path == '/session':
                state['created'] = True
                self.write({'sessionId': 'synthetic-1', 'capabilities': {}})
            elif self.path in ('/session/synthetic-1/element', '/session/synthetic-1/elements'):
                state['locators'].append(body)
                element = {element_key: 'elem-123'}
                self.write([element] if self.path.endswith('/elements') else element)
            elif self.path.endswith('/click'):
                self.write(None)
            else:
                self.write({'error': 'unknown command'}, 404)
        def do_GET(self):
            if self.path.endswith('/displayed'): self.write(True)
            elif self.path.endswith('/text'): self.write('Ready')
            else: self.write({'error': 'unknown command'}, 404)
        def do_DELETE(self):
            state['closed'] = True
            self.write(None)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), FakeW3C)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    spec = {'id': 'appium-smoke', 'driver': 'webdriver',
            'webdriver_url': f'http://127.0.0.1:{server.server_port}',
            'steps': [{'name': 'visible', 'action': 'assert_visible',
                       'locator': {'by': 'accessibility_id', 'value': 'Home'}, 'expected': True},
                      {'name': 'copy', 'action': 'assert_text',
                       'locator': {'by': 'accessibility_id', 'value': 'Home'}, 'expected': 'Ready'},
                      {'name': 'count', 'action': 'assert_count',
                       'locator': {'by': 'accessibility_id', 'value': 'Home'}, 'expected': 1},
                      {'name': 'hover', 'action': 'hover',
                       'locator': {'by': 'accessibility_id', 'value': 'Home'}}]}
    try:
        with tempfile.TemporaryDirectory() as temp:
            result = execute(spec, temp)
            assert result['verdict'] == 'INCONCLUSIVE'  # Hover explicitly unsupported.
            assert result['steps_executed'] == 4
            assert [x['status'] for x in result['assertions']] == ['PASS', 'PASS', 'PASS']
        assert state['created'] and state['closed']
        assert len(state['locators']) == 3
        assert all(x['using'] == 'accessibility id' for x in state['locators'])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_issue_fingerprints_deduplicate_across_runs_and_offline_report_escapes():
    from services.universal_ui.issues import IssueIndex
    from services.universal_ui.report import render
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        log = root / 'server.log'; log.touch()
        with ui_fixture(log, broken=True) as (origin, oracle):
            spec = scenario(origin, oracle, log)
            with patch.dict(os.environ, {'QA_LOG_ROOT': temp}, clear=False):
                # Deliberately run twice against same fixture to verify issue grouping.
                runs = [execute(spec, root / 'runs', local_files=True) for _ in range(2)]
        assert runs[0]['run_id'] != runs[1]['run_id']
        issues = IssueIndex(root / 'runs').list('fixture')
        assert issues
        assert any(issue['occurrences'] == 2 for issue in issues)
        repeated = next(issue for issue in issues if issue['occurrences'] == 2)
        issue = IssueIndex(root / 'runs').get(repeated['fingerprint'])
        assert len(issue['runs']) == 2
        data = json.loads(Store(root / 'runs').evidence_bytes(runs[0]['evidence_sha256']))
        data['events'].append({'seq': 99, 'at': 'now', 'source': '<script>', 'level': 'info',
                                'message': '<script>alert(1)</script>'})
        html_report = render(runs[0], data)
        assert '<script>' not in html_report
        assert '&lt;script&gt;' in html_report
        assert 'Content-Security-Policy' in html_report
        assert 'Root cause proven?' in html_report


def test_local_api_exposes_ui_runs_issues_and_safe_html_report():
    from fastapi.testclient import TestClient
    import importlib
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        log = root / 'server.log'; log.touch()
        with ui_fixture(log, broken=True) as (origin, oracle):
            spec = scenario(origin, oracle, log)
            # Remote API must reject owner-local sensitive file and baseline references.
            with patch.dict(os.environ, {'QA_DATA_DIR': str(root / 'data'),
                                         'QA_API_TOKEN': 'test-private-api-key',
                                         'QA_LOG_ROOT': temp}, clear=False):
                from services.platform import api
                importlib.reload(api)
                client = TestClient(api.app)
                auth = {'x-qa-api-token': 'test-private-api-key'}
                assert client.post('/ui/execute', headers=auth, json=spec).status_code == 422
                safe = {k: v for k, v in spec.items() if k not in ('log_file', 'log_messages', 'screenshots')}
                safe['steps'] = [s for s in safe['steps'] if s['action'] not in ('screenshot', 'assert_no_server_errors')]
                response = client.post('/ui/execute', headers=auth, json=safe)
                assert response.status_code == 200, response.text
                record = response.json()
                assert record['verdict'] == 'FAIL'
                issues = client.get('/ui/issues', headers=auth)
                assert issues.status_code == 200 and issues.json()
                detail = client.get('/ui/issues/' + issues.json()[0]['fingerprint'], headers=auth)
                assert detail.status_code == 200 and detail.json()['runs']
                report = client.get('/ui/runs/' + record['run_id'] + '/report', headers=auth)
                assert report.status_code == 200
                assert 'Content-Security-Policy' in report.text
                assert record['trace_id'] in report.text
                assert client.get('/ui/issues').status_code == 401
                assert client.get('/ui/runs/' + record['run_id'] + '/report').status_code == 401


def test_event_stream_overflow_is_tracked():
    stream = EventStream(max_events=2)
    for _ in range(5): stream.add('console', 'error', 'test')
    assert stream.dropped() == 3
    assert [e['seq'] for e in stream.snapshot()] == [4, 5]


def test_trace_context_joins_ui_action_and_backend_request():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        log = root / 'trace.log'; log.touch()
        with ui_fixture(log, broken=False) as (origin, oracle):
            spec = scenario(origin, oracle, log)
            spec['propagate_trace'] = True
            with patch.dict(os.environ, {'QA_LOG_ROOT': temp}, clear=False):
                run = execute(spec, root / 'runs', local_files=True)
            assert run['verdict'] == 'PASS'
            assert f'trace_id={run["trace_id"]}' in log.read_text()
            evidence = json.loads(Store(root / 'runs').evidence_bytes(run['evidence_sha256']))
            assert evidence['trace_propagation_enabled']
            assert any(event['source'] == 'server_log' and run['trace_id'] in event.get('message', '')
                       for event in evidence['events'])


def test_webdriver_trace_header_injection_fails_closed():
    with pytest.raises(ValueError, match='WebDriver cannot inject'):
        validate({'id': 'native', 'driver': 'webdriver', 'webdriver_url': 'http://127.0.0.1:4723',
                  'propagate_trace': True,
                  'steps': [{'name': 'ready', 'action': 'assert_title', 'expected': 'Ready'}]})


def test_static_source_candidate_requires_observed_matching_route():
    from services.graph.graph import Graph
    from services.discovery.project import discover_project
    from services.universal_ui.localize import attach_candidates
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / 'routes.py').write_text("@app.post('/create')\ndef create():\n    pass\n@app.get('/unrelated')\ndef unrelated():\n    pass\n")
        graph = Graph(root / 'graph.sqlite3')
        summary = discover_project(root, graph, project='fixture', version='v1')
        assert summary['routes'] == 2
        findings = [{'step': 'charge', 'action': 'assert_oracle', 'category': 'state_mismatch',
                     'event_seq_start': 3, 'event_seq_end': 10}]
        events = [{'seq': 5, 'source': 'network', 'method': 'POST', 'path': '/create'}]
        attach_candidates(graph, 'fixture', 'v1', findings, events)
        assert len(findings[0]['source_candidates']) == 1
        candidate = findings[0]['source_candidates'][0]
        assert candidate['file'] == 'routes.py'
        assert candidate['method'] == 'POST'
        assert candidate['confirmed_cause'] is False
        findings[0]['event_seq_start'] = 100
        attach_candidates(graph, 'fixture', 'v1', findings, events)
        assert findings[0]['source_candidates'] == []


def test_autonomous_read_only_ui_audit_runs_bounded_health_checks():
    from services.universal_ui.autopilot import audit
    with tempfile.TemporaryDirectory() as temp:
        log = Path(temp) / 'console.log'; log.touch()
        with ui_fixture(log, broken=False) as (origin, oracle):
            result = audit({'id': 'crawl', 'origin': origin, 'fixture_relay': True},
                           Path(temp) / 'runs', max_pages=2)
            assert result['verdict'] == 'PASS', result
            assert result['page_count'] == 1
            assert result['business_logic_verified'] is False
            assert result['runs'][0]['evidence_sha256']
            assert result['inventory']['proposed_scenarios_approved'] is False
            with pytest.raises(ValueError, match='mutation'):
                audit({'id': 'crawl', 'origin': origin, 'allow_mutations': True,
                       'fixture_relay': True}, temp)


def test_ui_accessibility_and_javascript_errors_are_evidence_not_guesses():
    class BadMarkup(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'''<!doctype html><title>Bad</title><img src="data:image/png;base64,iVBORw0KGgo=" />
                <input id="secret"/><button aria-label="OK">Go</button>
                <script>console.error('synthetic UI failure');</script>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), BadMarkup)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        spec = {'id': 'page-health', 'origin': f'http://127.0.0.1:{server.server_port}',
                'fixture_relay': True, 'steps': [
                    {'name': 'navigate', 'action': 'goto', 'path': '/'},
                    {'name': 'console', 'action': 'assert_no_console_errors'},
                    {'name': 'accessibility', 'action': 'audit_accessibility'}]}
        with tempfile.TemporaryDirectory() as temp:
            run = execute(spec, temp)
            assert run['verdict'] == 'FAIL', run
            assert all(a['status'] == 'FAIL' for a in run['assertions'])
            assert {f['category'] for f in run['findings']} >= {
                'accessibility_heuristic', 'concurrent_runtime_error'}
            observation = json.loads(Store(temp).evidence_bytes(run['evidence_sha256']))
            assert any(x['source'] == 'console' and x['level'] == 'error' for x in observation['events'])
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def test_pixel_baseline_comparison_and_private_failure_screenshot():
    import io
    from PIL import Image
    from services.universal_ui.evidence import image_difference
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        baseline = root / 'baseline.png'
        image = Image.new('RGB', (1280, 800), (255, 0, 0))
        image.save(baseline)
        file_content = baseline.read_bytes()
        assert image_difference(file_content, baseline)['ratio'] == 0.0
        changed = Image.new('RGB', (1280, 800), (0, 255, 0))
        buffer = io.BytesIO(); changed.save(buffer, format='PNG')
        assert image_difference(buffer.getvalue(), baseline)['ratio'] == 1.0
        log = root / 'server.log'; log.touch()
        with ui_fixture(log, broken=False) as (origin, oracle):
            spec = {'id': 'visual', 'origin': origin, 'fixture_relay': True, 'screenshots': True,
                    'steps': [{'name': 'open', 'action': 'goto', 'path': '/'},
                              {'name': 'pixel', 'action': 'assert_visual',
                               'baseline': str(baseline), 'threshold': 0.0}]}
            with patch.dict(os.environ, {'QA_BASELINE_ROOT': temp}, clear=False):
                run = execute(spec, root / 'runs', local_files=True)
            assert run['verdict'] == 'FAIL'
            assert run['screenshots']
            assert run['findings'][0]['category'] == 'visual_regression'
            assert (root / 'runs' / 'private-screenshots' / run['run_id']).exists()
            with pytest.raises(ValueError, match='baseline path'):
                validate(spec, local_files=False)


def test_end_to_end_browser_otel_export_is_protobuf_and_matches_trace_id():
    """Actual UI child process exports OTLP, not just an 'export configured' flag."""
    import subprocess
    import sys
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
    captured = []
    class OTLP(BaseHTTPRequestHandler):
        def do_POST(self):
            captured.append((self.path, self.headers.get('Content-Type'),
                             self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-protobuf')
            self.send_header('Content-Length', '0')
            self.end_headers()
        def log_message(self, *args): pass
    collector = ThreadingHTTPServer(('127.0.0.1', 0), OTLP)
    thread = threading.Thread(target=collector.serve_forever, daemon=True); thread.start()
    try:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            log = root / 'qa.log'; log.touch()
            with ui_fixture(log, broken=False) as (origin, oracle):
                spec = scenario(origin, oracle, log)
                path = root / 'scenario.json'; path.write_text(json.dumps(spec))
                repo = Path(__file__).resolve().parents[1]
                environment = {**os.environ, 'QA_LOG_ROOT': temp}
                subprocess_result = subprocess.run([
                    sys.executable, '-m', 'services.universal_ui.cli', str(path), '--output', str(root / 'out'),
                    '--otlp-endpoint', f'http://127.0.0.1:{collector.server_port}/v1/traces'],
                    cwd=repo, env=environment, capture_output=True, text=True, timeout=40)
                assert subprocess_result.returncode == 0, subprocess_result.stderr
                result = json.loads(subprocess_result.stdout)
                assert result['verdict'] == 'PASS'
                assert captured
                spans = []
                for endpoint, ctype, payload in captured:
                    assert endpoint == '/v1/traces'
                    assert ctype == 'application/x-protobuf'
                    proto = ExportTraceServiceRequest.FromString(payload)
                    spans.extend((s.name, s.trace_id.hex()) for resource in proto.resource_spans
                                 for scope in resource.scope_spans for s in scope.spans)
                assert ('qa.ui.run', result['trace_id']) in spans
                assert sum(1 for name, trace_id in spans if name == 'qa.ui.step' and trace_id == result['trace_id']) == len(spec['steps'])
    finally:
        collector.shutdown(); collector.server_close(); thread.join(timeout=3)


def test_distributed_span_lookup_uses_trace_id_not_runner_only_attributes():
    import sqlite3
    from services.universal_ui.runner import _trace_present
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'telemetry.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE spans(trace_id TEXT, name TEXT, run_id TEXT)')
            db.execute('INSERT INTO spans VALUES (?,?,?)', ('a' * 32, 'backend.charge', None))
        assert _trace_present(temp, 'a' * 32, 'backend.charge') is True
        assert _trace_present(temp, 'b' * 32, 'backend.charge') is False
        assert _trace_present(temp, 'a' * 32, 'backend.refund') is False
        assert _trace_present(Path(temp) / 'missing', 'a' * 32, 'backend.charge') is None

"""Per-step correlation: synthetic span tree plus a real Chromium + OTLP receiver run."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from services.engine.store import Store
from services.telemetry.correlate import correlate, main

TRACE = 'ab' * 16


def _record(root, *, messages=True):
    observed = {
        'steps': [{'step': 'open', 'action': 'goto', 'status': 'PASS', 'source': 'ui_driver',
                   'event_seq_start': 0, 'event_seq_end': 2},
                  {'step': 'buy', 'action': 'click', 'status': 'PASS', 'source': 'ui_driver',
                   'event_seq_start': 2, 'event_seq_end': 6}],
        'events': [
            {'seq': 1, 'source': 'runner', 'level': 'info'},
            {'seq': 2, 'source': 'network', 'level': 'info', 'status': 200, 'method': 'GET', 'path': '/'},
            {'seq': 3, 'source': 'runner', 'level': 'info'},
            {'seq': 4, 'source': 'network', 'level': 'info', 'status': 200, 'method': 'POST', 'path': '/create'},
            {'seq': 5, 'source': 'server_log', 'level': 'info', 'message': 'INFO trace_id=' + TRACE},
            {'seq': 6, 'source': 'server_log', 'level': 'error', 'message': 'ERROR span_id=' + '22' * 8},
            {'seq': 7, 'source': 'server_log', 'level': 'error', 'message': 'ERROR later, unrelated'},
        ],
        'events_dropped': 0, 'trace_propagation_enabled': True, 'event_messages_opted_in': messages,
    }
    if not messages:
        for event in observed['events']:
            event.pop('message', None)
    return Store(root).save({'run_id': 'r-1', 'project_id': 'p', 'scenario_id': 's', 'version': 'v',
                             'kind': 'universal-ui', 'verdict': 'FAIL', 'trace_id': TRACE,
                             'created_at': 'now', 'observed': observed})


def _spans(root, rows):
    with sqlite3.connect(Path(root) / 'telemetry.sqlite3') as db:
        db.execute('CREATE TABLE spans(trace_id TEXT, span_id TEXT, parent_id TEXT, name TEXT, service TEXT,'
                   ' run_id TEXT, start_ns INTEGER, end_ns INTEGER, attributes TEXT)')
        db.executemany('INSERT INTO spans VALUES (?,?,?,?,?,?,?,?,?)', rows)


def test_trace_linked_versus_time_window_joins():
    with tempfile.TemporaryDirectory() as temp:
        record = _record(temp)
        _spans(temp, [
            (TRACE, '00' * 8, '', 'qa.ui.run', 'runner', 'r-1', 0, 10, '{}'),
            (TRACE, '11' * 8, '00' * 8, 'qa.ui.step', 'runner', 'r-1', 1, 2, '{"qa.step.name": "open"}'),
            (TRACE, '22' * 8, '00' * 8, 'qa.ui.step', 'runner', 'r-1', 3, 9, '{"qa.step.name": "buy"}'),
            (TRACE, '33' * 8, '22' * 8, 'POST /create', 'shop', None, 4, 8, '{}'),
            (TRACE, '44' * 8, '33' * 8, 'db.insert charge', 'shop', None, 5, 6, '{}'),
            (TRACE, '55' * 8, 'ff' * 8, 'cron.cleanup', 'shop', None, 5, 6, '{}'),
        ])
        before = (Path(temp) / 'telemetry.sqlite3').read_bytes()
        result = correlate(record, temp)
        assert (Path(temp) / 'telemetry.sqlite3').read_bytes() == before  # read-only
        open_step, buy = result['steps']
        assert [n['path'] for n in open_step['network']] == ['/']
        assert [n['path'] for n in buy['network']] == ['/create']
        assert all(n['join'] == 'time_window' for n in buy['network'])
        assert {s['name'] for s in buy['backend_spans']} == {'POST /create', 'db.insert charge'}
        assert all(s['join'] == 'trace_linked' for s in buy['backend_spans'])
        assert open_step['backend_spans'] == []
        bases = {log['seq']: log.get('trace_basis') for log in buy['server_logs']}
        assert bases == {5: 'run trace_id in log line', 6: 'step span_id in log line'}
        assert [s['name'] for s in result['backend_spans_outside_steps']] == ['cron.cleanup']
        assert [e['seq'] for e in result['unattributed_events']] == [7]
        assert result['limits'] == []


def test_missing_telemetry_and_messages_are_stated_as_limits():
    with tempfile.TemporaryDirectory() as temp:
        record = _record(temp, messages=False)
        result = correlate(record, temp)
        assert result['telemetry'].startswith('no telemetry.sqlite3')
        assert any('backend span joins unavailable' in x for x in result['limits'])
        assert any('log messages not retained' in x for x in result['limits'])
        logs = result['steps'][1]['server_logs']
        assert logs and all(x['join'] == 'time_window' for x in logs)
        assert main(['missing-run', '--output', temp]) == 2


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def test_real_ui_run_through_live_otlp_receiver_is_correlated_per_step():
    import uvicorn
    from reference_apps.ui_fixture import ui_fixture
    from services.telemetry.receiver import app
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        out = root / 'out'
        out.mkdir()
        old = os.environ.get('QA_DATA_DIR')
        os.environ['QA_DATA_DIR'] = str(out)  # receiver indexes into the runner's output dir
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started: break
                time.sleep(0.05)
            log = root / 'qa.log'
            log.touch()
            with ui_fixture(log, broken=True) as (origin, oracle):
                spec = {'id': 'checkout', 'project_id': 'demo', 'origin': origin, 'oracle_origin': oracle,
                        'allow_mutations': True, 'propagate_trace': True, 'log_file': str(log),
                        'log_messages': True,
                        'steps': [{'name': 'open', 'action': 'goto', 'path': '/'},
                                  {'name': 'buy', 'action': 'click', 'locator': {'by': 'test_id', 'value': 'buy'}},
                                  {'name': 'done', 'action': 'wait_for', 'locator': {'by': 'text', 'value': 'Created'}},
                                  {'name': 'retry', 'action': 'click', 'locator': {'by': 'test_id', 'value': 'buy'}},
                                  {'name': 'state', 'action': 'assert_oracle', 'oracle_path': '/state',
                                   'pointer': '/charges', 'operator': 'equals', 'expected': 1},
                                  {'name': 'server_errors', 'action': 'assert_no_server_errors'}]}
                scenario = root / 'scenario.json'
                scenario.write_text(json.dumps(spec))
                repo = Path(__file__).resolve().parents[1]
                run = subprocess.run([sys.executable, '-m', 'services.universal_ui.cli', str(scenario),
                                      '--output', str(out), '--otlp-endpoint', f'http://127.0.0.1:{port}/v1/traces'],
                                     cwd=repo, env={**os.environ, 'QA_LOG_ROOT': temp},
                                     capture_output=True, text=True, timeout=60)
            assert run.returncode == 0, run.stderr
            record = json.loads(run.stdout)
            assert record['verdict'] == 'FAIL'
            result = correlate(record, out)
            assert result['telemetry'] == 'indexed'
            by_step = {s['step']: s for s in result['steps']}
            assert all(s['step_span_id'] for s in result['steps'])  # every step span was indexed
            linked_logs = [x for s in ('buy', 'done', 'retry', 'state') for x in by_step[s]['server_logs']
                           if x['join'] == 'trace_linked']
            assert linked_logs, result  # backend log lines carry the propagated trace ID
            assert any(n.get('method') == 'POST' for s in ('buy', 'done', 'retry') for n in by_step[s]['network'])
            # The fixture backend is not OTel-instrumented: no backend spans, and that is not invented.
            assert all(s['backend_spans'] == [] for s in result['steps'])
            cli = subprocess.run([sys.executable, '-m', 'services.telemetry.correlate', record['run_id'],
                                  '--output', str(out)], cwd=repo, capture_output=True, text=True, timeout=30)
            assert cli.returncode == 0 and json.loads(cli.stdout)['run_id'] == record['run_id']
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            if old is None: os.environ.pop('QA_DATA_DIR', None)
            else: os.environ['QA_DATA_DIR'] = old

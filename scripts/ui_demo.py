"""Run a full UI+logs+oracle benchmark without external applications or accounts."""
import json
import os
import tempfile
from pathlib import Path

from reference_apps.ui_fixture import ui_fixture
from services.engine.store import Store
from services.universal_ui.report import render
from services.universal_ui.runner import execute


def manifest(origin, oracle, log):
    return {'id': 'checkout-e2e', 'project_id': 'demo', 'version': 'fixture-v1',
            'origin': origin, 'oracle_origin': oracle, 'log_file': str(log),
            'log_messages': True, 'fixture_relay': True, 'allow_mutations': True,
            'propagate_trace': True,
            'screenshots': True,
            'steps': [
                {'name': 'open', 'action': 'goto', 'path': '/'},
                {'name': 'heading', 'action': 'assert_title', 'expected': 'QA shop'},
                {'name': 'accessibility', 'action': 'audit_accessibility'},
                {'name': 'create', 'action': 'click', 'locator': {'by': 'test_id', 'value': 'buy'}},
                {'name': 'confirm', 'action': 'wait_for', 'locator': {'by': 'text', 'value': 'Created'}},
                {'name': 'retry', 'action': 'click', 'locator': {'by': 'test_id', 'value': 'buy'}},
                {'name': 'verify_real_state', 'action': 'assert_oracle', 'oracle_path': '/state',
                 'pointer': '/charges', 'operator': 'equals', 'expected': 1},
                {'name': 'server_errors', 'action': 'assert_no_server_errors'},
                {'name': 'js_errors', 'action': 'assert_no_console_errors'},
                {'name': 'http_errors', 'action': 'assert_no_http_errors'},
            ]}


def demo(output='.local-runs/ui-demo'):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    results = []
    old_log_root = os.environ.get('QA_LOG_ROOT')
    try:
        os.environ['QA_LOG_ROOT'] = str(root)
        for broken in (False, True):
            log = root / ('defective.log' if broken else 'corrected.log')
            log.touch()
            with ui_fixture(log, broken=broken) as (origin, oracle):
                spec = manifest(origin, oracle, log)
                record = execute(spec, root, local_files=True)
                observed = json.loads(Store(root).evidence_bytes(record['evidence_sha256']))
                name = 'defective' if broken else 'corrected'
                report = root / (name + '.html')
                report.write_text(render(record, observed))
                results.append({'fixture': name, 'expected': 'FAIL' if broken else 'PASS',
                                'verdict': record['verdict'], 'run_id': record['run_id'],
                                'trace_id': record['trace_id'],
                                'findings': [x['category'] for x in record['findings']],
                                'report': str(report)})
    finally:
        if old_log_root is None: os.environ.pop('QA_LOG_ROOT', None)
        else: os.environ['QA_LOG_ROOT'] = old_log_root
    checks = all(entry['verdict'] == entry['expected'] for entry in results)
    output = {'results': results, 'expected_verdicts_matched': checks,
              'fixture_relay': True, 'native_chromium_networking_verified': False}
    (root / 'summary.json').write_text(json.dumps(output, indent=2) + '\n')
    return output


if __name__ == '__main__':
    result = demo()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['expected_verdicts_matched'] else 1)

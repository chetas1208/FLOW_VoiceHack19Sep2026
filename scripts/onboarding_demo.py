"""End-to-end demo on an app the engine has no specific code for (reference_apps/lending_library).

1. Onboard release v2 read-only: discover pages, forms and controls behind a bearer token.
2. Propose workflows; an explicit owner approval turns one mutating draft into a test.
3. Execute through Chromium while tailing the server log and receiving OTLP spans
   (runner spans and instrumented backend spans) in a live receiver.
4. Verify state through the independent oracle: release v2 has a lost-write defect
   that still shows "Reserved" in the UI.
5. Correlate each step with network, log and span evidence; write a reproducible bug report.
6. Onboard release v3 (defect fixed, /loans changed), diff against v2, select regressions
   (changed pages + previously failing), re-run them, and require PASS.

Everything runs on loopback with synthetic data. Output: .local-runs/onboarding-demo/.
"""
import json
import os
import shutil
import socket
import threading
import time
from pathlib import Path

from reference_apps.lending_library import lending_library
from services.engine.store import Store
from services.telemetry.correlate import correlate
from services.universal_ui import bugreport
from services.universal_ui.onboard import approve, onboard, select_regressions
from services.universal_ui.report import render as render_html
from services.universal_ui.runner import execute

TOKEN_ENV = 'QA_TARGET_TOKEN_LIBRARY_DEMO'
TARGET_WORKFLOW = 'form-catalog-reserve-form-b2'  # boundary variant: reserving the last copy


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _receiver(output):
    import uvicorn
    from services.telemetry.receiver import app
    os.environ['QA_DATA_DIR'] = str(output)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server, thread, f'http://127.0.0.1:{port}/v1/traces'


def owner_approval(oracle, log):
    """What an application owner supplies; the engine never invents these expectations."""
    return {'allow_mutations': True, 'oracle_origin': oracle, 'log_file': str(log), 'log_messages': True,
            'propagate_trace': True,
            'ui_checks': [{'name': 'ui_claims_success', 'action': 'assert_text',
                           'locator': {'by': 'id', 'value': 'status'}, 'expected': 'Reserved'}],
            'oracle_checks': [
                {'oracle_path': '/state', 'pointer': '/reservations', 'operator': 'equals', 'expected': 1},
                {'oracle_path': '/state', 'pointer': '/available/b2', 'operator': 'equals', 'expected': 0}]}


def _run(scenario, output, endpoint, name):
    record = execute(scenario, output, endpoint, local_files=True)
    observed = json.loads(Store(output).evidence_bytes(record['evidence_sha256']))
    correlation = correlate(record, output)
    (output / f'{name}.html').write_text(render_html(record, observed))
    (output / f'{name}.correlation.json').write_text(json.dumps(correlation, indent=2))
    return record, correlation


def demo(output='.local-runs/onboarding-demo'):
    saved = {k: os.environ.get(k) for k in ('QA_LOG_ROOT', 'QA_DATA_DIR', TOKEN_ENV)}
    try:
        return _demo(output)
    finally:
        for key, value in saved.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def _demo(output):
    output = Path(output).resolve()
    shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True)
    os.environ['QA_LOG_ROOT'] = str(output)
    os.environ[TOKEN_ENV] = 'synthetic-staging-token'  # stands in for an owner-provisioned test credential
    server, thread, endpoint = _receiver(output)
    summary = {'app': 'reference_apps/lending_library.py', 'phases': {}}
    try:
        # Phase 1: release v2, as delivered (contains the defect).
        log = output / 'v2-server.log'
        log.touch()
        with lending_library(log, broken=True, token=os.environ[TOKEN_ENV], release='v2',
                             otlp_endpoint=endpoint) as (origin, oracle):
            base = {'id': 'library', 'project_id': 'library', 'version': 'v2', 'origin': origin, 'auth_env': TOKEN_ENV}
            v2 = onboard(base, output, max_pages=8, drafts_dir=output / 'drafts-v2')
            workflows = {w['id']: w for w in v2['workflows']}
            approval = owner_approval(oracle, log)
            (output / 'owner-approval.json').write_text(json.dumps({**approval, 'approved_workflow': TARGET_WORKFLOW,
                                                                    'oracle_origin': 'loopback fixture'}, indent=2))
            scenario = approve(workflows[TARGET_WORKFLOW], {**approval, 'version': 'v2'})
            (output / 'approved-scenario.json').write_text(json.dumps(scenario, indent=2))
            record, correlation = _run(scenario, output, endpoint, 'v2-defect')
            (output / 'bug-report.md').write_text(bugreport.render(record, scenario, correlation))
            smoke = [execute(w['scenario'], output, endpoint, local_files=True)['verdict']
                     for w in v2['workflows'] if w.get('runnable_without_approval')]
        spans = [b for s in correlation['steps'] for b in s['backend_spans']]
        summary['phases']['v2'] = {
            'onboarding': v2['summary'], 'skipped_unsafe_links': v2['skipped_unsafe_links'],
            'workflows': [{k: w.get(k) for k in ('id', 'kind', 'status', 'variant')} for w in v2['workflows']],
            'approved_workflow': TARGET_WORKFLOW, 'verdict': record['verdict'], 'run_id': record['run_id'],
            'trace_id': record['trace_id'],
            'failed_checks': [a['step'] for a in record['assertions'] if a['status'] == 'FAIL'],
            'ui_claimed_success': any(a['step'] == 'ui_claims_success' and a['status'] == 'PASS' for a in record['assertions']),
            'backend_spans_trace_linked': sorted({s['name'] for s in spans}),
            'correlation_limits': correlation['limits'], 'navigation_smoke_verdicts': smoke,
            'bug_report': str(output / 'bug-report.md')}

        # Phase 2: release v3 (defect fixed, /loans changed).
        log = output / 'v3-server.log'
        log.touch()
        with lending_library(log, broken=False, token=os.environ[TOKEN_ENV], release='v3',
                             otlp_endpoint=endpoint) as (origin, oracle):
            base = {'id': 'library', 'project_id': 'library', 'version': 'v3', 'origin': origin, 'auth_env': TOKEN_ENV}
            v3 = onboard(base, output, max_pages=8, drafts_dir=output / 'drafts-v3')
            failing = {TARGET_WORKFLOW} if record['verdict'] == 'FAIL' else set()
            selection = select_regressions(v3.get('changes', {}), v3['workflows'], failing)
            approval = owner_approval(oracle, log)
            workflows = {w['id']: w for w in v3['workflows']}
            reruns = {}
            for item in selection['selected']:
                workflow = workflows[item['id']]
                scenario = (approve(workflow, {**approval, 'version': 'v3'}) if workflow.get('mutating')
                            else workflow['scenario'])
                rerun, rerun_correlation = _run(scenario, output, endpoint, 'v3-' + item['id'])
                reruns[item['id']] = {'verdict': rerun['verdict'], 'reasons': item['reasons'], 'run_id': rerun['run_id'],
                                      'backend_spans': sorted({b['name'] for s in rerun_correlation['steps']
                                                               for b in s['backend_spans']})}
        summary['phases']['v3'] = {'changes': v3.get('changes'), 'selection': selection, 'reruns': reruns}
    finally:
        server.should_exit = True
        thread.join(timeout=5)
    v2p, v3p = summary['phases']['v2'], summary['phases']['v3']
    summary['checks'] = {
        'defect_detected_by_independent_oracle': v2p['verdict'] == 'FAIL' and any(s.startswith('oracle') for s in v2p['failed_checks']),
        'ui_claimed_success_despite_defect': v2p['ui_claimed_success'],
        'destructive_link_not_followed': '/account/delete' in v2p['skipped_unsafe_links'],
        'backend_spans_trace_linked': 'POST /api/reservations' in v2p['backend_spans_trace_linked'],
        'changed_page_detected': '/loans' in (v3p['changes'] or {}).get('pages_changed', []),
        'failing_workflow_reselected': TARGET_WORKFLOW in v3p['reruns'],
        'regressions_pass_after_fix': bool(v3p['reruns']) and all(r['verdict'] == 'PASS' for r in v3p['reruns'].values()),
    }
    summary['all_checks_passed'] = all(summary['checks'].values())
    summary['limits'] = ['single synthetic reference app on loopback; not evidence of general accuracy',
                         'the owner approval (expected outcomes, oracle) is supplied by this script acting as owner',
                         'self-verified by one agent after the second peer became unavailable']
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


if __name__ == '__main__':
    result = demo()
    print(json.dumps({'checks': result['checks'], 'all_checks_passed': result['all_checks_passed']}, indent=2))
    raise SystemExit(0 if result['all_checks_passed'] else 1)

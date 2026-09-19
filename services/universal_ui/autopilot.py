"""Consent-bounded autonomous read-only UI audits from discovered routes.

No LLM judgment, guesses of expected business logic or automatic form submission.
A configured owner oracle is needed for business E2E claims.
"""
import hashlib

from services.universal_ui.discovery import discover
from services.universal_ui.runner import execute
from services.universal_ui.spec import validate


def audit(spec, output='.local-runs', *, max_pages=10, local_files=False, graph=None, otlp_endpoint=None):
    if spec.get('allow_mutations') or spec.get('allow_destructive'):
        raise ValueError('autonomous discovery never accepts mutation permissions')
    initial = {k: v for k, v in spec.items() if k in ('id', 'project_id', 'version', 'driver',
               'origin', 'browser', 'fixture_relay', 'viewport', 'timeout_ms',
               'propagate_trace')}
    initial['steps'] = [{'name': 'landing', 'action': 'goto', 'path': '/'}]
    validate(initial)
    inventory = discover(initial, max_pages=max_pages, graph=graph)
    runs = []
    for page in inventory['pages']:
        if page.get('status') == 'UNAVAILABLE':
            runs.append({'path': page['path'], 'verdict': 'INCONCLUSIVE', 'reason': 'page unavailable'})
            continue
        page_id = hashlib.sha256(page['path'].encode()).hexdigest()[:12]
        scenario = {**initial, 'id': 'audit-' + page_id, 'steps': [
            {'name': 'navigate', 'action': 'goto', 'path': page['path']},
            {'name': 'page_errors', 'action': 'assert_no_page_errors'},
            {'name': 'console', 'action': 'assert_no_console_errors'},
            {'name': 'http', 'action': 'assert_no_http_errors'},
            {'name': 'accessibility', 'action': 'audit_accessibility'},
        ]}
        if spec.get('log_file'):
            scenario['log_file'] = spec['log_file']
            scenario['log_messages'] = spec.get('log_messages', False)
            scenario['steps'].append({'name': 'server_errors', 'action': 'assert_no_server_errors'})
        if spec.get('screenshots'):
            scenario['screenshots'] = True
        result = execute(scenario, output, otlp_endpoint, local_files=local_files, graph=graph)
        runs.append({'path': page['path'], 'run_id': result['run_id'], 'verdict': result['verdict'],
                     'evidence_sha256': result['evidence_sha256'], 'trace_id': result['trace_id'],
                     'finding_count': len(result['findings'])})
    verdicts = [r['verdict'] for r in runs]
    overall = ('INFRA_ERROR' if 'INFRA_ERROR' in verdicts else
               'FAIL' if 'FAIL' in verdicts else
               'INCONCLUSIVE' if 'INCONCLUSIVE' in verdicts or not verdicts or inventory['truncated']
               else 'PASS')
    return {'verdict': overall, 'mode': 'read-only-ui-health-audit', 'page_count': len(runs),
            'truncated': inventory['truncated'], 'runs': runs,
            'business_logic_verified': False, 'inventory': inventory}

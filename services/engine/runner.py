"""Owner-authorized HTTP black-box QA with OTLP spans and independent assertions.

Never runs submitted code, follows redirects, or exposes raw arbitrary responses in evidence.
The state oracle is independently queried rather than trusting a model's final message.
"""
import json
import os
from uuid import uuid4
import httpx
from opentelemetry import trace
from services.engine.manifest import approved_base_url, validate_manifest
from services.engine.store import Store, utc
from services.runtime.wave1 import configure_telemetry

MISSING = object()
MAX_RESPONSE = 1_048_576


def resolve_pointer(body, pointer):
    if pointer == '':
        return body
    current = body
    for token in pointer.split('/')[1:]:
        key = token.replace('~1', '/').replace('~0', '~')
        try:
            if isinstance(current, list):
                if not key.isascii() or not key.isdigit():
                    return MISSING
                current = current[int(key)]
            elif isinstance(current, dict):
                current = current[key]
            else:
                return MISSING
        except (IndexError, KeyError, ValueError):
            return MISSING
    return current


def assess(assertion, step):
    op = assertion['operator']
    if op == 'status_equals':
        actual = step['status']
    elif step['json'] is MISSING:
        return {'id': assertion['id'], 'status': 'INCONCLUSIVE', 'reason': 'response is not JSON'}
    else:
        actual = resolve_pointer(step['json'], assertion.get('pointer', ''))
    expected = assertion['expected']
    try:
        if op == 'exists':
            passed = (actual is not MISSING) is expected if isinstance(expected, bool) else False
        elif actual is MISSING:
            return {'id': assertion['id'], 'status': 'FAIL', 'reason': 'JSON pointer missing'}
        elif op == 'equals' or op == 'status_equals':
            passed = type(actual) is type(expected) and actual == expected
        elif op == 'not_equals':
            passed = actual != expected
        elif op == 'length_equals':
            passed = isinstance(actual, (list, dict, str)) and isinstance(expected, int) and len(actual) == expected
        elif op == 'contains':
            passed = (isinstance(actual, (list, str, dict)) and expected in actual)
        elif op == 'less_or_equal':
            passed = type(actual) in (int, float) and type(expected) in (int, float) and actual <= expected
        else:
            raise ValueError('unknown assertion operator')
    except (TypeError, ValueError):
        passed = False
    # Do not persist raw actual values; they may contain sensitive customer data.
    return {'id': assertion['id'], 'status': 'PASS' if passed else 'FAIL',
            'reason': 'assertion satisfied' if passed else 'expected property not satisfied',
            'source': 'external_state_probe' if step['target'] == 'oracle' else 'application_response'}


def request_step(client, manifest, step, timeout):
    target = step.get('target', 'application')
    base = approved_base_url(manifest['oracle_base_url'] if target == 'oracle' else manifest['base_url'])
    url = base + step['path']
    headers = dict(step.get('headers', {}))
    headers.setdefault('Accept', 'application/json')
    credential_field = 'oracle_auth_env' if target == 'oracle' else 'auth_env'
    if credential_field in manifest:
        token = os.getenv(manifest[credential_field])
        if not token:
            raise RuntimeError('configured endpoint credential is unavailable')
        headers['Authorization'] = 'Bearer ' + token
    # The request JSON is intentionally not included in evidence or span attributes.
    with client.stream(step['method'], url, json=step.get('json') if 'json' in step else None,
                       headers=headers, timeout=timeout, follow_redirects=False) as response:
        buf = bytearray()
        for chunk in response.iter_bytes():
            buf.extend(chunk)
            if len(buf) > MAX_RESPONSE:
                raise RuntimeError('response size exceeds 1MiB limit')
        try:
            body = json.loads(buf)
        except (ValueError, UnicodeError):
            body = MISSING
        return {'status': response.status_code, 'json': body, 'target': target,
                'size_bytes': len(buf), 'method': step['method'], 'path': step['path']}


def execute(manifest, output='.local-runs', otlp_endpoint=None, graph=None):
    validate_manifest(manifest)
    timeout = manifest.get('timeout_seconds', 5)
    store = Store(output)
    endpoint = otlp_endpoint if otlp_endpoint is not None else os.getenv('QA_OTLP_TRACES_ENDPOINT')
    provider, tracer = configure_telemetry(endpoint)
    run_id = str(uuid4())
    responses = {}
    observations = []
    assertions = []
    trace_id = '0' * 32
    verdict = 'INFRA_ERROR'
    error = None
    try:
        with tracer.start_as_current_span('qa.run', attributes={
            'qa.run.id': run_id, 'qa.scenario.id': manifest['id'],
            'qa.project.id': manifest.get('project_id', 'local'),
            'qa.kind': manifest.get('kind', 'fullstack')}) as parent:
            trace_id = f'{parent.get_span_context().trace_id:032x}'
            with httpx.Client(trust_env=False, follow_redirects=False) as client:
                for step in manifest['steps']:
                    with tracer.start_as_current_span('qa.http_step', attributes={
                        'qa.run.id': run_id, 'qa.step.name': step['name'],
                        'http.request.method': step['method'], 'qa.step.target': step.get('target', 'application')}) as span:
                        try:
                            record = request_step(client, manifest, step, timeout)
                        except (httpx.HTTPError, RuntimeError, OSError) as exc:
                            error = f'{type(exc).__name__}: request or response failed'
                            span.record_exception(exc)
                            span.set_attribute('qa.step.infra_error', True)
                            break
                        responses[step['name']] = record
                        span.set_attribute('http.response.status_code', record['status'])
                        observations.append({'step': step['name'], 'method': record['method'],
                                             'path': record['path'], 'status': record['status'],
                                             'json_valid': record['json'] is not MISSING,
                                             'size_bytes': record['size_bytes'], 'target': record['target']})
            if error is None:
                with tracer.start_as_current_span('qa.independent_verification') as verifier:
                    assertions = [assess(a, responses[a['step']]) for a in manifest['assertions']]
                    verdict = ('FAIL' if any(a['status'] == 'FAIL' for a in assertions)
                               else 'INCONCLUSIVE' if any(a['status'] == 'INCONCLUSIVE' for a in assertions)
                               else 'PASS')
                    verifier.set_attribute('qa.verdict', verdict)
            parent.set_attribute('qa.verdict', verdict)
    except Exception as exc:
        error = f'{type(exc).__name__}: execution failed'
        verdict = 'INFRA_ERROR'
    finally:
        provider.force_flush(timeout_millis=5000)
    record = {'run_id': run_id, 'project_id': manifest.get('project_id', 'local'),
              'scenario_id': manifest['id'], 'version': manifest.get('version', 'unversioned'),
              'kind': manifest.get('kind', 'fullstack'), 'verdict': verdict, 'trace_id': trace_id,
              'assertions': assertions, 'created_at': utc(), 'error': error,
              'telemetry_export_configured': bool(endpoint),
              'observed': {'steps': observations, 'assertion_results': assertions}}
    result = store.save(record)
    if graph is not None:
        project = result['project_id']
        version = result['version']
        scenario_id = f'{project}:scenario:{manifest["id"]}'
        run_node = f'{project}:run:{run_id}'
        graph.node(scenario_id, 'scenario', version, {'name': manifest['id']}, 'manifest:' + manifest['id'])
        graph.node(run_node, 'run', version, {'verdict': verdict, 'trace_id': trace_id}, 'runner:' + run_id)
        graph.edge(scenario_id, run_node, 'EXECUTED_AS', version, 'runner:' + run_id)
        for assertion in assertions:
            assertion_id = f'{project}:assertion:{manifest["id"]}:{assertion["id"]}'
            graph.node(assertion_id, 'assertion', version, assertion, 'runner:' + run_id)
            graph.edge(run_node, assertion_id, 'EVALUATED_BY', version, 'runner:' + run_id)
    return result

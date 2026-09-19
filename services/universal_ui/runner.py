"""Concurrent UI and server-log QA with independent, non-generative assertions.

Evidence is redacted and content addressed. FAIL = observed mismatch; INCONCLUSIVE
= no independent evidence or unavailable capability; INFRA_ERROR = environment.
"""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from opentelemetry import trace

from services.engine.runner import MISSING, resolve_pointer
from services.engine.store import Store, utc
from services.runtime.wave1 import configure_telemetry
from services.universal_ui.drivers import DriverError, UnsupportedAction, open_driver
from services.universal_ui.evidence import EventStream, FileTail, image_difference, save_screenshot, scrub
from services.universal_ui.spec import MUTATING, validate


def _compare(value, expected, operator):
    if operator == 'exists':
        return (value is not MISSING) == expected if isinstance(expected, bool) else False
    if value is MISSING:
        return False
    if operator == 'equals': return type(value) is type(expected) and value == expected
    if operator == 'not_equals': return value != expected
    if operator == 'contains':
        return type(value) in (str, list, dict) and expected in value
    if operator == 'length_equals':
        return type(value) in (str, list, dict) and type(expected) is int and len(value) == expected
    if operator == 'less_or_equal':
        return type(value) in (int, float) and type(expected) in (int, float) and value <= expected
    raise ValueError('invalid assertion operator')


def _oracle(spec, step):
    """GET only, approved origin, no redirects, bounded response, no raw persistence."""
    headers = {'Accept': 'application/json'}
    if spec.get('oracle_auth_env'):
        headers['Authorization'] = 'Bearer ' + os.environ[spec['oracle_auth_env']]
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=5) as client:
            with client.stream('GET', spec['oracle_origin'] + step['oracle_path'], headers=headers) as response:
                payload = bytearray()
                for part in response.iter_bytes():
                    payload.extend(part)
                    if len(payload) > 1_048_576:
                        raise DriverError('oracle returned oversized response')
                if response.status_code != 200:
                    raise DriverError('oracle returned non-200 HTTP response')
                try:
                    obj = json.loads(payload)
                except ValueError as exc:
                    raise DriverError('oracle returned invalid JSON') from exc
    except httpx.HTTPError as exc:
        raise DriverError('oracle unavailable') from exc
    value = resolve_pointer(obj, step.get('pointer', ''))
    return _compare(value, step['expected'], step['operator']), value is not MISSING


def _audit_accessibility(driver):
    """Basic deterministic heuristic; NOT WCAG conformance certification."""
    if driver.kind != 'web':
        raise UnsupportedAction('accessibility audit requires DOM driver')
    return driver.page.evaluate('''() => {
      const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
      const issues=[];
      for(const image of document.querySelectorAll('img')) {
        if(visible(image) && !image.hasAttribute('alt')) issues.push('image-missing-alt');
      }
      for(const button of document.querySelectorAll('button,[role="button"]')) {
        const name=(button.getAttribute('aria-label')||button.getAttribute('aria-labelledby')||button.innerText||'').trim();
        if(visible(button) && !name) issues.push('button-missing-name');
      }
      for(const input of document.querySelectorAll('input,textarea,select')) {
        if(!visible(input) || ['hidden','submit','button'].includes(input.type)) continue;
        const id=input.id;
        const hasLabel=!!(input.getAttribute('aria-label') || input.getAttribute('aria-labelledby') ||
          (id && document.querySelector('label[for="'+CSS.escape(id)+'"]')) || input.closest('label'));
        if(!hasLabel) issues.push('field-missing-label');
      }
      return {issues:issues.slice(0,100), scanned:true};
    }''')


def _trace_present(output, trace_id, name):
    """Match distributed spans by propagated W3C trace ID, NOT QA-only run attrs."""
    path = Path(output) / 'telemetry.sqlite3'
    if not path.exists(): return None
    with sqlite3.connect(path) as db:
        try:
            found = db.execute('SELECT COUNT(*) FROM spans WHERE trace_id=? AND name=?',
                               (trace_id, name)).fetchone()
        except sqlite3.DatabaseError:
            return None
    return bool(found and found[0])


def _assert(step, driver, events, spec, output, run_id, trace_id):
    action = step['action']
    expected = step.get('expected')
    observed = None
    detail = ''
    snapshot = events.snapshot()
    if action == 'assert_oracle':
        success, exists = _oracle(spec, step)
        if not exists and step['operator'] != 'exists':
            return 'FAIL', 'independent state property missing', 'oracle'
        return ('PASS' if success else 'FAIL'), 'independent state verified' if success else 'independent state mismatch', 'oracle'
    if action == 'assert_log_contains':
        if not spec.get('log_file'):
            return 'INCONCLUSIVE', 'no trusted local log source configured', 'server_log'
        if not spec.get('log_messages'):
            return 'INCONCLUSIVE', 'log message retention not opted in', 'server_log'
        observed = any(str(expected) in x.get('message', '') for x in snapshot if x['source'] == 'server_log')
        return ('PASS' if observed else 'FAIL'), 'server log match' if observed else 'server log match absent', 'server_log'
    if action == 'assert_trace_span':
        deadline = time.monotonic() + step.get('timeout_ms', 1000) / 1000
        while time.monotonic() <= deadline:
            if _trace_present(output, trace_id, str(expected)) is True:
                return 'PASS', 'expected span observed in indexed OTLP trace', 'otlp'
            time.sleep(0.05)
        # Missing spans can reflect sampling, collector latency or missing instrumentation.
        # Without a completion barrier, absence is not proof of app non-execution.
        return 'INCONCLUSIVE', 'expected span not observed before telemetry deadline', 'otlp'
    if action == 'assert_no_server_errors':
        if not spec.get('log_file'):
            return 'INCONCLUSIVE', 'no trusted local server log configured', 'server_log'
        if not spec.get('log_messages'):
            return 'INCONCLUSIVE', 'log messages not opted in', 'server_log'
        errors = [x for x in snapshot if x['source'] == 'server_log' and x['level'] == 'error']
        return ('FAIL' if errors else 'PASS'), 'server error events: ' + str(len(errors)), 'server_log'
    if action in ('assert_no_console_errors', 'assert_no_page_errors', 'assert_no_http_errors'):
        source = {'assert_no_console_errors': ('console', 'page_error'),
                  'assert_no_page_errors': ('page_error',),
                  'assert_no_http_errors': ('network',)}[action]
        if driver.kind != 'web':
            return 'INCONCLUSIVE', 'driver does not expose required event stream', 'driver'
        errors = [x for x in snapshot if x['source'] in source and x['level'] == 'error']
        return ('FAIL' if errors else 'PASS'), 'error events: ' + str(len(errors)), 'live_events'
    if action == 'audit_accessibility':
        issues = _audit_accessibility(driver)['issues']
        return ('FAIL' if issues else 'PASS'), 'basic heuristic issues: ' + ','.join(issues[:5]), 'dom_heuristic'
    if action == 'assert_visual':
        actual = driver.screenshot()
        diff = image_difference(actual, step['baseline'])
        success = diff['ratio'] <= step.get('threshold', 0)
        return ('PASS' if success else 'FAIL'), 'pixel change ratio ' + str(round(diff['ratio'], 5)), 'pixel_diff'
    observed = driver.action(step)
    if action in ('assert_title', 'assert_url', 'assert_text', 'assert_value'):
        # Default to explicit equals unless caller specifies a comparison.
        if action == 'assert_url':
            success = urlsplit(str(observed)).path == expected if str(expected).startswith('/') else observed == expected
        else:
            success = _compare(observed, expected, step.get('operator', 'equals'))
    elif action in ('assert_visible', 'assert_count'):
        success = _compare(observed, expected, 'equals')
    else:
        raise UnsupportedAction('unrecognized assertion')
    # The DOM value is never persisted: it may be a password or account detail.
    return ('PASS' if success else 'FAIL'), 'DOM assertion satisfied' if success else 'DOM assertion mismatched', 'dom'


def _fingerprint(failure):
    basis = '|'.join((failure.get('source', ''), failure.get('action', ''),
                      failure.get('step', ''), failure.get('reason', '')))
    return hashlib.sha256(basis.encode()).hexdigest()[:20]


def diagnose(assertions, events):
    """Transparent, heuristic correlations. Never claims source-code root-cause proof."""
    findings = []
    errors = [x for x in events if x['level'] == 'error']
    for assertion in assertions:
        if assertion['status'] != 'FAIL': continue
        # Include nearby *preceding* errors: asynchronous backend failures often
        # happen during the click, before a later independent-state assertion.
        near = [event for event in errors if max(0, assertion['event_seq_start'] - 25) <= event['seq']
                and event['seq'] <= assertion['event_seq_end']]
        sources = sorted({event['source'] for event in near})
        label = 'state_mismatch' if assertion['source'] == 'oracle' else (
            'visual_regression' if assertion['source'] == 'pixel_diff' else (
                'accessibility_heuristic' if assertion['source'] == 'dom_heuristic' else (
                    'concurrent_runtime_error' if sources else 'ui_assertion_mismatch')))
        item = {'step': assertion['step'], 'action': assertion['action'], 'source': assertion['source'],
                'category': label, 'reason': assertion['reason'],
                'event_seq_start': assertion['event_seq_start'], 'event_seq_end': assertion['event_seq_end'],
                'correlated_event_ids': [x['seq'] for x in near[:20]],
                'correlated_sources': sources, 'correlation_scope': 'preceding_25_events',
                'root_cause_confirmed': False}
        item['fingerprint'] = _fingerprint(item)
        findings.append(item)
    return findings


def execute(spec, output='.local-runs', otlp_endpoint=None, *, local_files=False, graph=None):
    validate(spec, local_files=local_files)
    output = Path(output).resolve()
    stream = EventStream(keep_messages=bool(spec.get('log_messages')))
    store = Store(output)
    run_id = str(uuid4())
    endpoint = otlp_endpoint if otlp_endpoint is not None else os.getenv('QA_OTLP_TRACES_ENDPOINT')
    provider, tracer = configure_telemetry(endpoint)
    trace_id = '0' * 32
    checks = []
    steps = []
    screenshots = []
    verdict = 'INFRA_ERROR'
    error = None
    driver = None
    tail = None
    started = time.monotonic()
    try:
        with tracer.start_as_current_span('qa.ui.run', attributes={
             'qa.run.id': run_id, 'qa.project.id': spec.get('project_id', 'local'),
             'qa.scenario.id': spec['id'], 'qa.kind': 'universal-ui'}) as span:
            trace_id = f'{span.get_span_context().trace_id:032x}'
            if spec.get('log_file'):
                tail = FileTail(spec['log_file'], stream).start()
            driver = open_driver(spec, stream)
            verdict = 'PASS'
            for step in spec['steps']:
                action = step['action']
                begin = stream.last_seq()
                status = 'PASS'
                reason = 'interaction completed'
                source = 'ui_driver'
                stream.add('runner', 'info', 'step started', step=step['name'])
                tick = time.monotonic()
                with tracer.start_as_current_span('qa.ui.step', attributes={
                    'qa.run.id': run_id, 'qa.step.name': step['name'],
                    'qa.action': action}) as child:
                    if spec.get('propagate_trace') and driver.kind == 'web':
                        context = child.get_span_context()
                        driver.traceparent = f'00-{context.trace_id:032x}-{context.span_id:016x}-01'
                    try:
                        if action.startswith('assert_') or action == 'audit_accessibility':
                            status, reason, source = _assert(step, driver, stream, spec, output, run_id, trace_id)
                        elif action == 'screenshot':
                            data = driver.screenshot()
                            if not spec.get('screenshots'):
                                raise ValueError('screenshots not authorized')
                            screenshot = save_screenshot(output, run_id, step['name'], data)
                            screenshots.append({'step': step['name'], 'sha256': screenshot['sha256'], 'bytes': screenshot['bytes']})
                        else:
                            driver.action(step)
                    except UnsupportedAction as exc:
                        status, reason, source = 'INCONCLUSIVE', scrub(exc), 'driver_capability'
                    except (DriverError, httpx.HTTPError) as exc:
                        status, reason, source = 'INFRA_ERROR', scrub(exc), 'transport'
                    except Exception as exc:
                        # A UI lookup/action error may be an app defect, rather than runner failure.
                        if action == 'goto':
                            status, reason, source = 'INFRA_ERROR', 'navigation unavailable: ' + type(exc).__name__, 'transport'
                        elif driver is not None and (action in MUTATING or action == 'wait_for'):
                            status, reason, source = 'FAIL', 'UI interaction failed: ' + type(exc).__name__, 'driver'
                        else:
                            status, reason, source = 'FAIL', 'assertion execution failed: ' + type(exc).__name__, 'driver'
                    elapsed = round((time.monotonic() - tick) * 1000, 2)
                    child.set_attribute('qa.verdict', status)
                    if status != 'PASS':
                        child.set_attribute('qa.failure.source', source)
                # Allow async UI->server log events to arrive before correlation snapshot.
                if tail:
                    time.sleep(0.06)
                end = stream.last_seq()
                entry = {'step': step['name'], 'action': action, 'status': status,
                         'reason': scrub(reason), 'source': source, 'elapsed_ms': elapsed,
                         'event_seq_start': begin, 'event_seq_end': end}
                steps.append(entry)
                if status == 'FAIL' and spec.get('screenshots') and driver:
                    try:
                        image = save_screenshot(output, run_id, step['name'], driver.screenshot())
                        screenshots.append({'step': step['name'], 'sha256': image['sha256'],
                                            'bytes': image['bytes'], 'reason': 'failure'})
                    except Exception:
                        stream.add('runner', 'warning', 'failure screenshot unavailable')
                if action.startswith('assert_') or action == 'audit_accessibility':
                    checks.append(entry)
                if status == 'INFRA_ERROR':
                    verdict = 'INFRA_ERROR'
                    error = 'UI driver or external oracle unavailable'
                    break
                if status == 'FAIL': verdict = 'FAIL'
                elif status == 'INCONCLUSIVE' and verdict == 'PASS': verdict = 'INCONCLUSIVE'
            span.set_attribute('qa.verdict', verdict)
    except Exception as exc:
        error = 'UI setup failed: ' + type(exc).__name__
        verdict = 'INFRA_ERROR'
    finally:
        if tail: tail.stop()
        if driver:
            try: driver.close()
            except Exception: pass
        provider.force_flush(timeout_millis=5000)
    if not checks and verdict == 'PASS':
        verdict = 'INCONCLUSIVE'  # Interactions are not independent proof of correctness.
    if stream.dropped() and verdict == 'PASS':
        verdict = 'INCONCLUSIVE'  # Missing events could hide runtime errors.
    events = stream.snapshot()
    findings = diagnose(checks + [s for s in steps if s not in checks], events)
    if graph is not None:
        from services.universal_ui.localize import attach_candidates
        attach_candidates(graph, spec.get('project_id', 'local'),
                          spec.get('version', 'unversioned'), findings, events)
    observations = {'steps': steps, 'events': events, 'events_dropped': stream.dropped(), 'findings': findings,
                    'screenshots': screenshots, 'event_messages_opted_in': bool(spec.get('log_messages')),
                    'driver': spec.get('driver', 'web'), 'fixture_relay': bool(spec.get('fixture_relay')),
                    'trace_propagation_enabled': bool(spec.get('propagate_trace')),
                    'duration_ms': round((time.monotonic() - started) * 1000, 2)}
    record = {'run_id': run_id, 'project_id': spec.get('project_id', 'local'),
              'scenario_id': spec['id'], 'version': spec.get('version', 'unversioned'),
              'kind': 'universal-ui', 'verdict': verdict, 'trace_id': trace_id,
              'assertions': checks, 'findings': findings, 'screenshots': screenshots,
              'steps_total': len(spec['steps']), 'steps_executed': len(steps),
              'events_dropped': stream.dropped(),
              'created_at': utc(), 'error': error,
              'telemetry_export_configured': bool(endpoint), 'observed': observations}
    result = store.save(record)
    from services.universal_ui.issues import IssueIndex
    IssueIndex(output).add(record)
    if graph is not None:
        project = record['project_id']; version = record['version']
        scenario = f'{project}:scenario:{spec["id"]}'
        execution = f'{project}:run:{run_id}'
        graph.node(scenario, 'scenario', version, {'name': spec['id'], 'driver': spec.get('driver', 'web')}, 'manifest:' + spec['id'])
        graph.node(execution, 'run', version, {'verdict': verdict, 'trace_id': trace_id}, 'runner:' + run_id)
        graph.edge(scenario, execution, 'EXECUTED_AS', version, 'runner:' + run_id)
        for issue in findings:
            issue_id = f'{project}:finding:{issue["fingerprint"]}'
            graph.node(issue_id, 'finding', version, {'category': issue['category'], 'step': issue['step']}, 'runner:' + run_id)
            graph.edge(execution, issue_id, 'EVIDENCED_BY', version, 'runner:' + run_id)
    return result
